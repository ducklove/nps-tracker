"""시장 가격 수집 — KIS 일자별 시세(공식 API, 병렬) → pykrx 단일종목 → yfinance 폴백,
KOSPI(^KS11) + 가격 증분 캐시.

캐시(data/price_cache.json) 형식:
  {"<종목코드>": [{"date": "YYYY-MM-DD", "close": float}, ...],
   "_KOSPI": [{"date": ..., "value": ...}, ...],
   "_meta": {"since": "YYYY-MM-DD"}}   # 과거 전체 조회가 커버한 시작일(증분 판단용)

캐시에 있는 과거 날짜는 재조회·덮어쓰기하지 않는다(발행 이력 재현성 확보가 목적).
yfinance 데이터 재작성(기업행위 소급 등)에 대응할 때는 --refresh-prices로 전체 재조회한다.

일 배치의 증분 구간(보통 1~3일)은 KIS 병렬 조회로 ~75초에 끝난다(pykrx 직렬 ≈ 7분).
KIS 자격증명이 없거나 구간이 100행 한도를 넘으면 기존 pykrx 경로를 그대로 쓴다.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from .. import config
from ..io_utils import _read_json, _write_json, _yyyymmdd

logger = logging.getLogger("nps")

KOSPI_CACHE_KEY = "_KOSPI"
META_CACHE_KEY = "_meta"


def fetch_prices_kis(codes: list[str], since: str, until: str) -> tuple[bool, dict[str, list[dict]]]:
    """KIS 일자별 시세(공식 API, 병렬) — (사용 가능 여부, {종목코드: rows}).

    자격증명 없음·토큰 실패·예외 시 (False, {}) → 호출부가 pykrx로 폴백한다.
    """
    try:
        from .kis import fetch_daily_closes
        return fetch_daily_closes(codes, since, until)
    except Exception as exc:
        logger.warning("KIS 시세 경로 오류(pykrx 폴백): %s", exc)
        return False, {}


def fetch_prices_pykrx(codes: list[str], since: str, until: str) -> dict[str, list[dict]]:
    """pykrx 단일종목 일별 종가(원주가). 전종목/지수 엔드포인트는 1.2.4에서 깨져 있어 단일종목 경로만 사용."""
    try:
        from pykrx import stock
    except Exception as exc:
        logger.warning("pykrx 임포트 실패: %s", exc)
        return {}
    out: dict[str, list[dict]] = {}
    fs, us = _yyyymmdd(since), _yyyymmdd(until)
    for i, code in enumerate(codes):
        try:
            df = stock.get_market_ohlcv(fs, us, code)
            if df is not None and len(df):
                rows = [
                    {"date": idx.strftime("%Y-%m-%d"), "close": float(r["종가"])}
                    for idx, r in df.iterrows()
                    if float(r["종가"]) > 0
                ]
                if rows:
                    out[code] = rows
        except Exception:
            pass
        if (i + 1) % 100 == 0:
            logger.info("pykrx 진행 %d/%d", i + 1, len(codes))
    return out


def fetch_prices_yf(codes: list[str], since: str, until: str) -> dict[str, list[dict]]:
    """yfinance 폴백(병렬). 한국 종목은 .KS(코스피)/.KQ(코스닥) 접미사를 차례로 시도."""
    try:
        import yfinance as yf
    except Exception:
        return {}
    end = (date.fromisoformat(until) + timedelta(days=1)).isoformat()

    def one(code: str) -> tuple[str, list[dict] | None]:
        for suffix in (".KS", ".KQ"):
            try:
                h = yf.Ticker(code + suffix).history(start=since, end=end, auto_adjust=False)
                if len(h):
                    rows = [
                        {"date": idx.strftime("%Y-%m-%d"), "close": float(c)}
                        for idx, c in h["Close"].items()
                        if c == c and c > 0
                    ]
                    if rows:
                        return code, rows
            except Exception:
                pass
        return code, None

    out: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(codes)))) as ex:
        for code, rows in ex.map(one, codes):
            if rows:
                out[code] = rows
    return out


def fetch_kospi(since: str, until: str) -> list[dict]:
    """KOSPI 지수 시계열(yfinance ^KS11). pykrx 지수 엔드포인트가 깨져 있어 yfinance 사용."""
    try:
        import yfinance as yf
    except Exception:
        return []
    end = (date.fromisoformat(until) + timedelta(days=1)).isoformat()
    try:
        h = yf.Ticker("^KS11").history(start=since, end=end, auto_adjust=False)
        return [
            {"date": idx.strftime("%Y-%m-%d"), "value": round(float(c), 2)}
            for idx, c in h["Close"].items()
            if c == c
        ]
    except Exception as exc:
        logger.warning("KOSPI 조회 실패: %s", exc)
        return []


def _fetch_market_monthly() -> tuple[dict, dict]:
    """yfinance 월말 종가: (S&P500 {period:val}, USD/KRW {period:val}). 추정 입력용."""
    try:
        import yfinance as yf
    except Exception:
        return {}, {}
    res: dict[str, dict] = {}
    for tk, key in (("^GSPC", "sp"), ("KRW=X", "usd")):
        try:
            h = yf.Ticker(tk).history(period="3y", auto_adjust=False)["Close"]
            me = h.resample("ME").last()
            res[key] = {f"{i.year}-{i.month:02d}": float(v) for i, v in me.items() if v == v and v > 0}
        except Exception as exc:
            logger.warning("%s 월말 조회 실패: %s", tk, exc)
            res[key] = {}
    return res.get("sp", {}), res.get("usd", {})


def _close_on_before(rows: list[dict], target: str) -> tuple[float | None, float | None]:
    """target 이하의 최신 종가와 그 직전 종가."""
    valid = sorted([r for r in rows if r.get("close")], key=lambda r: r["date"])
    valid = [r for r in valid if r["date"] <= target]
    if not valid:
        return None, None
    latest = valid[-1]["close"]
    prev = valid[-2]["close"] if len(valid) >= 2 else None
    return latest, prev


# ---------- 가격 증분 캐시 ----------
def load_price_cache() -> dict:
    cache = _read_json(config.PRICE_CACHE, {}) or {}
    return cache if isinstance(cache, dict) else {}


def save_price_cache(cache: dict) -> None:
    _write_json(config.PRICE_CACHE, cache)


def _merge_rows(cached: list[dict], fetched: list[dict]) -> list[dict]:
    """날짜 기준 병합·정렬·중복 제거. 같은 날짜는 캐시 값 우선(과거 날짜 불변 = 이력 재현성)."""
    by_date = {r["date"]: r for r in fetched or [] if r.get("date")}
    by_date.update({r["date"]: r for r in cached or [] if r.get("date")})
    return [by_date[d] for d in sorted(by_date)]


def _plan_fetch(cached_rows: list[dict] | None, since: str, until: str,
                covered_from: str | None = None) -> str | None:
    """캐시 상태에 따른 조회 시작일을 계산.

    반환: None=조회 불필요(캐시가 until까지 커버), since=전체 조회, 그 외=증분 시작일(캐시 마지막+1일).
    캐시 첫 날짜가 since보다 늦으면 앞 구간이 비었을 수 있어 전체 재조회한다. 단, 이전 전체 조회가
    since 이전부터 커버했음이 _meta에 기록돼 있으면(covered_from ≤ since) 첫 거래일이 since 뒤여도
    정상이므로 증분만 조회한다(since는 보통 휴장일 포함 src_date-10일이라 첫 종가가 since 뒤에 온다).
    """
    dates = sorted(r["date"] for r in cached_rows or [] if r.get("date"))
    if not dates:
        return since
    head_covered = (covered_from is not None and covered_from <= since) or dates[0] <= since
    if not head_covered:
        return since  # 캐시 첫 날짜 > since → 부족 구간을 채우기 위해 전체 재조회
    if dates[-1] >= until:
        return None
    return (date.fromisoformat(dates[-1]) + timedelta(days=1)).isoformat()


def get_prices_cached(codes: list[str], since: str, until: str,
                      refresh: bool = False) -> dict[str, list[dict]]:
    """종가 조회(증분 캐시). 종목별로 캐시 마지막 날짜 이후 구간만 pykrx→yfinance로 받아 병합한다.

    refresh=True면 캐시를 무시하고 전체 재조회(캐시도 새 값으로 교체).
    캐시가 없으면 기존과 동일하게 전체 조회한다.
    """
    cache = load_price_cache()
    covered_from = ((cache.get(META_CACHE_KEY) or {}).get("since")) if not refresh else None
    groups: dict[str, list[str]] = defaultdict(list)  # 조회 시작일 → 종목 리스트
    for code in codes:
        fsince = since if refresh else _plan_fetch(cache.get(code), since, until, covered_from)
        if fsince:
            groups[fsince].append(code)
    n_fetch = sum(len(g) for g in groups.values())
    if n_fetch < len(codes):
        logger.info("가격 캐시 적중 %d/%d종목 (신규 조회 %d종목)", len(codes) - n_fetch, len(codes), n_fetch)
    fetched: dict[str, list[dict]] = {}
    for fsince, group in sorted(groups.items()):
        got: dict[str, list[dict]] = {}
        kis_ok = False
        span_days = (date.fromisoformat(until) - date.fromisoformat(fsince)).days
        if span_days <= config.KIS_PRICE_MAX_CAL_DAYS:  # KIS는 종목당 최근 100행 한도
            kis_ok, got = fetch_prices_kis(group, fsince, until)
            if kis_ok and not got and len(group) >= config.PRICE_HOLIDAY_SKIP_MIN_CODES:
                # API는 정상인데 대량 종목이 전부 빈 응답 = 조회 구간이 통째로 휴장.
                # 종목별 pykrx/yf 재확인(수십 분)을 생략한다.
                logger.info("KIS 시세 %d종목 전부 빈 응답(%s~%s) — 휴장 구간으로 보고 폴백 생략",
                            len(group), fsince, until)
                continue
        missing = [c for c in group if c not in got]
        if missing:
            if kis_ok:
                logger.info("KIS 미수신 %d종목 → pykrx 폴백", len(missing))
            pk = fetch_prices_pykrx(missing, fsince, until)
            got.update(pk)
            missing = [c for c in missing if c not in pk]
            if missing:
                logger.info("pykrx 미수신 %d종목 → yfinance 폴백", len(missing))
                got.update(fetch_prices_yf(missing, fsince, until))
        fetched.update(got)
    out: dict[str, list[dict]] = {}
    for code in codes:
        cached_rows = [] if refresh else (cache.get(code) or [])
        rows = _merge_rows(cached_rows, fetched.get(code, []))
        if rows:
            out[code] = rows
            cache[code] = rows
    meta = cache.get(META_CACHE_KEY) or {}
    meta["since"] = min(filter(None, [None if refresh else meta.get("since"), since]))
    cache[META_CACHE_KEY] = meta
    save_price_cache(cache)
    return out


def get_kospi_cached(since: str, until: str, refresh: bool = False) -> list[dict]:
    """KOSPI 지수 조회(증분 캐시). 종목 캐시와 같은 파일의 "_KOSPI" 키에 캐싱한다."""
    cache = load_price_cache()
    covered_from = ((cache.get(META_CACHE_KEY) or {}).get("since")) if not refresh else None
    cached_rows = [] if refresh else (cache.get(KOSPI_CACHE_KEY) or [])
    fsince = since if refresh else _plan_fetch(cached_rows, since, until, covered_from)
    fetched = fetch_kospi(fsince, until) if fsince else []
    rows = _merge_rows(cached_rows, fetched)
    if rows:
        cache[KOSPI_CACHE_KEY] = rows
        save_price_cache(cache)
    return rows
