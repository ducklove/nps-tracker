"""기금 전체·부문별 평가액 시계열 합성 + seed(폴백) 관리.

우선순위: Google Sheet(공표) > data.go.kr > KOSIS(2012~2024) > seed. 마지막 공표월 다음부터
현재월까지는 규칙 기반 추정(연 3% 복리, 환율·S&P500 반영, 국내주식은 본 사이트 일별 평가액)을 부가한다.
"""
from __future__ import annotations

import logging
from datetime import date

from . import config
from .config import _ALLOCATION_DISPLAY, FUND_SIX
from .io_utils import _read_json, _write_json
from .sources.datago import fetch_fund_portfolio
from .sources.kosis import fetch_kosis_fund_monthly
from .sources.market import _fetch_market_monthly
from .sources.sheet import fetch_sheet_fund

logger = logging.getLogger("nps")


def _latest_allocation(fund_portfolio: dict | None) -> dict | None:
    """기금 자산군 시계열의 최신 월을 자산배분 비중(%)으로 요약.

    각 자산군 평가액 / 전체 평가액. 단기자금·기타는 제외하므로 합은 100% 미만.
    데이터가 없거나 합계를 못 구하면 None(헛값 금지).
    """
    series = (fund_portfolio or {}).get("series") or []
    if not series:
        return None
    latest = max(series, key=lambda r: r.get("period") or "")
    total = latest.get("total") or sum((latest.get(k) or 0) for k, _ in _ALLOCATION_DISPLAY)
    if not total:
        return None
    classes = []
    for key, label in _ALLOCATION_DISPLAY:
        value = latest.get(key)
        if value is None:
            continue
        classes.append({"key": key, "label": label, "pct": round(value / total * 100, 1)})
    if not classes:
        return None
    # 최신성 우선: 공표 최신월이 수개월 시차이므로 현재월 추정치를 노출하고 추정 여부만 표시.
    return {
        "asOf": latest.get("period"),
        "estimated": bool(latest.get("estimated")),
        "classes": classes,
    }


def _domestic_stock_by_month(nav_hist: list[dict] | None) -> dict[str, int]:
    """본 사이트 일별 국내주식 평가총액 → 월말값 {period: total_value}(원)."""
    out: dict[str, int] = {}
    for s in nav_hist or []:
        out[s["date"][:7]] = s.get("total_value")  # 날짜순이라 같은 달 마지막값이 남음
    return {k: v for k, v in out.items() if v}


def _month_add(period: str, n: int = 1) -> str:
    idx = int(period[:4]) * 12 + (int(period[5:7]) - 1) + n
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def estimate_recent_months(series_map: dict[str, dict], nav_hist: list[dict] | None,
                           until_period: str) -> list[dict]:
    """마지막 공표월 다음 ~ until_period(현재월)를 추정. 규칙:
      국내채권·대체투자·단기자금=연 3%↑, 해외채권=원/달러+연 3%, 해외주식=원/달러+S&P500,
      국내주식=본 사이트 일별 실제 평가액(월말). 시장지표가 없으면 추정을 생략한다.
    """
    official = sorted(p for p, s in series_map.items() if not s.get("estimated"))
    if not official:
        return []
    base_p = official[-1]
    if until_period <= base_p:
        return []
    base = series_map[base_p]
    sp, usd = _fetch_market_monthly()
    if base_p not in sp or base_p not in usd:
        logger.warning("추정 기준월(%s) 시장지표 없음 → 추정 생략", base_p)
        return []
    sp0, usd0 = sp[base_p], usd[base_p]
    ds_month = _domestic_stock_by_month(nav_hist)
    ds_base = ds_month.get(base_p)  # 본 사이트 기준월 국내주식(레벨 정합용)
    out: list[dict] = []
    p = _month_add(base_p, 1)
    while p <= until_period:
        m = _months_between(base_p, p)
        f3 = 1.03 ** (m / 12)
        usd_r = usd.get(p, usd0) / usd0
        sp_r = sp.get(p, sp0) / sp0
        ds_cur = ds_month.get(p)
        # 국내주식: 공표 기준월 레벨 × 본 사이트 일별 변화율(소스 전환 시 레벨 점프 방지)
        ds_est = round(base["domestic_stock"] * ds_cur / ds_base) if (ds_base and ds_cur) else base["domestic_stock"]
        out.append({
            "period": p, "estimated": True,
            "domestic_bond": round(base["domestic_bond"] * f3),
            "alternative": round(base["alternative"] * f3),
            "short_term": round(base["short_term"] * f3),
            "foreign_bond": round(base["foreign_bond"] * usd_r * f3),
            "foreign_stock": round(base["foreign_stock"] * sp_r * usd_r),
            "domestic_stock": ds_est,
        })
        p = _month_add(p, 1)
    return out


