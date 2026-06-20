"""공공데이터포털(data.go.kr) 수집 — 국내주식 투자정보(보유내역) · 기금 포트폴리오 현황."""
from __future__ import annotations

import csv
import io
import logging
import os
import re
from datetime import date, timedelta

from .. import config
from ..http import _decode_csv, _download
from ..io_utils import _pf, _pi
from ..resolver import load_resolver, resolve_code

logger = logging.getLogger("nps")


def _discover_public_csv() -> tuple[str, str]:
    text = _download(config.PUBLIC_NPS_PAGE_URL).decode("utf-8", "replace")
    m = config._PUBLIC_CSV_URL_RE.search(text)
    url = m.group(1).replace("&amp;", "&") if m else config.PUBLIC_NPS_FALLBACK_CSV_URL
    dm = config._PUBLIC_DATASET_RE.search(text)
    src_date = (
        f"{dm.group(1)[:4]}-{dm.group(1)[4:6]}-{dm.group(1)[6:8]}" if dm else config.PUBLIC_NPS_FALLBACK_DATE
    )
    return url, src_date


def fetch_public_holdings() -> tuple[list[dict], str]:
    """공공데이터 CSV에서 보유내역(종목명/연말평가액/지분율)을 파싱. shares는 없음(추정 대상)."""
    discover = os.getenv("NPS_PUBLIC_DATA_DISCOVER", "1").strip().lower() not in {"0", "false", "no", "off"}
    csv_url, source_date = config.PUBLIC_NPS_FALLBACK_CSV_URL, config.PUBLIC_NPS_FALLBACK_DATE
    if discover:
        try:
            csv_url, source_date = _discover_public_csv()
        except Exception as exc:
            logger.warning("공공데이터 discover 실패, fallback URL 사용: %s", exc)
    payload = _download(csv_url, referer=config.PUBLIC_NPS_PAGE_URL)
    reader = csv.DictReader(io.StringIO(_decode_csv(payload)))
    rows: list[dict] = []
    for row in reader:
        rank = _pi(row.get("번호"))
        name = str(row.get("종목명") or "").strip()
        amount_eok = _pf(row.get("평가액(억 원)"))
        ownership = _pf(row.get("지분율(퍼센트)"))
        if not rank or not name or amount_eok is None:
            continue
        rows.append({
            "name": name,
            "source_market_value": round(amount_eok * 100_000_000),
            "ownership_pct": ownership or 0.0,
            "rank": rank,
        })
    return rows, source_date


def get_public_holdings() -> tuple[list[dict], str] | None:
    """공공데이터 보유내역(매핑 완료, 추정수량 전). 실패하거나 매핑이 빈약하면 None."""
    try:
        rows, src_date = fetch_public_holdings()
    except Exception as exc:
        logger.warning("공공데이터 수집 실패: %s", exc)
        return None
    if not rows:
        return None
    resolver = load_resolver()
    resolved = []
    for r in rows:
        code = resolve_code(r["name"], resolver)
        if code and len(code) == 6:
            item = dict(r)
            item["stock_code"] = code
            resolved.append(item)
    if len(resolved) < config.MIN_RESOLVED_HOLDINGS:
        logger.warning("공공데이터 코드 매핑 부족(%d) → seed 폴백", len(resolved))
        return None
    logger.info("공공데이터 %s: %d종목 중 %d종목 매핑", src_date, len(rows), len(resolved))
    return resolved, src_date


