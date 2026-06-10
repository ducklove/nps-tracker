"""NAV 계산 — 보유구성(shares 고정)을 일별 종가로 재평가한 기준가 시계열과 수익률 지표.

※ 발행 NAV 수치를 보존해야 하므로 이 모듈의 계산 로직은 fetch_data.py에서 그대로 이동(verbatim).
   ffill은 의도적으로 무제한이다(제한하면 발행 이력이 바뀜) — 스테일 종목은 validate가 경고로 보고.
"""
from __future__ import annotations

import calendar
from datetime import date

from .config import BASE_NAV
from .sources.market import _close_on_before


def build_nav_history(holdings: list[dict], prices: dict[str, list[dict]],
                      start_date: str, snap_date: str) -> list[dict]:
    """보유구성(shares 고정)을 start_date~snap_date 각 거래일 종가로 평가한 NAV 시계열.

    첫 거래일 평가총액을 NAV 1000으로 고정(총좌수 고정). 종목별 종가는 거래일에 맞춰
    forward-fill 하여 휴장/누락을 흡수한다.
    """
    import pandas as pd

    shares = {h["stock_code"]: h["shares"] for h in holdings}
    cols = {}
    for code, qty in shares.items():
        rows = prices.get(code)
        if rows and qty:
            cols[code] = pd.Series({r["date"]: r["close"] for r in rows})
    if not cols:
        return []
    df = pd.DataFrame(cols).sort_index().ffill()
    df = df[(df.index >= start_date) & (df.index <= snap_date)]
    if df.empty:
        return []
    sh = pd.Series(shares)
    total = df.mul(sh, axis=1).sum(axis=1, min_count=1)
    hist: list[dict] = []
    units = None
    for d, tv in total.items():
        if pd.notna(tv) and tv > 0:
            if units is None:
                units = tv / BASE_NAV
            hist.append({
                "date": str(d), "total_value": round(float(tv)),
                "nav": float(tv) / units, "total_count": len(shares),
            })
    return hist


def _nav_on_or_before(hist: list[dict], d: str) -> dict | None:
    match = None
    for s in hist:
        if s["date"] <= d:
            match = s
        else:
            break
    return match


def _today_change_pct(holdings: list[dict]) -> float | None:
    total, weighted = 0.0, 0.0
    for h in holdings:
        mv, cp = h.get("market_value"), h.get("change_pct")
        if mv and cp is not None:
            weighted += cp * mv
            total += mv
    return weighted / total if total else None


def _mtd_pct(hist: list[dict], snap: str) -> float | None:
    t = date.fromisoformat(snap)
    if t.month == 1:
        prev_last = date(t.year - 1, 12, 31)
    else:
        last_day = calendar.monthrange(t.year, t.month - 1)[1]
        prev_last = date(t.year, t.month - 1, last_day)
    ref = _nav_on_or_before(hist, prev_last.isoformat())
    cur = hist[-1] if hist else None
    if not ref or not cur or not ref.get("nav"):
        return None
    return (cur["nav"] / ref["nav"] - 1) * 100


def _ytd_pct(hist: list[dict], snap: str) -> float | None:
    year_start = snap[:4] + "-01-01"
    ref = None
    for s in hist[:-1]:
        if s["date"] < year_start:
            ref = s
        elif ref is None and s["date"] >= year_start:
            ref = s
            break
    cur = hist[-1] if hist else None
    if not ref or not cur or not ref.get("nav"):
        return None
    return (cur["nav"] / ref["nav"] - 1) * 100


def _evaluate_today(holdings, prices, snap_date):
    """snap_date 기준 보유종목 평가(현재가·등락률·평가액)."""
    valid = []
    for h in holdings:
        price, prev = _close_on_before(prices.get(h["stock_code"], []), snap_date)
        if price is None:
            continue
        item = dict(h)
        item.update(
            price=price,
            change_pct=(price / prev - 1) * 100 if prev else None,
            market_value=round(price * h["shares"]),
        )
        valid.append(item)
    return valid
