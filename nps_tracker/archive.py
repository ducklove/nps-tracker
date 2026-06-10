"""연말 보유구성 스냅샷 아카이브(F-6) — 원본 보존 + YoY 비교 요약.

공시 구성(연 1회)은 seed_holdings_latest.json이 다음 연도 공시로 덮어쓰므로,
기준일별 원본을 data/archive/holdings_<date>.json 으로 별도 보존한다(커밋 대상).
아카이브가 2개 이상 모이면 최신 두 기준일의 YoY 비교(신규 편입/전량 매도/수량 증감 상위)를
계산해 발행물에 포함한다. 평가액 비교는 두 시점의 가격이 모두 필요해 범위에서 제외하고,
수량·지분율 기반으로만 비교한다(신규 편입만 현재 파이프라인 가격으로 기준일 평가액을 부가).
"""
from __future__ import annotations

import logging
import os
import re

from . import config
from .io_utils import _read_json, _write_json
from .sources.market import _close_on_before

logger = logging.getLogger("nps")

_ARCHIVE_RE = re.compile(r"^holdings_(\d{4}-\d{2}-\d{2})\.json$")


def _archive_path(src_date: str) -> str:
    return os.path.join(config.ARCHIVE_DIR, f"holdings_{src_date}.json")


def ensure_archive(holdings: list[dict], src_date: str) -> bool:
    """기준일 스냅샷이 없으면 보존한다. 이미 있으면 덮어쓰지 않음(원본 불변). 생성 시 True."""
    if not holdings or not src_date:
        return False
    path = _archive_path(src_date)
    if os.path.exists(path):
        return False
    _write_json(path, {"date": src_date, "holdings": [{
        "stock_code": h["stock_code"],
        "stock_name": h.get("stock_name", ""),
        "shares": h.get("shares", 0),
        "ownership_pct": h.get("ownership_pct", 0),
    } for h in holdings]})
    logger.info("보유구성 아카이브 생성: %s (%d종목)", path, len(holdings))
    return True


def list_archive_dates() -> list[str]:
    """보존된 스냅샷 기준일 목록(오름차순)."""
    try:
        names = os.listdir(config.ARCHIVE_DIR)
    except FileNotFoundError:
        return []
    return sorted(m.group(1) for n in names if (m := _ARCHIVE_RE.match(n)))


def compute_yoy(prices: dict[str, list[dict]] | None = None) -> dict | None:
    """최신 두 아카이브의 구성 변화 요약. 아카이브가 2개 미만이면 None.

    added(신규 편입)는 to 기준일 종가로 평가액을 부가해 그 순으로,
    removed(전량 매도)는 직전 지분율 순으로, top_changes(수량 증감)는
    to 기준일 평가액 변화분(폴백: |증감률|) 순으로 정렬한다.
    """
    dates = list_archive_dates()
    if len(dates) < 2:
        return None
    d_from, d_to = dates[-2], dates[-1]
    old = {h["stock_code"]: h for h in (_read_json(_archive_path(d_from), {}) or {}).get("holdings", [])}
    new = {h["stock_code"]: h for h in (_read_json(_archive_path(d_to), {}) or {}).get("holdings", [])}
    if not old or not new:
        return None

    def _value_at_to(code: str, shares: int) -> int | None:
        close, _ = _close_on_before((prices or {}).get(code, []), d_to)
        return round(close * shares) if close and shares else None

    added = []
    for code in new.keys() - old.keys():
        h = new[code]
        added.append({"stock_code": code, "stock_name": h.get("stock_name", ""),
                      "shares": h.get("shares", 0), "ownership_pct": h.get("ownership_pct", 0),
                      "value": _value_at_to(code, h.get("shares", 0))})
    added.sort(key=lambda x: (x["value"] or 0, x["ownership_pct"] or 0), reverse=True)

    removed = []
    for code in old.keys() - new.keys():
        h = old[code]
        removed.append({"stock_code": code, "stock_name": h.get("stock_name", ""),
                        "shares": h.get("shares", 0), "ownership_pct": h.get("ownership_pct", 0)})
    removed.sort(key=lambda x: (x["ownership_pct"] or 0, x["shares"] or 0), reverse=True)

    changes = []
    for code in new.keys() & old.keys():
        s0, s1 = old[code].get("shares") or 0, new[code].get("shares") or 0
        if s0 <= 0:
            continue
        pct = (s1 - s0) / s0 * 100
        if abs(pct) < config.YOY_MIN_CHANGE_PCT:
            continue
        delta_value = _value_at_to(code, abs(s1 - s0))
        changes.append({"stock_code": code, "stock_name": new[code].get("stock_name", ""),
                        "from_shares": s0, "to_shares": s1,
                        "change_pct": round(pct, 1), "delta_value": delta_value})
    changes.sort(key=lambda x: (x["delta_value"] or 0, abs(x["change_pct"])), reverse=True)

    return {
        "from": d_from, "to": d_to,
        "addedTotal": len(added), "removedTotal": len(removed), "changedTotal": len(changes),
        "added": added[:config.YOY_LIST_MAX],
        "removed": removed[:config.YOY_LIST_MAX],
        "topChanges": changes[:config.YOY_TOP_CHANGES],
    }