# ---------- 해외주식 투자정보(F-9): 연 1회 스냅샷 + 현재가 기반 추정 ----------
_FOREIGN_META = {
    "APPLE INC": {"ticker": "AAPL", "country": "미국", "currency": "USD"},
    "NVIDIA CORP": {"ticker": "NVDA", "country": "미국", "currency": "USD"},
    "MICROSOFT CORP": {"ticker": "MSFT", "country": "미국", "currency": "USD"},
    "AMAZON.COM INC": {"ticker": "AMZN", "country": "미국", "currency": "USD"},
    "META PLATFORMS INC CLASS A": {"ticker": "META", "country": "미국", "currency": "USD"},
    "INVESCO MSCI USA ETF": {"ticker": "MXUS.L", "country": "아일랜드(ETF)", "currency": "USD"},
    "ALPHABET INC CL A": {"ticker": "GOOGL", "country": "미국", "currency": "USD"},
    "ALPHABET INC CL C": {"ticker": "GOOG", "country": "미국", "currency": "USD"},
    "BROADCOM INC": {"ticker": "AVGO", "country": "미국", "currency": "USD"},
    "TESLA INC": {"ticker": "TSLA", "country": "미국", "currency": "USD"},
    "TAIWAN SEMICONDUCTOR SP ADR": {"ticker": "TSM", "country": "대만(ADR)", "currency": "USD"},
    "ISHARES CORE S+P 500 ETF": {"ticker": "IVV", "country": "미국(ETF)", "currency": "USD"},
    "JPMORGAN CHASE + CO": {"ticker": "JPM", "country": "미국", "currency": "USD"},
    "TAIWAN SEMICONDUCTOR MANUFAC": {"ticker": "2330.TW", "country": "대만", "currency": "TWD"},
    "UNITEDHEALTH GROUP INC": {"ticker": "UNH", "country": "미국", "currency": "USD"},
    "VISA INC CLASS A SHARES": {"ticker": "V", "country": "미국", "currency": "USD"},
    "MASTERCARD INC A": {"ticker": "MA", "country": "미국", "currency": "USD"},
    "NETFLIX INC": {"ticker": "NFLX", "country": "미국", "currency": "USD"},
    "EXXON MOBIL CORP": {"ticker": "XOM", "country": "미국", "currency": "USD"},
    "ELI LILLY + CO": {"ticker": "LLY", "country": "미국", "currency": "USD"},
    "COSTCO WHOLESALE CORP": {"ticker": "COST", "country": "미국", "currency": "USD"},
    "BERKSHIRE HATHAWAY INC CL B": {"ticker": "BRK-B", "country": "미국", "currency": "USD"},
    "PROCTER + GAMBLE CO/THE": {"ticker": "PG", "country": "미국", "currency": "USD"},
    "NOVO NORDISK A/S B": {"ticker": "NOVO-B.CO", "country": "덴마크", "currency": "DKK"},
    "TENCENT HOLDINGS LTD": {"ticker": "0700.HK", "country": "중국", "currency": "HKD"},
    "JOHNSON + JOHNSON": {"ticker": "JNJ", "country": "미국", "currency": "USD"},
    "SALESFORCE INC": {"ticker": "CRM", "country": "미국", "currency": "USD"},
    "ORACLE CORP": {"ticker": "ORCL", "country": "미국", "currency": "USD"},
    "ROCHE HOLDING AG GENUSSCHEIN": {"ticker": "RO.SW", "country": "스위스", "currency": "CHF"},
    "BANK OF AMERICA CORP": {"ticker": "BAC", "country": "미국", "currency": "USD"},
    "INTUITIVE SURGICAL INC": {"ticker": "ISRG", "country": "미국", "currency": "USD"},
    "BOOKING HOLDINGS INC": {"ticker": "BKNG", "country": "미국", "currency": "USD"},
    "WALMART INC": {"ticker": "WMT", "country": "미국", "currency": "USD"},
    "ASML HOLDING NV": {"ticker": "ASML.AS", "country": "네덜란드", "currency": "EUR"},
    "SERVICENOW INC": {"ticker": "NOW", "country": "미국", "currency": "USD"},
    "HOME DEPOT INC": {"ticker": "HD", "country": "미국", "currency": "USD"},
    "CISCO SYSTEMS INC": {"ticker": "CSCO", "country": "미국", "currency": "USD"},
    "HCA HEALTHCARE INC": {"ticker": "HCA", "country": "미국", "currency": "USD"},
    "ADOBE INC": {"ticker": "ADBE", "country": "미국", "currency": "USD"},
    "MERCK + CO. INC.": {"ticker": "MRK", "country": "미국", "currency": "USD"},
    "ABBVIE INC": {"ticker": "ABBV", "country": "미국", "currency": "USD"},
    "NOVARTIS AG REG": {"ticker": "NOVN.SW", "country": "스위스", "currency": "CHF"},
    "CHEVRON CORP": {"ticker": "CVX", "country": "미국", "currency": "USD"},
    "ACCENTURE PLC CL A": {"ticker": "ACN", "country": "아일랜드", "currency": "USD"},
    "SAP SE": {"ticker": "SAP.DE", "country": "독일", "currency": "EUR"},
    "INVESCO MSCI USA UCITS ETF": {"ticker": "MXUS.L", "country": "아일랜드(ETF)", "currency": "USD"},
    "COMPASS GROUP PLC": {"ticker": "CPG.L", "country": "영국", "currency": "GBP", "price_scale": 0.01},
    "TJX COMPANIES INC": {"ticker": "TJX", "country": "미국", "currency": "USD"},
    "QUALCOMM INC": {"ticker": "QCOM", "country": "미국", "currency": "USD"},
    "COMCAST CORP CLASS A": {"ticker": "CMCSA", "country": "미국", "currency": "USD"},
    "THE CIGNA GROUP": {"ticker": "CI", "country": "미국", "currency": "USD"},
    "UNILEVER PLC": {"ticker": "ULVR.L", "country": "영국", "currency": "GBP", "price_scale": 0.01},
    "ING GROEP NV": {"ticker": "INGA.AS", "country": "네덜란드", "currency": "EUR"},
    "WELLS FARGO + CO": {"ticker": "WFC", "country": "미국", "currency": "USD"},
    "LVMH MOET HENNESSY LOUIS VUI": {"ticker": "MC.PA", "country": "프랑스", "currency": "EUR"},
    "CITIGROUP INC": {"ticker": "C", "country": "미국", "currency": "USD"},
    "HITACHI LTD": {"ticker": "6501.T", "country": "일본", "currency": "JPY"},
    "SIEMENS AG REG": {"ticker": "SIE.DE", "country": "독일", "currency": "EUR"},
    "BNP PARIBAS": {"ticker": "BNP.PA", "country": "프랑스", "currency": "EUR"},
}

