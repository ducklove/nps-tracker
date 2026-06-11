"""산출물 발행 — data.js(window.NPS_DATA) · data.json · current.json · data/nav_history.json.

계약 v2: 기존 필드는 한 글자도 바꾸지 않고(외부 소비자: value-invest 허브의 current.json·iframe)
schemaVersion / composition / warnings 를 **추가**한다. data.json은 data.js와 동일 객체의 순수 JSON.
fundPortfolio가 있으면 중기 자산배분 목표(targets)를 데이터로 함께 발행한다.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from . import config
from .fund import _latest_allocation
from .io_utils import _write_json

# 기존 source 문자열 "seed(2024-12-31)" / "data.go.kr(2024-12-31)" → 구조화 분해용
_SOURCE_RE = re.compile(r"^(?P<source>.+?)\((?P<date>\d{4}-\d{2}-\d{2})\)$")


def _composition(source: str) -> dict:
    """source 문자열을 {"date", "source"}로 분해. 예: "seed(2024-12-31)" → seed / 2024-12-31."""
    m = _SOURCE_RE.match(str(source or "").strip())
    if m:
        return {"date": m.group("date"), "source": m.group("source")}
    return {"date": None, "source": str(source or "")}


def write_outputs(snap_date, source, holdings, total_value, nav,
                  today_pct, mtd, ytd, hist, kospi, fund_portfolio=None, warnings=None,
                  sectors=None, yoy=None, foreign=None):
    holdings = sorted(holdings, key=lambda h: h["market_value"], reverse=True)
    total_disp = sum(h["market_value"] for h in holdings) or 0
    hjson = [{
        "stock_code": h["stock_code"],
        "stock_name": h["stock_name"],
        "shares": h["shares"],
        "ownership_pct": h.get("ownership_pct", 0),
        "price": h["price"],
        "market_value": h["market_value"],
        "change_pct": h.get("change_pct"),
        "weight": (h["market_value"] / total_disp * 100) if total_disp else None,
        "sector": h.get("sector"),  # v2 추가 — KRX 업종명(미분류 시 null)
    } for h in holdings]

    # 초기 로딩은 평가액 상위 TOP_N만(테이블 DOM 렌더 병목 완화). 나머지는 current.json에서 지연 로딩.
    top = hjson[:config.TOP_N]

    summary = {
        "totalValue": total_value,
        "nav": round(nav, 2),
        "count": len(holdings),
        "todayPct": today_pct,
        "mtdPct": mtd,
        "ytdPct": ytd,
        "asOf": snap_date,
    }
    warnings = list(warnings or [])
    composition = _composition(source)
    fp_out = None
    if fund_portfolio:
        fp_out = dict(fund_portfolio)
        fp_out["targets"] = dict(config.FUND_TARGETS)  # 중기 자산배분 목표 — index.html 하드코딩을 데이터로 이관
        fp_out["targetsNote"] = config.FUND_TARGETS_NOTE
    nps_data = {
        "lastUpdated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "asOf": snap_date,
        "source": source,
        "summary": summary,
        "holdings": top,
        "holdingsTotal": len(hjson),
        "navHistory": [{"date": s["date"], "nav": round(s["nav"], 4)} for s in hist],
        "kospiHistory": kospi,
        "treemap": [
            {"name": h["stock_name"], "value": h["market_value"], "changePct": h.get("change_pct"),
             "sector": h.get("sector")}
            for h in holdings[:config.TOP_N] if h["market_value"] > 0
        ],
        "fundPortfolio": fp_out,  # 기금 전체·부문별 평가액 시계열(연말+최신월). 없으면 None.
        # ---- 계약 v2 추가 필드 (기존 필드 뒤에 추가만) ----
        "schemaVersion": config.SCHEMA_VERSION,
        "composition": composition,
        "warnings": warnings,
        "sectors": sectors or [],  # F-7 섹터별 비중·등락·기여도(업종 매핑 실패 시 빈 배열)
        "yoy": yoy,                # F-6 연말 구성 YoY 요약(아카이브 2개 미만이면 None)
        "foreign": foreign,        # F-9 해외주식 연말 스냅샷(공시 평가액 그대로, 없으면 None)
    }

    payload = json.dumps(nps_data, ensure_ascii=False)
    with open(os.path.join(config.ROOT, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.NPS_DATA = " + payload + ";\n")
    # data.json = data.js와 동일 객체의 순수 JSON(신규 소비자용; data.js는 file://·구형 임베드 호환용 유지)
    with open(os.path.join(config.ROOT, "data.json"), "w", encoding="utf-8") as f:
        f.write(payload)
    # current.json은 전체 보유내역(지연 로딩 + 허브 인사이트용)
    _write_json(os.path.join(config.ROOT, "current.json"), {
        "lastUpdated": nps_data["lastUpdated"],
        "asOf": snap_date,
        "source": source,
        "summary": summary,
        "allocation": _latest_allocation(fund_portfolio),
        "holdings": hjson,
        # ---- 계약 v2 추가 필드 ----
        "schemaVersion": config.SCHEMA_VERSION,
        "composition": composition,
        "warnings": warnings,
        "sectors": sectors or [],
    })
    _write_json(config.NAV_HISTORY, [{
        "date": s["date"], "total_value": s["total_value"],
        "nav": s["nav"], "total_count": s.get("total_count", 0),
    } for s in hist])
