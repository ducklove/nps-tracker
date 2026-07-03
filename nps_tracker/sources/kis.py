"""Korea Investment Open API helpers for daily investor trade data."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

from .. import config
from ..http import _Pacer
from ..io_utils import _read_json, _write_json, _yyyymmdd

logger = logging.getLogger("nps")

TR_ID_INVESTOR_TRADE_BY_STOCK_DAILY = "FHPTJ04160001"
TR_ID_INVESTOR_DAILY_BY_MARKET = "FHPTJ04040000"
TR_ID_DAILY_ITEMCHARTPRICE = "FHKST03010100"
PBMN_TO_KRW = 1_000_000
_DOTENV_CACHE: dict[str, str] | None = None
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MULTILINE_DOTENV_KEYS = {"KIS_APP_SECRET", "KOREAINVESTMENT_APP_SECRET", "KOREA_INVESTMENT_APP_SECRET"}
_KIS_MARKETS = (
    {"name": "KOSPI", "market": "KSP", "symbol": "0001"},
    {"name": "KOSDAQ", "market": "KSQ", "symbol": "1001"},
)


class KISCredentialsMissing(RuntimeError):
    """Raised when KIS app credentials are not configured."""


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name) or _windows_env(name) or _dotenv_env(name)
        if value:
            return value.strip()
    return None


def _compact_secret(value: str | None) -> str | None:
    if value is None:
        return None
    compacted = "".join(value.strip().strip('"').strip("'").split())
    return compacted or None


def _is_env_assignment(line: str) -> bool:
    if "=" not in line:
        return False
    key, _ = line.split("=", 1)
    return bool(_ENV_ASSIGNMENT_RE.fullmatch(key.strip()))


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
                lines = f.read().splitlines()
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    i += 1
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if key in _MULTILINE_DOTENV_KEYS:
                        fragments = []
                        while i < len(lines):
                            next_line = lines[i].strip()
                            if not next_line or next_line.startswith("#") or _is_env_assignment(next_line):
                                break
                            fragments.append(next_line)
                            i += 1
                        if fragments:
                            value += "".join(fragments)
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
    app_key = _compact_secret(_env_first("KIS_APP_KEY", "KOREAINVESTMENT_APP_KEY", "KOREA_INVESTMENT_APP_KEY"))
    app_secret = _compact_secret(_env_first(
        "KIS_APP_SECRET",
        "KOREAINVESTMENT_APP_SECRET",
        "KOREA_INVESTMENT_APP_SECRET",
    ))
    return app_key, app_secret


def _kis_base_url() -> str:
    return (_env_first("KIS_BASE_URL") or config.KIS_BASE_URL).rstrip("/")


def _kis_token_url() -> str:
    return f"{_kis_base_url()}/oauth2/tokenP"


def _kis_investor_trade_url() -> str:
    return f"{_kis_base_url()}/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"


def _kis_investor_daily_by_market_url() -> str:
    return f"{_kis_base_url()}/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market"


def _kis_daily_itemchartprice_url() -> str:
    return f"{_kis_base_url()}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"


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
        return "".join(explicit.removeprefix("Bearer ").strip().split())

    cached = _cached_token()
    if cached:
        return cached

    payload = _request_json(
        "POST",
        _kis_token_url(),
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


def _parse_daily_close_rows(payload: dict) -> list[dict]:
    """inquire-daily-itemchartprice output2 → [{"date", "close"}] (날짜 오름차순, 0/결측 제외)."""
    rows = []
    for r in payload.get("output2") or []:
        if not r:
            continue  # 휴장 구간은 빈 dict 행으로 온다
        d = _iso_date(r.get("stck_bsop_date"))
        close = _float(r.get("stck_clpr"))
        if d and close and close > 0:
            rows.append({"date": d, "close": close})
    rows.sort(key=lambda r: r["date"])
    return rows


def fetch_daily_closes(codes: list[str], since: str, until: str, *,
                       fetcher: Callable[[str, str, str], list[dict]] | None = None,
                       ) -> tuple[bool, dict[str, list[dict]]]:
    """KIS 일자별 시세로 여러 종목 종가를 병렬 조회 — (API 사용 가능 여부, {종목코드: rows}).

    공식 API라 pykrx(KRX 화면 스크레이핑)보다 빠르고(병렬 ~14 req/s) 차단 위험이 없다.
    첫 종목을 동기 probe로 호출해 자격증명·토큰 문제면 (False, {})를 반환(→ pykrx 폴백).
    이후 병렬 조회에서 개별 실패 종목은 결과에서 빠져 폴백 대상이 된다.
    수정주가(FID_ORG_ADJ_PRC=0) 기준 — pykrx get_market_ohlcv(adjusted=True 기본)과 동일.
    KIS 응답은 종목당 최근 100행까지만이므로 긴 구간은 호출부에서 pykrx 경로를 써야 한다.
    """
    if not codes:
        return False, {}
    if fetcher is None:
        app_key, app_secret = _credentials()
        if not app_key or not app_secret:
            logger.info("KIS 자격증명 없음 → KIS 시세 생략(pykrx 사용)")
            return False, {}
        try:
            token = get_access_token(app_key, app_secret)
        except Exception as exc:
            logger.warning("KIS 토큰 발급 실패 → pykrx 폴백: %s", exc)
            return False, {}
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": TR_ID_DAILY_ITEMCHARTPRICE,
            "custtype": "P",
        }
        url = _kis_daily_itemchartprice_url()

        def fetcher(code: str, s: str, u: str) -> list[dict]:
            payload = _request_json("GET", url, headers=headers, query={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": _yyyymmdd(s),
                "FID_INPUT_DATE_2": _yyyymmdd(u),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            })
            if payload.get("rt_cd") not in (None, "0", 0):
                raise RuntimeError(payload.get("msg1") or payload.get("msg_cd") or "KIS error")
            return _parse_daily_close_rows(payload)

    pacer = _Pacer(config.KIS_PRICE_INTERVAL_SEC)
    out: dict[str, list[dict]] = {}

    # probe: 토큰/권한 문제라면 전 종목이 같은 이유로 실패하므로 1건으로 판정하고 즉시 물러난다.
    pacer.wait()
    try:
        rows = fetcher(codes[0], since, until)
        if rows:
            out[codes[0]] = rows
    except Exception as exc:
        logger.warning("KIS 시세 probe 실패(%s) → pykrx 폴백: %s", codes[0], exc)
        return False, {}

    rest = codes[1:]
    if rest:
        def one(code: str):
            pacer.wait()
            try:
                return code, fetcher(code, since, until)
            except Exception:
                return code, None  # 개별 실패는 폴백 대상으로 남긴다

        with ThreadPoolExecutor(max_workers=min(config.KIS_PRICE_WORKERS, len(rest))) as ex:
            for code, rows in ex.map(one, rest):
                if rows:
                    out[code] = rows
    return True, out


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
        _kis_investor_trade_url(),
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


def fetch_investor_daily_by_market(market: str, base_date: str) -> dict:
    """Fetch daily market-level investor trade data for KOSPI or KOSDAQ."""
    spec = next((m for m in _KIS_MARKETS if m["name"] == market), None)
    if not spec:
        raise ValueError(f"Unsupported KIS market: {market}")
    app_key, app_secret = _credentials()
    if not app_key or not app_secret:
        raise KISCredentialsMissing("KIS_APP_KEY/KIS_APP_SECRET are not configured")

    token = get_access_token(app_key, app_secret)
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": TR_ID_INVESTOR_DAILY_BY_MARKET,
        "custtype": "P",
    }
    ymd = _yyyymmdd(base_date)
    payload = _request_json(
        "GET",
        _kis_investor_daily_by_market_url(),
        headers=headers,
        query={
            # KIS market/sector investor endpoint accepts "U"; "J" is for stock-level queries.
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": spec["symbol"],
            "FID_INPUT_DATE_1": ymd,
            "FID_INPUT_ISCD_1": spec["market"],
            "FID_INPUT_DATE_2": ymd,
            "FID_INPUT_ISCD_2": spec["symbol"],
        },
        timeout=20,
    )
    rt_cd = payload.get("rt_cd")
    if rt_cd not in (None, "0", 0):
        msg = payload.get("msg1") or payload.get("msg_cd") or payload
        raise RuntimeError(f"KIS investor-daily-by-market failed for {market}: {msg}")
    return payload


def extract_pension_market_trade_rows(payload: dict, market: str) -> list[dict]:
    """Extract pension-fund net trade rows from a KIS market-level payload."""
    out = []
    for row in payload.get("output") or []:
        d = _iso_date(row.get("stck_bsop_date"))
        if not d:
            continue
        out.append({
            "date": d,
            "market": market,
            "close": _float(row.get("bstp_nmix_prpr")),
            "netShares": _num(row.get("fund_ntby_qty")),
            "netValue": _num(row.get("fund_ntby_tr_pbmn")) * PBMN_TO_KRW,
        })
    return sorted(out, key=lambda r: r["date"])


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


def aggregate_market_pension_trade(
    market_rows: Iterable[tuple[str, list[dict]]],
    *,
    as_of: str,
    total_value: float | int | None = None,
    queried_count: int = 0,
    success_count: int = 0,
) -> dict | None:
    by_date: dict[str, dict] = defaultdict(lambda: {
        "netShares": 0,
        "netValue": 0,
        "markets": 0,
        "marketValues": {},
    })
    for market, rows in market_rows:
        seen_dates = set()
        for row in rows:
            d = row.get("date")
            if not d or d > as_of:
                continue
            value = _num(row.get("netValue"))
            acc = by_date[d]
            acc["netShares"] += _num(row.get("netShares"))
            acc["netValue"] += value
            acc["marketValues"][market] = value
            seen_dates.add(d)
        for d in seen_dates:
            by_date[d]["markets"] += 1

    if not by_date:
        return None

    tv = float(total_value or 0)
    series = []
    for d in sorted(by_date):
        row = {"date": d, **by_date[d]}
        row["netValuePct"] = (row["netValue"] / tv * 100) if tv else None
        series.append(row)
    latest = series[-1]
    return {
        "source": "KIS Open API",
        "endpoint": "inquire-investor-daily-by-market",
        "trId": TR_ID_INVESTOR_DAILY_BY_MARKET,
        "unit": "KRW",
        "asOf": latest["date"],
        "latest": latest,
        "basis": {
            "aggregation": "KOSPI + KOSDAQ markets",
            "markets": [m["name"] for m in _KIS_MARKETS],
            "queried": queried_count,
            "success": success_count,
            "amountSourceUnit": "million KRW",
        },
        "series": series,
    }


def get_market_pension_trade_trend(
    as_of: str,
    total_value: float | int | None = None,
    *,
    fetcher: Callable[[str, str], dict] | None = None,
) -> dict | None:
    """Aggregate KIS pension-fund daily trades across KOSPI and KOSDAQ markets."""
    if fetcher is None:
        app_key, app_secret = _credentials()
        if not app_key or not app_secret:
            logger.info("KIS credentials missing; market pension trade trend skipped")
            return None
        fetcher = fetch_investor_daily_by_market

    base_date = _yyyymmdd(as_of)
    market_rows = []
    failures = 0
    attempted = 0
    last_error = None
    for spec in _KIS_MARKETS:
        market = spec["name"]
        attempted += 1
        try:
            payload = fetcher(market, base_date)
            rows = extract_pension_market_trade_rows(payload, market)
            if rows:
                market_rows.append((market, rows))
        except KISCredentialsMissing:
            logger.info("KIS credentials missing; market pension trade trend skipped")
            return None
        except Exception as exc:
            failures += 1
            last_error = str(exc)
            logger.warning("KIS market pension trade skipped for %s: %s", market, exc)

    if not market_rows and failures:
        return {
            "source": "KIS Open API",
            "endpoint": "inquire-investor-daily-by-market",
            "trId": TR_ID_INVESTOR_DAILY_BY_MARKET,
            "unit": "KRW",
            "asOf": as_of,
            "status": "error",
            "error": last_error or "KIS market request failed",
            "basis": {
                "aggregation": "KOSPI + KOSDAQ markets",
                "markets": [m["name"] for m in _KIS_MARKETS],
                "queried": attempted,
                "success": 0,
                "amountSourceUnit": "million KRW",
            },
            "series": [],
        }

    return aggregate_market_pension_trade(
        market_rows,
        as_of=as_of,
        total_value=total_value,
        queried_count=attempted,
        success_count=len(market_rows),
    )


def get_pension_trade_trend(
    holdings: list[dict],
    as_of: str,
    total_value: float | int | None = None,
    *,
    fetcher: Callable[[str, str], dict] | None = None,
    market_fetcher: Callable[[str, str], dict] | None = None,
) -> dict | None:
    """Aggregate KIS pension-fund daily trades.

    The production path uses KIS market-level KOSPI/KOSDAQ daily data. Passing
    fetcher keeps the older held-stock aggregation path available for tests and
    narrow diagnostics.
    """
    if fetcher is None:
        return get_market_pension_trade_trend(
            as_of,
            total_value=total_value,
            fetcher=market_fetcher,
        )

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
    attempted = 0
    last_error = None
    for h in selected:
        code = str(h.get("stock_code")).strip()
        attempted += 1
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
            if failures >= 5 and not symbol_rows:
                logger.warning("KIS pension trade aborted after %d consecutive failures", failures)
                break
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
                "queried": attempted,
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
        queried_count=attempted,
        success_count=len(symbol_rows),
        coverage_value=coverage_value,
        limit=limit,
    )