_FX_TICKERS = {
    "USD": "KRW=X",
    "EUR": "EURKRW=X",
    "GBP": "GBPKRW=X",
    "CHF": "CHFKRW=X",
    "DKK": "DKKKRW=X",
    "HKD": "HKDKRW=X",
    "JPY": "JPYKRW=X",
    "TWD": "TWDKRW=X",
}
_FX_USD_CROSS_TICKERS = {
    "DKK": "DKK=X",  # USD/DKK. DKKKRW=X는 과거 이력이 자주 비어 있어 교차환율로 보완한다.
}


def _norm_foreign_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().upper())


def _foreign_meta(name: str) -> dict:
    return dict(_FOREIGN_META.get(_norm_foreign_name(name), {}))


def _col(row: dict, *substrs: str) -> str | None:
    """헤더 표기 변동(공백·괄호 차이)을 흡수해 부분일치로 컬럼 값을 찾는다."""
    for key, val in row.items():
        k = str(key or "")
        if all(s in k for s in substrs):
            return val
    return None


def fetch_foreign_holdings() -> tuple[list[dict], str]:
    """해외주식 CSV(discover 전용) → [{name, value(원), weight_pct, ownership_pct}], 기준일.

    원본에는 티커가 없으므로 가격 재평가는 별도 메타 매핑이 가능한 상위 종목에 한정한다.
    """
    html = _download(config.PUBLIC_FOREIGN_PAGE_URL, retries=1).decode("utf-8", "replace")
    m = config._PUBLIC_CSV_URL_RE.search(html)
    if not m:
        raise RuntimeError("해외주식 CSV URL discover 실패")
    csv_url = m.group(1).replace("&amp;", "&")
    dm = config._FOREIGN_DATASET_RE.search(html)
    if not dm:
        raise RuntimeError("해외주식 기준일 discover 실패")
    src_date = f"{dm.group(1)[:4]}-{dm.group(1)[4:6]}-{dm.group(1)[6:8]}"
    payload = _download(csv_url, referer=config.PUBLIC_FOREIGN_PAGE_URL, retries=1)
    reader = csv.DictReader(io.StringIO(_decode_csv(payload)))
    rows: list[dict] = []
    for row in reader:
        name = str(_col(row, "종목명") or "").strip()
        amount_eok = _pf(_col(row, "평가액"))
        if not name or not amount_eok:
            continue
        rows.append({
            "name": name,
            "value": round(amount_eok * 100_000_000),
            "weight_pct": _pf(_col(row, "비중")),
            "ownership_pct": _pf(_col(row, "지분율")),
            "country": str(_col(row, "국가") or "").strip() or None,
        })
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows, src_date