def get_fund_portfolio(nav_hist: list[dict] | None = None) -> dict | None:
    """기금 부문별 평가액 월별 시계열. 우선순위: 시트(공표) > data.go.kr > KOSIS(2012~2024) > seed,
    끝에 추정(마지막 공표월+1 ~ 현재월) 부가. 전체(total)는 6대 금융부문 합으로 통일.

    공표가 나오면 시트가 덮어 추정을 교체한다. seed에는 확정값만 영속(추정 제외).
    """
    series_map: dict[str, dict] = {}
    # ⓪ seed 베이스(과거 보존). 과거 추정 잔재는 제거하고 받는다.
    seed = _read_json(config.SEED_FUND_PORTFOLIO)
    if seed and seed.get("series"):
        for s in seed["series"]:
            if not s.get("estimated"):
                series_map[s["period"]] = dict(s)
    # ① KOSIS 월별(2012~2024)
    try:
        kosis = fetch_kosis_fund_monthly()
        if kosis:
            for s in kosis:
                series_map[s["period"]] = s
            logger.info("KOSIS 월별 %d개월(%s~%s)", len(kosis), kosis[0]["period"], kosis[-1]["period"])
    except Exception as exc:
        logger.warning("KOSIS 월별 수집 실패: %s", exc)
    # ② data.go.kr(연말·최신월) — 보조 공식 소스
    try:
        dago = fetch_fund_portfolio()
        if dago and dago.get("series"):
            for s in dago["series"]:
                series_map[s["period"]] = s
    except Exception as exc:
        logger.warning("기금 포트폴리오(data.go.kr) 수집 실패: %s", exc)
    # ③ Google Sheet 공표값 — 최우선(사용자 SSOT)
    try:
        sheet = fetch_sheet_fund()
        if sheet:
            for s in sheet:
                series_map[s["period"]] = s
            logger.info("시트 공표 %d개월(%s~%s)", len(sheet), sheet[0]["period"], sheet[-1]["period"])
    except Exception as exc:
        logger.warning("시트 수집 실패: %s", exc)
    if not series_map:
        logger.warning("기금 포트폴리오 데이터 없음")
        return None
    # ④ 추정(마지막 공표월 다음 ~ 현재월)
    today = date.today()
    for s in estimate_recent_months(series_map, nav_hist, f"{today.year}-{today.month:02d}"):
        series_map[s["period"]] = s
    # ⑤ total = 6대 부문 합으로 통일 + 정렬
    series = []
    for p in sorted(series_map):
        s = series_map[p]
        s["total"] = sum(int(s.get(k, 0) or 0) for k in FUND_SIX)
        series.append(s)
    n_est = sum(1 for s in series if s.get("estimated"))
    fp = {"unit": "won", "asOf": series[-1]["period"], "monthlyFrom": series[0]["period"],
          "estimatedFrom": next((s["period"] for s in series if s.get("estimated")), None), "series": series}
    # seed엔 확정값만 영속(추정 제외)
    _write_json(config.SEED_FUND_PORTFOLIO, {"unit": "won", "asOf": fp["asOf"], "monthlyFrom": fp["monthlyFrom"],
                                             "series": [s for s in series if not s.get("estimated")]})
    logger.info("기금 포트폴리오 %d기간(%s~%s, 추정 %d)", len(series), series[0]["period"], series[-1]["period"], n_est)
    return fp


# ---------- seed (폴백) ----------
def load_baseline() -> tuple[list[dict], str | None]:
    d = _read_json(config.SEED_HOLDINGS, {}) or {}
    holdings = [{
        "stock_code": h["stock_code"],
        "stock_name": h["stock_name"],
        "shares": h["shares"],
        "ownership_pct": h.get("ownership_pct", 0),
    } for h in d.get("holdings", []) if h.get("stock_code") and h.get("shares")]
    return holdings, d.get("date")


def save_baseline(holdings: list[dict], date_iso: str) -> None:
    """공공데이터로 환산한 구성을 정적 seed로 저장한다.

    클라우드(GitHub Actions)에서는 data.go.kr 접근이 차단(timeout)되므로, 로컬에서 공공데이터를
    받아 seed를 갱신·커밋해 두면 Actions는 네트워크 없이 이 완전 구성을 폴백으로 사용한다.
    """
    _write_json(config.SEED_HOLDINGS, {"date": date_iso, "holdings": holdings})
