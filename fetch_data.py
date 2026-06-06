"""국민연금(NPS) 국내주식 포트폴리오 정적 대시보드 데이터 생성기.

value-invest의 nps_scraper.py / snapshot_nps.py 로직을 독립 정적 사이트용으로 이식했다.

데이터 흐름:
  1) 보유내역: FnGuide 기관보유(strInstCD=49530) → 실패 시 data/seed_holdings_latest.json(baseline)
  2) 종목코드 매핑: data/stock_meta.json(과거 NPS 종목) 역방향 + 내장 aliases
  3) 종가: pykrx 단일종목(원주가) → 실패 종목은 yfinance(.KS/.KQ) 폴백
  4) KOSPI: yfinance(^KS11)
  5) NAV: 첫 스냅샷 평가총액을 1000으로 고정(총좌수 고정), 현금흐름 없음
  6) 발행: data.js(window.NPS_DATA), current.json, data/nav_history.json

산출물은 GitHub Actions가 일 1회 커밋하고 GitHub Pages로 배포한다.
"""
from __future__ import annotations

import argparse
import calendar
import json
import logging
import os
import sys
import urllib.request
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
FNGUIDE_URL = "https://comp.fnguide.com/SVO/WooriRenewal/Inst_Data.asp?strInstCD=49530"
PUBLIC_NPS_PAGE_URL = "https://www.data.go.kr/data/3070507/fileData.do"
PRICE_LOOKBACK_DAYS = 16  # 전 거래일 종가(등락률)와 휴장일을 흡수할 여유

# data.go.kr 공개 데이터는 종목 단축명만 제공하고, 일부 메가캡은 법인명/영문
# 표기가 달라 매핑에서 누락될 수 있다. 고가중 종목의 별칭을 명시해 둔다.
# (value-invest/nps_scraper.py 에서 그대로 이식)
_NPS_NAME_ALIASES = {
    "삼성전자": "005930",
    "SK하이닉스": "000660",
    "LG에너지솔루션": "373220",
    "삼성바이오로직스": "207940",
    "현대차": "005380",
    "기아": "000270",
    "NAVER": "035420",
    "셀트리온": "068270",
    "현대모비스": "012330",
    "POSCO홀딩스": "005490",
    "HD현대중공업": "329180",
    "HD한국조선해양": "009540",
    "삼성물산": "028260",
    "LG화학": "051910",
    "삼성생명": "032830",
    "한화에어로스페이스": "012450",
    "삼성SDI": "006400",
    "카카오": "035720",
    "크래프톤": "259960",
    "삼성화재": "000810",
    "두산에너빌리티": "034020",
    "기업은행": "024110",
    "삼성전기": "009150",
    "삼성에스디에스": "018260",
    "삼성중공업": "010140",
    "SK텔레콤": "017670",
    "LG전자": "066570",
    "한미반도체": "042700",
    "HD현대미포": "010620",
    "SK바이오팜": "326030",
    "LS ELECTRIC": "010120",
    "현대차2우B": "005387",
    "삼성전자우": "005935",
    "휠라홀딩스": "081660",
    "HD현대인프라코어": "042670",
    "아모레G": "002790",
    "HD현대건설기계": "267270",
    "DGB금융지주": "139130",
    "삼성화재우": "000815",
    "TKG휴켐스": "069260",
    "DI동일": "001530",
    "KCC글라스": "344820",
    "현대차우": "005385",
    "LG전자우": "066575",
    "LG화학우": "051915",
    "아모레퍼시픽우": "090435",
    "LG생활건강우": "051905",
    "미래에셋증권2우B": "00680K",
    "CJ제일제당 우": "097955",
    "금호석유우": "011785",
    "유나이티드제약": "033270",
    "CJ4우(전환)": "00104K",
    "현대차3우B": "005389",
    "삼성전기우": "009155",
    "신세계 I&C": "035510",
    "KB금융": "105560",
    "신한지주": "055550",
    "하나금융지주": "086790",
    "우리금융지주": "316140",
    "메리츠금융지주": "138040",
    "KT&G": "033780",
    "HMM": "011200",
    "LG": "003550",
    "SK": "034730",
    "LS": "006260",
    "GS": "078930",
    "CJ": "001040",
    "KT": "030200",
    "S-Oil": "010950",
}


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