def _fetch_yf_history(symbol: str, since: str, until: str, value_key: str) -> list[dict]:
    try:
        import yfinance as yf
    except Exception:
        return []
    end = (date.fromisoformat(until) + timedelta(days=1)).isoformat()
    try:
        h = yf.Ticker(symbol).history(start=since, end=end, auto_adjust=False)
        if h is None or not len(h):
            return []
        return [
            {"date": idx.strftime("%Y-%m-%d"), value_key: float(v)}
            for idx, v in h["Close"].items()
            if v == v and v > 0
        ]
    except Exception as exc:
        logger.debug("yfinance 조회 실패(%s): %s", symbol, exc)
        return []


def _fetch_fx_history(currency: str, since: str, until: str) -> list[dict]:
    direct = _fetch_yf_history(_FX_TICKERS[currency], since, until, "fx") if currency in _FX_TICKERS else []
    src_ok = _value_on_or_before(direct, since, "fx")[0] is not None
    cur_ok = _value_on_or_before(direct, until, "fx")[0] is not None
    if src_ok and cur_ok:
        return direct
    cross_ticker = _FX_USD_CROSS_TICKERS.get(currency)
    if not cross_ticker:
        return direct
    usd_krw = _fetch_yf_history(_FX_TICKERS["USD"], since, until, "usd_krw")
    usd_cur = _fetch_yf_history(cross_ticker, since, until, "usd_cur")
    by_krw = {r["date"]: r["usd_krw"] for r in usd_krw}
    by_cur = {r["date"]: r["usd_cur"] for r in usd_cur}
    rows = [
        {"date": d, "fx": by_krw[d] / by_cur[d]}
        for d in sorted(set(by_krw) & set(by_cur))
        if by_cur[d]
    ]
    return rows or direct


def _value_on_or_before(rows: list[dict], target: str, key: str) -> tuple[float | None, str | None]:
    valid = sorted([r for r in rows if r.get(key) and r.get("date") <= target], key=lambda r: r["date"])
    if not valid:
        return None, None
    return valid[-1][key], valid[-1]["date"]


