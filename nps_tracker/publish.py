"""산출물 발행 — data.js(window.NPS_DATA) · data.json · current.json · data/nav_history.json
+ 재사용 산출물(F-14): data/holdings_latest.csv(엑셀·시트용) · feed.xml(Atom 구독용).

계약 v2: 기존 필드는 한 글자도 바꾸지 않고(외부 소비자: value-invest 허브의 current.json·iframe)
schemaVersion / composition / warnings 를 **추가**한다. data.json은 data.js와 동일 객체의 순수 JSON.
fundPortfolio가 있으면 중기 자산배분 목표(targets)를 데이터로 함께 발행한다.
"""
from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime
from xml.sax.saxutils import escape

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


def _write_holdings_csv(hjson: list[dict], snap_date: str) -> None:
    """전체 보유내역을 CSV로 발행(data/holdings_latest.csv) — 엑셀·구글시트에서 바로 열람용.

    utf-8-sig(BOM): 한국어 엑셀이 UTF-8 CSV를 자동 인식하는 유일한 방식.
    """
    os.makedirs(os.path.dirname(config.HOLDINGS_CSV), exist_ok=True)
    with open(config.HOLDINGS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["종목코드", "종목명", "추정수량", "현재가", "평가금액",
                    "비중(%)", "등락률(%)", "지분율(%)", "업종", "기준일"])
        for h in hjson:
            w.writerow([
                h["stock_code"], h["stock_name"], h["shares"], h["price"], h["market_value"],
                round(h["weight"], 4) if h.get("weight") is not None else "",
                h["change_pct"] if h.get("change_pct") is not None else "",
                h.get("ownership_pct") or "",
                h.get("sector") or "",
                snap_date,
            ])


def _write_feed(hist: list[dict], snap_date: str) -> None:
    """일별 NAV 업데이트 Atom 피드(feed.xml) — RSS 리더/자동화 구독용.

    상태 파일 없이 nav_history 꼬리(FEED_MAX_ENTRIES 거래일)에서 매번 재생성한다.
    updated는 해당 거래일 16:00 KST(장마감 후 확정 시각)로 고정해 재실행에도 안정적이다.
    """
    site = config.SITE_URL.rstrip("/")
    tail = [s for s in hist if s.get("date") and s.get("nav") is not None]
    tail = tail[-config.FEED_MAX_ENTRIES:]
    if not tail:
        return
    entries = []
    prev_nav = None
    for s in tail:
        nav = s["nav"]
        pct = ((nav / prev_nav - 1) * 100) if prev_nav else None
        prev_nav = nav
        d = s["date"]
        pct_str = f" ({'+' if pct > 0 else ''}{pct:.2f}%)" if pct is not None else ""
        title = f"NAV {nav:.2f}{pct_str} — {d}"
        tv = s.get("total_value")
        summary = f"국민연금 국내주식 평가총액 {tv / 1e12:.3f}조 원" if tv else ""
        entries.append(
            f"  <entry>\n"
            f"    <id>{site}/#nav-{d}</id>\n"
            f"    <title>{escape(title)}</title>\n"
            f"    <updated>{d}T16:00:00+09:00</updated>\n"
            f"    <link href=\"{site}/\"/>\n"
            f"    <summary>{escape(summary)}</summary>\n"
            f"  </entry>"
        )
    feed = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"  <id>{site}/</id>\n"
        "  <title>국민연금 국내주식 포트폴리오 NAV</title>\n"
        f"  <updated>{snap_date}T16:00:00+09:00</updated>\n"
        f'  <link href="{site}/" rel="alternate"/>\n'
        f'  <link href="{site}/feed.xml" rel="self"/>\n'
        "  <author><name>nps-tracker</name></author>\n"
        + "\n".join(reversed(entries)) + "\n</feed>\n"
    )
    with open(os.path.join(config.ROOT, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(feed)


def write_outputs(snap_date, source, holdings, total_value, nav,
                  today_pct, mtd, ytd, hist, kospi, fund_portfolio=None, warnings=None,
                  sectors=None, yoy=None, foreign=None, pension_trade=None):
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
        "pensionTrade": pension_trade,  # KIS 기금 일별 순매수 집계(없으면 None)
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
        "pensionTrade": pension_trade,
    })
    _write_json(config.NAV_HISTORY, [{
        "date": s["date"], "total_value": s["total_value"],
        "nav": s["nav"], "total_count": s.get("total_count", 0),
    } for s in hist])
    # 재사용 산출물(F-14) — 실패해도 본 발행물에는 영향 없음(부가 파일).
    _write_holdings_csv(hjson, snap_date)
    _write_feed(hist, snap_date)
