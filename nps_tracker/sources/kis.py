"""Korea Investment Open API helpers for daily investor trade data."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Callable, Iterable

from .. import config
from ..io_utils import _read_json, _write_json, _yyyymmdd

logger = logging.getLogger("nps")

TR_ID_INVESTOR_TRADE_BY_STOCK_DAILY = "FHPTJ04160001"
PBMN_TO_KRW = 1_000_000
_DOTENV_CACHE: dict[str, str] | None = None


class KISCredentialsMissing(RuntimeError):
    """Raised when KIS app credentials are not configured."""


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name) or _windows_env(name) or _dotenv_env(name)
        if value:
            return value.strip()
    return None


def _windows_env(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        roots = (
            (winreg.HKEY_CURRENT_USER, "Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        )
        for root, path in roots:
            try:
                with winreg.OpenKey(root, path) as key:
                    value, _ = winreg.QueryValueEx(key, name)
                    if value:
                        return str(value)
            except OSError:
                continue
    except Exception:
        return None
    return None


def _load_dotenv() -> dict[str, str]:
    global _DOTENV_CACHE
    if _DOTENV_CACHE is not None:
        return _DOTENV_CACHE
    env: dict[str, str] = {}
    for filename in (".env.local", ".env"):
        path = os.path.join(config.ROOT, filename)
        try:
            with open(path, encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in env:
                        env[key] = value
        except FileNotFoundError:
            continue
    _DOTENV_CACHE = env
    return env


def _dotenv_env(name: str) -> str | None:
    return _load_dotenv().get(name)


def _credentials() -> tuple[str | None, str | None]:
    app_key = _env_first("KIS_APP_KEY", "KOREAINVESTMENT_APP_KEY", "KOREA_INVESTMENT_APP_KEY")
    app_secret = _env_first("KIS_APP_SECRET", "KOREAINVESTMENT_APP_SECRET", "KOREA_INVESTMENT_APP_SECRET")
    return app_key, app_secret


def _num(v) -> int:
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace(",", "").strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _float(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _iso_date(v) -> str | None:
    s = str(v or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None


def _request_json(method: str, url: str, *, headers=None, query=None, body=None, timeout=20):
    if query:
        url = url + "?" + urllib.parse.urlencode(query)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req_headers = {"User-Agent": config._USER_AGENT}
    req_headers.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
            msg = payload.get("msg1") or payload.get("msg_cd") or raw[:300]
        except Exception:
            msg = raw[:300] if raw else exc.reason
        raise RuntimeError(f"HTTP {exc.code}: {msg}") from exc
    return json.loads(raw)


def _cached_token() -> str | None:
    cached = _read_json(config.KIS_TOKEN_CACHE, {}) or {}
    token = cached.get("access_token")
    expires_at = cached.get("expires_at") or 0
    try:
        if token and float(expires_at) > time.time() + 120:
            return str(token)
    except (TypeError, ValueError):
        return None
    return None


def get_access_token(app_key: str, app_secret: str) -> str:
    explicit = _env_first("KIS_ACCESS_TOKEN", "KOREAINVESTMENT_ACCESS_TOKEN", "KOREA_INVESTMENT_ACCESS_TOKEN")
    if explicit:
        return explicit.removeprefix("Bearer ").strip()

    cached = _cached_token()
    if cached:
        return cached

    payload = _request_json(
        "POST",
        config.KIS_TOKEN_URL,
        headers={"content-type": "application/json; charset=utf-8"},
        body={"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret},
        timeout=20,
    )
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"KIS token response missing access_token: {payload.get('msg1') or payload}")
    expires_in = _num(payload.get("expires_in")) or 23 * 60 * 60
    _write_json(config.KIS_TOKEN_CACHE, {
        "access_token": token,
        "expires_at": time.time() + max(60, expires_in - 120),
    })
    return str(token)


def fetch_investor_trade_by_stock_daily(symbol: str, base_date: str) -> dict:
    """Fetch investor trade-by-stock daily data for one KRX symbol."""
    app_key, app_secret = _credentials()
    if not app_key or not app_secret:
        raise KISCredentialsMissing("KIS_APP_KEY/KIS_APP_SECRET are not configured")

    token = get_access_token(app_key, app_secret)
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": TR_ID_INVESTOR_TRADE_BY_STOCK_DAILY,
        "custtype": "P",
    }
    payload = _request_json(
        "GET",
        config.KIS_INVESTOR_TRADE_URL,
        headers=headers,
        query={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": str(symbol).strip(),
            "FID_INPUT_DATE_1": _yyyymmdd(base_date),
            "FID_ORG_ADJ_PRC": "",
            "FID_ETC_CLS_CODE": "",
        },
        timeout=20,
    )
    rt_cd = payload.get("rt_cd")
    if rt_cd not in (None, "0", 0):
        msg = payload.get("msg1") or payload.get("msg_cd") or payload
        raise RuntimeError(f"KIS investor-trade failed for {symbol}: {msg}")
    return payload


def extract_pension_trade_rows(payload: dict) -> list[dict]:
    """Extract only pension-fund rows from a KIS investor-trade payload."""
    out = []
    for row in payload.get("output2") or []:
        d = _iso_date(row.get("stck_bsop_date"))
        if not d:
            continue
        out.append({
            "date": d,
            "close": _float(row.get("stck_clpr")),
            "netShares": _num(row.get("fund_ntby_qty")),
            "buyShares": _num(row.get("fund_shnu_vol")),
            "sellShares": _num(row.get("fund_seln_vol")),
            "netValue": _num(row.get("fund_ntby_tr_pbmn")) * PBMN_TO_KRW,
            "buyValue": _num(row.get("fund_shnu_tr_pbmn")) * PBMN_TO_KRW,
            "sellValue": _num(row.get("fund_seln_tr_pbmn")) * PBMN_TO_KRW,
        })
    return sorted(out, key=lambda r: r["date"])


def aggregate_pension_trade(
    symbol_rows: Iterable[tuple[str, list[dict]]],
    *,
    as_of: str,
    total_value: float | int | None = None,
    eligible_count: int = 0,
    queried_count: int = 0,
    success_count: int = 0,
    coverage_value: float | int | None = None,
    limit: int | None = None,
) -> dict | None:
    by_date: dict[str, dict] = defaultdict(lambda: {
        "netShares": 0,
        "buyShares": 0,
        "sellShares": 0,
        "netValue": 0,
        "buyValue": 0,
        "sellValue": 0,
        "symbols": 0,
    })
    for _, rows in symbol_rows:
        seen_dates = set()
        for row in rows:
            d = row.get("date")
            if not d or d > as_of:
                continue
            acc = by_date[d]
            acc["netShares"] += _num(row.get("netShares"))
            acc["buyShares"] += _num(row.get("buyShares"))
            acc["sellShares"] += _num(row.get("sellShares"))
            acc["netValue"] += _num(row.get("netValue"))
            acc["buyValue"] += _num(row.get("buyValue"))
            acc["sellValue"] += _num(row.get("sellValue"))
            seen_dates.add(d)
        for d in seen_dates:
            by_date[d]["symbols"] += 1

    if not by_date:
        return None

    tv = float(total_value or 0)
    series = []
    for d in sorted(by_date):
        row = {"date": d, **by_date[d]}
        row["netValuePct"] = (row["netValue"] / tv * 100) if tv else None
        series.append(row)
    latest = series[-1]
    coverage_pct = (float(coverage_value or 0) / tv * 100) if tv else None
    return {
        "source": "KIS Open API",
        "endpoint": "investor-trade-by-stock-daily",
        "trId": TR_ID_INVESTOR_TRADE_BY_STOCK_DAILY,
        "unit": "KRW",
        "asOf": latest["date"],
        "latest": latest,
        "basis": {
            "aggregation": "held domestic stocks",
            "limit": limit if limit and limit > 0 else None,
            "eligible": eligible_count,
            "queried": queried_count,
            "success": success_count,
            "coverageValue": coverage_value,
            "coveragePct": coverage_pct,
            "amountSourceUnit": "million KRW",
        },
        "series": series,
    }


def get_pension_trade_trend(
    holdings: list[dict],
    as_of: str,
    total_value: float | int | None = None,
    *,
    fetcher: Callable[[str, str], dict] | None = None,
) -> dict | None:
    """Aggregate KIS pension-fund daily trades across held domestic stocks."""
    if fetcher is None:
        app_key, app_secret = _credentials()
        if not app_key or not app_secret:
            logger.info("KIS credentials missing; pension trade trend skipped")
            return None
        fetcher = fetch_investor_trade_by_stock_daily

    eligible = [
        h for h in holdings
        if h.get("stock_code") and str(h.get("stock_code")).strip()
    ]
    eligible.sort(key=lambda h: h.get("market_value") or 0, reverse=True)
    limit = getattr(config, "KIS_PENSION_TRADE_LIMIT", 100)
    selected = eligible[:limit] if limit and limit > 0 else eligible
    if not selected:
        return None

    base_date = _yyyymmdd(as_of)
    symbol_rows = []
    failures = 0
    last_error = None
    for h in selected:
        code = str(h.get("stock_code")).strip()
        try:
            payload = fetcher(code, base_date)
            rows = extract_pension_trade_rows(payload)
            if rows:
                symbol_rows.append((code, rows))
        except KISCredentialsMissing:
            logger.info("KIS credentials missing; pension trade trend skipped")
            return None
        except Exception as exc:
            failures += 1
            last_error = str(exc)
            if failures <= 5:
                logger.warning("KIS pension trade skipped for %s: %s", code, exc)
        sleep_sec = getattr(config, "KIS_REQUEST_SLEEP_SEC", 0)
        if sleep_sec and fetcher is fetch_investor_trade_by_stock_daily:
            time.sleep(float(sleep_sec))

    if failures > 5:
        logger.warning("KIS pension trade skipped for %d more symbols", failures - 5)

    coverage_value = sum((h.get("market_value") or 0) for h in selected)
    if not symbol_rows and failures:
        return {
            "source": "KIS Open API",
            "endpoint": "investor-trade-by-stock-daily",
            "trId": TR_ID_INVESTOR_TRADE_BY_STOCK_DAILY,
            "unit": "KRW",
            "asOf": as_of,
            "status": "error",
            "error": last_error or "KIS request failed",
            "basis": {
                "aggregation": "held domestic stocks",
                "limit": limit if limit and limit > 0 else None,
                "eligible": len(eligible),
                "queried": len(selected),
                "success": 0,
                "coverageValue": coverage_value,
                "coveragePct": (float(coverage_value or 0) / float(total_value or 0) * 100)
                if total_value else None,
                "amountSourceUnit": "million KRW",
            },
            "series": [],
        }
    return aggregate_pension_trade(
        symbol_rows,
        as_of=as_of,
        total_value=total_value,
        eligible_count=len(eligible),
        queried_count=len(selected),
        success_count=len(symbol_rows),
        coverage_value=coverage_value,
        limit=limit,
    )