def fetch_foreign_market_data(rows: list[dict], src_date: str, as_of: str) -> dict[str, dict]:
    """매핑 가능한 해외주식의 공시일/현재 종가와 환율을 조회한다.

    반환값은 원본 종목명 기준 dict이며, 네트워크 실패·미매핑 항목은 자연스럽게 빠진다.
    """
    mapped = [(r, _foreign_meta(r.get("name", ""))) for r in rows]
    mapped = [(r, m) for r, m in mapped if m.get("ticker")]
    if not mapped:
        return {}
    since = (date.fromisoformat(src_date) - timedelta(days=config.PRICE_SINCE_LOOKBACK_DAYS)).isoformat()
    price_series = {
        m["ticker"]: _fetch_yf_history(m["ticker"], since, as_of, "close")
        for _, m in mapped
    }
    currencies = sorted({m.get("currency", "USD") for _, m in mapped})
    fx_series: dict[str, list[dict]] = {}
    for cur in currencies:
        if cur == "KRW":
            fx_series[cur] = []
            continue
        fx_series[cur] = _fetch_fx_history(cur, since, as_of)

    out: dict[str, dict] = {}
    for row, meta in mapped:
        ticker = meta["ticker"]
        currency = meta.get("currency", "USD")
        src_price, src_price_date = _value_on_or_before(price_series.get(ticker, []), src_date, "close")
        cur_price, cur_price_date = _value_on_or_before(price_series.get(ticker, []), as_of, "close")
        if currency == "KRW":
            src_fx, src_fx_date = 1.0, src_price_date
            cur_fx, cur_fx_date = 1.0, cur_price_date
        else:
            src_fx, src_fx_date = _value_on_or_before(fx_series.get(currency, []), src_date, "fx")
            cur_fx, cur_fx_date = _value_on_or_before(fx_series.get(currency, []), as_of, "fx")
        out[row["name"]] = {
            "ticker": ticker,
            "country": meta.get("country"),
            "currency": currency,
            "priceScale": meta.get("price_scale", 1.0),
            "sourcePrice": src_price,
            "sourcePriceDate": src_price_date,
            "sourceFx": src_fx,
            "sourceFxDate": src_fx_date,
            "currentPrice": cur_price,
            "currentPriceDate": cur_price_date,
            "currentFx": cur_fx,
            "currentFxDate": cur_fx_date,
        }
    return out


def _shape_foreign_row(row: dict) -> dict:
    meta = _foreign_meta(row.get("name", ""))
    return {
        "name": row["name"],
        "country": row.get("country") or meta.get("country"),
        "ticker": meta.get("ticker"),
        "value": row.get("value"),
        "weightPct": row.get("weight_pct"),
        "ownershipPct": row.get("ownership_pct"),
    }


def enrich_foreign_holdings(rows: list[dict], src_date: str, as_of: str,
                            foreign_stock_total: int | float | None = None) -> list[dict]:
    """공시 평가액에서 추정수량을 역산하고 현재 종가·환율로 현재 평가액을 추정한다."""
    shaped = [_shape_foreign_row(r) for r in rows]
    market = fetch_foreign_market_data(rows, src_date, as_of)
    for item in shaped:
        m = market.get(item["name"]) or {}
        item["country"] = item.get("country") or m.get("country")
        item["ticker"] = item.get("ticker") or m.get("ticker")
        for key in ("currency", "sourcePrice", "sourcePriceDate", "sourceFx", "sourceFxDate",
                    "currentPrice", "currentPriceDate", "currentFx", "currentFxDate"):
            if m.get(key) is not None:
                item[key] = m[key]
        scale = m.get("priceScale", 1.0)
        source_krw_price = (m.get("sourcePrice") or 0) * (m.get("sourceFx") or 0) * scale
        shares = (item["value"] / source_krw_price) if item.get("value") and source_krw_price else None
        if shares:
            item["estimatedShares"] = shares
        current_krw_price = (m.get("currentPrice") or 0) * (m.get("currentFx") or 0) * scale
        if shares and current_krw_price:
            item["currentValue"] = round(shares * current_krw_price)
    denom = foreign_stock_total or sum(i.get("currentValue") or 0 for i in shaped)
    if denom:
        for item in shaped:
            if item.get("currentValue") is not None:
                item["currentWeightPct"] = item["currentValue"] / denom * 100
    return shaped


