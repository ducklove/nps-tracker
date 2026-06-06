"""국민연금(NPS) 국내주식 포트폴리오 정적 대시보드 데이터 생성기.

value-invest의 NPS 로직(공개 보유내역 → 일별 종가 재평가 → NAV)을 독립 정적 사이트용으로 이식.

데이터 흐름:
  1) 보유내역: data/seed_holdings_latest.json — value-invest 운영 DB에서 추출한 완전 보유구성.
     공공데이터포털 「국민연금공단 국내주식 투자정보」를 기반으로 가공된 것으로, 삼성전자 등
     전 종목(평가액 전체 리스트)을 포함한다.
  2) 종가: pykrx 단일종목(원주가) → 실패 종목은 yfinance(.KS/.KQ) 폴백
  3) KOSPI: yfinance(^KS11)
  4) NAV: 첫 스냅샷 평가총액을 1000으로 고정(총좌수 고정), 현금흐름 없음
  5) 발행: data.js(window.NPS_DATA), current.json, data/nav_history.json

주의: FnGuide 기관보유 페이지(strInstCD=49530)는 **지분율 5% 이상 대량보유 종목만** 제공하고
응답도 불안정해, 삼성전자처럼 지분율이 5% 안팎인 대형주가 통째로 누락된다. 따라서 보유구성
소스로 쓰지 않는다. value-invest와 동일하게 공개데이터 기반 완전 구성(seed)을 사용한다.

산출물은 GitHub Actions가 일 1회 커밋하고 GitHub Pages로 배포한다.
"""
from __future__ import annotations

import argparse
import calendar
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta

try:  # Windows 콘솔에서도 한글 로그가 깨지지 않도록
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nps")

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
BASE_NAV = 1000.0
PRICE_LOOKBACK_DAYS = 16  # 전 거래일 종가(등락률)와 휴장일을 흡수할 여유


# ---------- 입출력 유틸 ----------
def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as exc:
        logger.warning("read %s 실패: %s", path, exc)
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _yyyymmdd(iso: str) -> str:
    return iso.replace("-", "")


# ---------- 보유내역 ----------
def load_holdings() -> tuple[list[dict], str]:
    """완전 보유구성을 로드한다(value-invest 운영 DB에서 추출한 seed).

    seed는 공개데이터 기반 전 종목 리스트라 삼성전자 등 대형주를 포함한다. 국민연금의
    보유구성은 분기/연 단위로만 바뀌므로, 일별 변동은 가격에만 반영한다. 더 최신 공개
    보유내역이 나오면 seed_holdings_latest.json만 교체하면 된다.
    """
    d = _read_json(os.path.join(DATA, "seed_holdings_latest.json"), {}) or {}
    holdings = [{
        "stock_code": h["stock_code"],
        "stock_name": h["stock_name"],
        "shares": h["shares"],
        "ownership_pct": h.get("ownership_pct", 0),
    } for h in d.get("holdings", []) if h.get("stock_code") and h.get("shares")]
    src_date = d.get("date", "?")
    logger.info("보유구성 %d종목 로드 (기준 %s)", len(holdings), src_date)
    return holdings, f"seed({src_date})"


# ---------- 종가 ----------
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
        if (i + 1) % 50 == 0:
            logger.info("pykrx 진행 %d/%d", i + 1, len(codes))
    return out


def fetch_prices_yf(codes: list[str], since: str, until: str) -> dict[str, list[dict]]:
    """yfinance 폴백. 한국 종목은 .KS(코스피)/.KQ(코스닥) 접미사를 차례로 시도."""
    try:
        import yfinance as yf
    except Exception:
        return {}
    out: dict[str, list[dict]] = {}
    end = (date.fromisoformat(until) + timedelta(days=1)).isoformat()
    for code in codes:
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
                        out[code] = rows
                        break
            except Exception:
                pass
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


def _close_on_before(rows: list[dict], target: str) -> tuple[float | None, float | None]:
    """target 이하의 최신 종가와 그 직전 종가."""
    valid = sorted([r for r in rows if r.get("close")], key=lambda r: r["date"])
    valid = [r for r in valid if r["date"] <= target]
    if not valid:
        return None, None
    latest = valid[-1]["close"]
    prev = valid[-2]["close"] if len(valid) >= 2 else None
    return latest, prev


# ---------- NAV ----------
def load_nav_history() -> list[dict]:
    h = _read_json(os.path.join(DATA, "nav_history.json"), None)
    if h is None:
        h = _read_json(os.path.join(DATA, "seed_nav_history.json"), []) or []
        logger.info("nav_history.json 없음 → seed(%d개)에서 시작", len(h))
    return sorted(h, key=lambda s: s["date"])


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


