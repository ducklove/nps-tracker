"""KRX 업종분류(F-7) — 종목코드 → 업종명 매핑 + 섹터별 집계.

pykrx 「업종분류현황」(KOSPI·KOSDAQ)을 받아 data/sector_cache.json에 캐시한다
(30일 경과 시 재수집, 실패 시 낡은 캐시 폴백 — DART corpCode와 같은 패턴).
업종 구성은 거의 변하지 않으므로 일배치마다 재수집하지 않는다.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from .. import config
from ..io_utils import _read_json, _write_json, _yyyymmdd

logger = logging.getLogger("nps")

_MARKETS = ("KOSPI", "KOSDAQ")
_LOOKBACK_DAYS = 7  # 조회일이 휴장 등으로 비면 직전 영업일을 찾아 거슬러 가는 한도


def _fetch_sector_map(snap_date: str) -> dict[str, str]:
    """KRX 업종분류현황 → {종목코드(6): 업종명}. 실패 시 빈 dict."""
    try:
        from pykrx import stock
    except Exception as exc:
        logger.warning("pykrx 임포트 실패(섹터 생략): %s", exc)
        return {}
    out: dict[str, str] = {}
    base = date.fromisoformat(snap_date)
    for market in _MARKETS:
        for back in range(_LOOKBACK_DAYS):
            day = _yyyymmdd((base - timedelta(days=back)).isoformat())
            try:
                df = stock.get_market_sector_classifications(day, market)
            except Exception:
                continue
            if df is None or not len(df):
                continue
            # pykrx는 종목코드를 인덱스로 두지만, 버전에 따라 컬럼일 수도 있어 둘 다 흡수
            codes = df["종목코드"] if "종목코드" in df.columns else df.index
            for code, sec in zip(codes, df["업종명"]):
                code, sec = str(code).strip(), str(sec).strip()
                if len(code) == 6 and sec:
                    out.setdefault(code, sec)
            break
    return out


def load_sector_map(snap_date: str) -> dict[str, str]:
    """업종 매핑. 신선한 캐시 → 재수집 → (실패 시) 낡은 캐시 순. 전부 실패하면 빈 dict."""
    cached = _read_json(config.SECTOR_CACHE) or {}
    cmap = cached.get("map") or {}
    if cmap:
        try:
            age = (date.today() - date.fromisoformat(cached.get("fetched", ""))).days
        except ValueError:
            age = 10**6
        if age <= config.SECTOR_CACHE_MAX_AGE_DAYS:
            return cmap
    fresh = _fetch_sector_map(snap_date)
    if fresh:
        _write_json(config.SECTOR_CACHE, {"fetched": date.today().isoformat(), "map": fresh})
        logger.info("KRX 업종분류 갱신: %d종목", len(fresh))
        return fresh
    if cmap:
        logger.warning("KRX 업종분류 재수집 실패 → 낡은 캐시 사용(%d종목)", len(cmap))
    return cmap


def aggregate_sectors(evaluated: list[dict]) -> list[dict]:
    """평가 완료 보유종목(h["sector"] 부착됨)을 섹터별 비중·등락·기여도로 집계.

    섹터 일간 등락은 전일 평가액(prev = mv/(1+chg/100)) 가중, 기여도는 포트폴리오
    전일 합계 대비(프런트 F-1 기여도와 같은 산식). sector가 하나도 없으면 빈 리스트.
    """
    if not any(h.get("sector") for h in evaluated):
        return []
    total_mv = sum(h.get("market_value") or 0 for h in evaluated)
    if not total_mv:
        return []
    total_prev = 0.0
    groups: dict[str, dict] = {}
    for h in evaluated:
        mv = h.get("market_value") or 0
        if mv <= 0:
            continue
        g = groups.setdefault(h.get("sector") or config.SECTOR_UNMAPPED_LABEL,
                              {"value": 0, "mv_chg": 0, "prev": 0.0, "count": 0})
        g["value"] += mv
        g["count"] += 1
        chg = h.get("change_pct")
        # 등락 집계는 change_pct 있는 종목만으로 분자·분모를 맞춘다(없는 종목은 비중에만 기여)
        if chg is not None and (1 + chg / 100) > 0:
            prev = mv / (1 + chg / 100)
            g["mv_chg"] += mv
            g["prev"] += prev
            total_prev += prev
    out = []
    for name, g in groups.items():
        change = (g["mv_chg"] - g["prev"]) / g["prev"] * 100 if g["prev"] > 0 else None
        # 기여도 분모는 등락 산출 가능 종목의 전일 합 — 섹터 합산 시 포트폴리오 일간 변동과 일치
        contrib = (g["mv_chg"] - g["prev"]) / total_prev * 100 if (total_prev > 0 and g["prev"] > 0) else None
        out.append({
            "name": name,
            "value": g["value"],
            "weightPct": round(g["value"] / total_mv * 100, 2),
            "changePct": round(change, 2) if change is not None else None,
            "contribPct": round(contrib, 3) if contrib is not None else None,
            "count": g["count"],
        })
    out.sort(key=lambda s: s["value"], reverse=True)
    return out