def get_foreign_holdings(as_of: str | None = None,
                         foreign_stock_total: int | float | None = None) -> dict | None:
    """해외주식 스냅샷: 네트워크(discover) 성공 시 seed 갱신, 실패 시 seed 폴백. 둘 다 없으면 None."""
    from ..io_utils import _read_json, _write_json

    rows: list[dict] = []
    src_date = None
    try:
        rows, src_date = fetch_foreign_holdings()
        if rows:
            _write_json(config.SEED_FOREIGN, {"date": src_date, "holdings": rows})
            logger.info("해외주식 공시 %s: %d종목 수집(seed 갱신)", src_date, len(rows))
    except Exception as exc:
        logger.warning("해외주식 수집 실패(seed 폴백): %s", exc)
    if not rows:
        seed = _read_json(config.SEED_FOREIGN, {}) or {}
        rows, src_date = seed.get("holdings") or [], seed.get("date")
    if not rows or not src_date:
        return None
    total = sum(r.get("value") or 0 for r in rows)
    holdings = rows[:config.FOREIGN_TOP_N]
    if as_of:
        holdings_out = enrich_foreign_holdings(holdings, src_date, as_of, foreign_stock_total)
    else:
        holdings_out = [_shape_foreign_row(r) for r in holdings]
    current_values = [h["currentValue"] for h in holdings_out if h.get("currentValue") is not None]
    return {
        "date": src_date,
        "count": len(rows),
        "total": total,  # 공시 종목(10억원↑ 한정) 평가액 합 — 부문 전체 평가액보다 작다
        "asOf": as_of,
        "currentTotal": (foreign_stock_total if foreign_stock_total else sum(current_values)) or None,
        "currentPricedCount": len(current_values),
        "holdings": holdings_out,
    }


# ---------- 기금 전체·부문별 평가액: 「기금 포트폴리오 현황」(data.go.kr) ----------
def _parse_fund_period(col: str) -> str | None:
    """컬럼 헤더 → 기준연월. '2026년 2월(십억 원)'→'2026-02', '2025년(십억 원)'→'2025-12'.

    연도가 없는 '현황(말잔_십억원)' 같은 중복 컬럼은 None을 반환해 자연히 제외된다.
    """
    m = re.search(r"(\d{4})년\s*(\d{1,2})\s*월", col)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{4})\s*년", col)
    if m:
        return f"{m.group(1)}-12"  # 연도만 표기된 컬럼 = 해당 연말
    return None


def fetch_fund_portfolio() -> dict | None:
    """「기금 포트폴리오 현황」 CSV → 부문별 평가액(원 단위) 시계열.

    행=부문, 열=기준시점(연말+최신월)인 wide 포맷을 long 시계열로 변환한다.
    국내주식은 본 대시보드가 일별로 직접 평가하지만, 해외주식·채권·대체투자 등은
    공개 일별 데이터가 없어 이 공식 스냅샷(연말+최신월)으로만 비중 추이를 그린다.
    """
    page = config.FUND_PORTFOLIO_PAGE_URL
    csv_url = config.FUND_PORTFOLIO_FALLBACK_CSV_URL
    discover = os.getenv("NPS_PUBLIC_DATA_DISCOVER", "1").strip().lower() not in {"0", "false", "no", "off"}
    if discover:
        try:
            html = _download(page).decode("utf-8", "replace")
            m = config._PUBLIC_CSV_URL_RE.search(html)
            if m:
                csv_url = m.group(1).replace("&amp;", "&")
        except Exception as exc:
            logger.warning("기금 포트폴리오 discover 실패, fallback URL 사용: %s", exc)
    payload = _download(csv_url, referer=page)
    rows = list(csv.reader(io.StringIO(_decode_csv(payload))))
    if len(rows) < 3:
        return None
    header = rows[0]
    periods = {i: p for i, col in enumerate(header) if i and (p := _parse_fund_period(col))}
    if not periods:
        return None
    series_map: dict[str, dict] = {p: {"period": p} for p in periods.values()}
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        key = config._FUND_SECTOR_MAP.get(r[0].strip())
        if not key:
            continue
        for i, p in periods.items():
            if i < len(r):
                iv = _pi(r[i])
                if iv is not None:
                    series_map[p][key] = iv * 1_000_000_000  # 십억원 → 원
    series = [series_map[p] for p in sorted(series_map) if "total" in series_map[p]]
    if not series:
        return None
    return {"unit": "won", "asOf": series[-1]["period"], "series": series}