# ---------- 발행 ----------
def write_outputs(snap_date, source, holdings, total_value, nav,
                  today_pct, mtd, ytd, hist, kospi):
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
    } for h in holdings]

    summary = {
        "totalValue": total_value,
        "nav": round(nav, 2),
        "count": len(holdings),
        "todayPct": today_pct,
        "mtdPct": mtd,
        "ytdPct": ytd,
        "asOf": snap_date,
    }
    nps_data = {
        "lastUpdated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "asOf": snap_date,
        "source": source,
        "summary": summary,
        "holdings": hjson,
        "navHistory": [{"date": s["date"], "nav": round(s["nav"], 4)} for s in hist],
        "valueHistory": [{"date": s["date"], "total_value": s["total_value"]} for s in hist],
        "kospiHistory": kospi,
        "treemap": [
            {"name": h["stock_name"], "value": h["market_value"], "changePct": h.get("change_pct")}
            for h in holdings if h["market_value"] > 0
        ],
    }

    with open(os.path.join(ROOT, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.NPS_DATA = " + json.dumps(nps_data, ensure_ascii=False) + ";\n")
    _write_json(os.path.join(ROOT, "current.json"), {
        "lastUpdated": nps_data["lastUpdated"],
        "asOf": snap_date,
        "source": source,
        "summary": summary,
        "holdings": hjson,
    })
    _write_json(os.path.join(DATA, "nav_history.json"), [{
        "date": s["date"],
        "total_value": s["total_value"],
        "nav": s["nav"],
        "total_count": s.get("total_count", 0),
    } for s in hist])


def main():
    ap = argparse.ArgumentParser(description="국민연금 포트폴리오 대시보드 데이터 생성")
    ap.add_argument("--limit", type=int, default=0, help="테스트용 종목 수 제한")
    ap.add_argument("--until", default=None, help="기준일 상한 YYYY-MM-DD (기본: 오늘)")
    args = ap.parse_args()

    until = args.until or date.today().isoformat()
    since = (date.fromisoformat(until) - timedelta(days=PRICE_LOOKBACK_DAYS)).isoformat()

    holdings, source = load_holdings()
    if args.limit:
        holdings = holdings[:args.limit]
    codes = [h["stock_code"] for h in holdings]
    logger.info("보유 %d종목, 종가 조회 기간 %s ~ %s", len(codes), since, until)

    prices = fetch_prices_pykrx(codes, since, until)
    missing = [c for c in codes if c not in prices]
    if missing:
        logger.info("pykrx 미수신 %d종목 → yfinance 폴백", len(missing))
        prices.update(fetch_prices_yf(missing, since, until))

    latest_dates = [rows[-1]["date"] for rows in prices.values() if rows]
    if not latest_dates:
        logger.error("가격을 하나도 받지 못했습니다. 네트워크/소스를 확인하세요.")
        sys.exit(1)
    snap_date = max(latest_dates)
    logger.info("기준일(snap_date) = %s", snap_date)

    valid = []
    for h in holdings:
        price, prev = _close_on_before(prices.get(h["stock_code"], []), snap_date)
        if price is None:
            continue
        change_pct = (price / prev - 1) * 100 if prev else None
        market_value = round(price * h["shares"])
        item = dict(h)
        item.update(price=price, change_pct=change_pct, market_value=market_value)
        valid.append(item)

    priced_ratio = len(valid) / len(holdings) if holdings else 0
    logger.info("가격 평가 완료: %d/%d종목 (%.0f%%)", len(valid), len(holdings), priced_ratio * 100)
    if priced_ratio < 0.90:
        logger.warning("가격 평가 종목 비율이 낮습니다(%.0f%%) — 일부 종목이 누락될 수 있음", priced_ratio * 100)

    total_value = sum(h["market_value"] for h in valid)
    if total_value <= 0:
        logger.error("total_value=0 — 평가 가능한 종목이 없습니다.")
        sys.exit(1)

    hist = [s for s in load_nav_history() if s["date"] < snap_date]
    if not hist:
        nav, total_units = BASE_NAV, total_value / BASE_NAV
    else:
        total_units = hist[0]["total_value"] / BASE_NAV
        nav = total_value / total_units
    new_hist = hist + [{
        "date": snap_date, "total_value": total_value, "nav": nav, "total_count": len(valid),
    }]

    dates = [s["date"] for s in new_hist]
    kospi = fetch_kospi(min(dates), max(dates))
    kospi = [k for k in kospi if k["date"] in set(dates)]

    today_pct = _today_change_pct(valid)
    mtd = _mtd_pct(new_hist, snap_date)
    ytd = _ytd_pct(new_hist, snap_date)

    write_outputs(snap_date, source, valid, total_value, nav, today_pct, mtd, ytd, new_hist, kospi)
    logger.info("완료: %s | NAV %.2f | 평가총액 %.3f조 | %d종목 | 오늘 %s",
                snap_date, nav, total_value / 1e12, len(valid),
                f"{today_pct:+.2f}%" if today_pct is not None else "-")


if __name__ == "__main__":
    main()
