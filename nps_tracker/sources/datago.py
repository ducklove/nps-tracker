"""공공데이터포털(data.go.kr) 수집 — 국내주식 투자정보(보유내역) · 기금 포트폴리오 현황."""
from __future__ import annotations

import csv
import io
import logging
import os
import re

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