# ---------- 종목코드 매핑 ----------
def load_name_to_code() -> dict[str, str]:
    """종목명 → 종목코드. stock_meta(과거 NPS 종목) 역방향 + aliases(별칭 우선)."""
    meta = _read_json(os.path.join(DATA, "stock_meta.json"), {}) or {}
    name_to_code: dict[str, str] = {}
    for code, name in meta.items():
        if name:
            name_to_code.setdefault(str(name).strip(), code)
    name_to_code.update(_NPS_NAME_ALIASES)  # 별칭이 우선
    return name_to_code


# ---------- 보유내역 ----------
def fetch_fnguide_holdings() -> list[dict]:
    """FnGuide 기관보유 페이지에서 국민연금 보유내역(종목명/주식수/지분율)을 파싱."""
    req = urllib.request.Request(FNGUIDE_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, "html.parser")
    out: list[dict] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        t = [td.get_text(strip=True) for td in tds]
        try:
            int(t[0])  # rank 컬럼이 숫자인 행만
        except (ValueError, IndexError):
            continue
        shares_str = t[2].replace(",", "")
        shares = int(shares_str) if shares_str.lstrip("-").isdigit() else 0
        try:
            ownership = float(t[5])
        except (ValueError, IndexError):
            ownership = 0.0
        report_date = t[6].replace(".", "-") if len(t) > 6 and t[6] else ""
        out.append({
            "name": t[1],
            "shares": shares,
            "ownership_pct": ownership,
            "report_date": report_date,
        })
    return out


def load_baseline_holdings() -> tuple[list[dict], str]:
    d = _read_json(os.path.join(DATA, "seed_holdings_latest.json"), {}) or {}
    return d.get("holdings", []), d.get("date", "")


def get_holdings(refresh: bool) -> tuple[list[dict], str]:
    """보유내역 + 소스 라벨. FnGuide 우선, 실패 시 seed baseline."""
    if refresh:
        try:
            raw = fetch_fnguide_holdings()
            if raw:
                n2c = load_name_to_code()
                resolved, missing = [], []
                for h in raw:
                    code = n2c.get(str(h["name"]).strip())
                    if code and len(code) == 6:
                        resolved.append({
                            "stock_code": code,
                            "stock_name": h["name"],
                            "shares": h["shares"],
                            "ownership_pct": h["ownership_pct"],
                        })
                    else:
                        missing.append(h["name"])
                if missing:
                    logger.warning("FnGuide 코드 매핑 실패 %d종목: %s",
                                   len(missing), ", ".join(missing[:10]))
                if len(resolved) >= 50:
                    rd = raw[0].get("report_date", "")
                    logger.info("FnGuide 보유내역 %d종목 사용 (공시 %s)", len(resolved), rd)
                    return resolved, "fnguide"
                logger.warning("FnGuide 매핑 종목이 너무 적음(%d) → baseline 사용", len(resolved))
        except Exception as exc:
            logger.warning("FnGuide 수집 실패, baseline 사용: %s", exc)

    hold, d = load_baseline_holdings()
    logger.info("baseline 보유내역 %d종목 사용 (기준 %s)", len(hold), d)
    return ([{
        "stock_code": h["stock_code"],
        "stock_name": h["stock_name"],
        "shares": h["shares"],
        "ownership_pct": h.get("ownership_pct", 0),
    } for h in hold], "baseline")


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
    ap.add_argument("--no-refresh", action="store_true",
                    help="FnGuide 갱신 없이 seed baseline 보유구성을 사용(가격만 갱신)")
    ap.add_argument("--limit", type=int, default=0, help="테스트용 종목 수 제한")
    ap.add_argument("--until", default=None, help="기준일 상한 YYYY-MM-DD (기본: 오늘)")
    args = ap.parse_args()

    until = args.until or date.today().isoformat()
    since = (date.fromisoformat(until) - timedelta(days=PRICE_LOOKBACK_DAYS)).isoformat()

    holdings, source = get_holdings(refresh=not args.no_refresh)
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
