"""국민연금(NPS) 국내주식 포트폴리오 정적 대시보드 데이터 생성기.

value-invest / finance-pi의 NPS 수집 로직(공개 보유내역 → 일별 종가 재평가 → NAV)을
독립 정적 사이트용으로 이식했다.

보유구성 소스 (우선순위):
  1) 공공데이터포털 「국민연금공단 국내주식 투자정보」(data.go.kr) — **전 종목·연말 기준 공식 데이터**.
     discover로 최신 연말판을 찾는다(실패 시 fallback CSV). 공개 CSV에는 보유 주식수가 없으므로
     연말(source_date) 종가로 추정수량을 환산한 뒤, 그 구성을 고정하고 source_date부터 현재까지
     각 거래일 종가로 평가해 NAV 시계열을 매번 재계산한다.
  2) seed(data/seed_holdings_latest.json) — value-invest 운영 DB에서 추출한 구성(폴백).
     ※ seed는 FnGuide(지분율 5% 대량보유)만 담겨 5% 미만 보유주가 누락된 불완전 구성이므로
        공공데이터가 받아지지 않을 때만 사용한다.

종목코드 매핑: corp_codes(DART 상장사 전체) + stock_meta + aliases, 정확/정규화/prefix 매칭.
종가: pykrx 단일종목(원주가) → 실패 시 yfinance(.KS/.KQ). KOSPI: yfinance(^KS11).
NAV: 첫 거래일 평가총액을 1000으로 고정(총좌수 고정), 현금흐름 없음.
발행: data.js(window.NPS_DATA), current.json, data/nav_history.json.

보유구성(지분) 변동은 공개 공시 주기로만 갱신된다(공공데이터=연 1회). 일별 매매는 비공개라
어떤 소스로도 추적 불가하며, 공시 사이에는 수량 고정 + 가격 변동만 반영된다.
"""
from __future__ import annotations

import argparse
import calendar
import csv
from collections import defaultdict
import io
import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta

try:  # Windows 콘솔에서도 한글 로그가 깨지지 않도록
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nps")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # 상폐 종목 폴백 노이즈 억제

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
SEED_HOLDINGS = os.path.join(DATA, "seed_holdings_latest.json")
SEED_FUND_PORTFOLIO = os.path.join(DATA, "seed_fund_portfolio.json")
BASE_NAV = 1000.0
PRICE_LOOKBACK_DAYS = 16

PUBLIC_NPS_PAGE_URL = "https://www.data.go.kr/data/3070507/fileData.do"
PUBLIC_NPS_FALLBACK_CSV_URL = (
    "https://www.data.go.kr/cmm/cmm/fileDownload.do"
    "?atchFileId=FILE_000000003558824&fileDetailSn=1&insertDataPrcus=N"
)
PUBLIC_NPS_FALLBACK_DATE = "2024-12-31"
FNGUIDE_URL = "https://comp.fnguide.com/SVO/WooriRenewal/Inst_Data.asp?strInstCD=49530"
# 기금 전체·부문별 평가액(시가) — 「국민연금공단_기금 포트폴리오 현황」(연말+최신월 스냅샷, 십억원)
FUND_PORTFOLIO_PAGE_URL = "https://www.data.go.kr/data/15106894/fileData.do"
FUND_PORTFOLIO_FALLBACK_CSV_URL = (
    "https://www.data.go.kr/cmm/cmm/fileDownload.do"
    "?atchFileId=FILE_000000003647207&fileDetailSn=1&insertDataPrcus=N"
)
# KOSIS 「기금운용현황(시가)」 DT_32202_B095 — 2012~2024 월별 부문별(PRD_DE=연도 × C2=월).
# 인증키는 환경변수 KOSIS_API_KEY로만 받는다(코드/커밋에 키를 두지 않음).
KOSIS_FUND_URL = (
    "https://kosis.kr/openapi/Param/statisticsParameterData.do?method=getList"
    "&apiKey={key}&itmId=H001+&objL1=ALL&objL2=ALL&objL3=&objL4=&objL5=&objL6=&objL7=&objL8="
    "&format=json&jsonVD=Y&prdSe=M&newEstPrdCnt=1200&orgId=322&tblId=DT_32202_B095"
)
# Google Sheet(사용자 공표 월별 금융부문, 억원) — 공표 확정값의 단일 출처. 공개 링크 CSV export.
GOOGLE_SHEET_ID = "1FtupuMVam7otVoerKS0r6fUNDWNhzM7GQVQPZUdPZtc"
GOOGLE_SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv"
# 시트 헤더(한글) → 표준 자산군 키
SHEET_COL_MAP = {
    "국내채권": "domestic_bond", "해외채권": "foreign_bond", "국내주식": "domestic_stock",
    "해외주식": "foreign_stock", "대체투자": "alternative", "단기자금": "short_term",
}
# 금융부문 6대 자산군(전체=이들의 합으로 통일; 공공·복지·기타는 시트에 없고 비중도 미미)
FUND_SIX = ("domestic_stock", "foreign_stock", "domestic_bond", "foreign_bond", "alternative", "short_term")

# 허브 '분석 도구' 카드에 노출할 자산배분 5종(표시 순서 고정).
_ALLOCATION_DISPLAY = (
    ("domestic_stock", "국내주식"),
    ("foreign_stock", "해외주식"),
    ("domestic_bond", "국내채권"),
    ("foreign_bond", "해외채권"),
    ("alternative", "대체투자"),
)


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
_USER_AGENT = "Mozilla/5.0"
_PUBLIC_DATASET_RE = re.compile(r"국민연금공단_국내주식 투자정보_(\d{8})")
_PUBLIC_CSV_URL_RE = re.compile(r'"contentUrl"\s*:\s*"([^"]+fileDownload\.do[^"]+)"')

# 「기금 포트폴리오 현황」 CSV의 '구분' 행 → 표준 자산군 키
_FUND_SECTOR_MAP = {
    "전체 자산(시장가)": "total",
    "복지부문": "welfare",
    "금융부문(국내주식)": "domestic_stock",
    "금융부문(해외주식)": "foreign_stock",
    "금융부문(국내채권)": "domestic_bond",
    "금융부문(해외채권)": "foreign_bond",
    "금융부문(대체투자)": "alternative",
    "금융부문(단기자금)": "short_term",
    "기타부문": "etc",
}

# 공개 CSV는 종목 단축명만 제공하고 일부 메가캡은 표기가 달라 매핑에서 빠질 수 있다.
# 고가중 종목의 별칭을 명시해 둔다. (value-invest/finance-pi 의 NPS_NAME_ALIASES 이식)
_NPS_NAME_ALIASES = {
    "삼성전자": "005930", "SK하이닉스": "000660", "LG에너지솔루션": "373220",
    "삼성바이오로직스": "207940", "현대차": "005380", "기아": "000270",
    "NAVER": "035420", "셀트리온": "068270", "현대모비스": "012330",
    "POSCO홀딩스": "005490", "HD현대중공업": "329180", "HD한국조선해양": "009540",
    "삼성물산": "028260", "LG화학": "051910", "삼성생명": "032830",
    "한화에어로스페이스": "012450", "삼성SDI": "006400", "카카오": "035720",
    "크래프톤": "259960", "삼성화재": "000810", "두산에너빌리티": "034020",
    "기업은행": "024110", "삼성전기": "009150", "삼성에스디에스": "018260",
    "삼성중공업": "010140", "SK텔레콤": "017670", "LG전자": "066570",
    "한미반도체": "042700", "HD현대미포": "010620", "SK바이오팜": "326030",
    "LS ELECTRIC": "010120", "현대차2우B": "005387", "삼성전자우": "005935",
    "휠라홀딩스": "081660", "HD현대인프라코어": "042670", "아모레G": "002790",
    "HD현대건설기계": "267270", "DGB금융지주": "139130", "삼성화재우": "000815",
    "TKG휴켐스": "069260", "DI동일": "001530", "KCC글라스": "344820",
    "현대차우": "005385", "LG전자우": "066575", "LG화학우": "051915",
    "아모레퍼시픽우": "090435", "LG생활건강우": "051905", "미래에셋증권2우B": "00680K",
    "CJ제일제당 우": "097955", "금호석유우": "011785", "유나이티드제약": "033270",
    "CJ4우(전환)": "00104K", "현대차3우B": "005389", "삼성전기우": "009155",
    "신세계 I&C": "035510", "KB금융": "105560", "신한지주": "055550",
    "하나금융지주": "086790", "우리금융지주": "316140", "메리츠금융지주": "138040",
    "KT&G": "033780", "HMM": "011200", "LG": "003550", "SK": "034730",
    "LS": "006260", "GS": "078930", "CJ": "001040", "KT": "030200", "S-Oil": "010950",
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


def _pf(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _pi(v):
    f = _pf(v)
    return int(f) if f is not None else None


# ---------- 종목코드 매핑 ----------
def _norm_name(s) -> str:
    return re.sub(r"[\s·._()/-]+", "", str(s or "").upper())


def load_resolver():
    """종목명 → 종목코드 리졸버. corp_codes(DART 상장사 전체) + stock_meta + aliases.

    반환: (정확명 맵, 정규화명 맵, (이름, 코드) 리스트[prefix 매칭용]).
    공개데이터 단축명과 DART 정식명 차이(예: 한국전력→한국전력공사)는 정규화·prefix로 흡수한다.
    """
    exact: dict[str, str] = {}
    normed: dict[str, str] = {}
    by_name: list[tuple[str, str]] = []
    corp = _read_json(os.path.join(DATA, "corp_codes.json"), {}) or {}  # {name: code}
    for name, code in corp.items():
        exact.setdefault(name, code)
        normed.setdefault(_norm_name(name), code)
        by_name.append((name, code))
    meta = _read_json(os.path.join(DATA, "stock_meta.json"), {}) or {}  # {code: name}
    for code, name in meta.items():
        if name and len(str(code)) == 6:
            exact.setdefault(str(name).strip(), str(code))
            normed.setdefault(_norm_name(name), str(code))
    for name, code in _NPS_NAME_ALIASES.items():
        exact[name] = code  # 별칭이 우선(덮어쓰기)
    return exact, normed, by_name


def resolve_code(name: str, resolver) -> str:
    exact, normed, by_name = resolver
    n = str(name or "").strip()
    if n in exact:
        return exact[n]
    nn = _norm_name(n)
    if nn in normed:
        return normed[nn]
    cands = {code for nm, code in by_name if nm.startswith(n)}  # prefix가 유일할 때만
    if len(cands) == 1:
        return next(iter(cands))
    return ""


# ---------- 공공데이터(data.go.kr) ----------
def _download(url: str, referer: str | None = None, timeout: int = 20, retries: int = 3) -> bytes:
    headers = {"User-Agent": _USER_AGENT}
    if referer:
        headers["Referer"] = referer
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # data.go.kr은 간헐적으로 연결을 끊는다 → 재시도
            last = exc
            if attempt < retries - 1:
                time.sleep(2)
    raise last


def _decode_csv(payload: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return payload.decode(enc)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", "replace")


def _discover_public_csv() -> tuple[str, str]:
    text = _download(PUBLIC_NPS_PAGE_URL).decode("utf-8", "replace")
    m = _PUBLIC_CSV_URL_RE.search(text)
    url = m.group(1).replace("&amp;", "&") if m else PUBLIC_NPS_FALLBACK_CSV_URL
    dm = _PUBLIC_DATASET_RE.search(text)
    src_date = f"{dm.group(1)[:4]}-{dm.group(1)[4:6]}-{dm.group(1)[6:8]}" if dm else PUBLIC_NPS_FALLBACK_DATE
    return url, src_date


def fetch_public_holdings() -> tuple[list[dict], str]:
    """공공데이터 CSV에서 보유내역(종목명/연말평가액/지분율)을 파싱. shares는 없음(추정 대상)."""
    discover = os.getenv("NPS_PUBLIC_DATA_DISCOVER", "1").strip().lower() not in {"0", "false", "no", "off"}
    csv_url, source_date = PUBLIC_NPS_FALLBACK_CSV_URL, PUBLIC_NPS_FALLBACK_DATE
    if discover:
        try:
            csv_url, source_date = _discover_public_csv()
        except Exception as exc:
            logger.warning("공공데이터 discover 실패, fallback URL 사용: %s", exc)
    payload = _download(csv_url, referer=PUBLIC_NPS_PAGE_URL)
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
    if len(resolved) < 100:
        logger.warning("공공데이터 코드 매핑 부족(%d) → seed 폴백", len(resolved))
        return None
    logger.info("공공데이터 %s: %d종목 중 %d종목 매핑", src_date, len(rows), len(resolved))
    return resolved, src_date


# ---------- 공시종목(5%↑) 최신 수량: FnGuide ----------
def fetch_fnguide_holdings() -> list[dict]:
    """FnGuide 기관보유 페이지에서 (종목명, 보유주식수)를 파싱. 지분율 5%↑ 대량보유 종목만 게재된다."""
    payload = _download(FNGUIDE_URL)
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(payload, "html.parser")
    out = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        t = [td.get_text(strip=True) for td in tds]
        try:
            int(t[0])  # rank 컬럼이 숫자인 행만
        except (ValueError, IndexError):
            continue
        s = t[2].replace(",", "")
        shares = int(s) if s.lstrip("-").isdigit() else 0
        if shares > 0:
            out.append({"name": t[1], "shares": shares})
    return out


def fetch_fnguide_shares(resolver) -> dict[str, int]:
    """공시종목(5%↑) 최신 분기 보유주식수 {종목코드: shares}. 실패 시 빈 dict(공공 수량 유지)."""
    try:
        rows = fetch_fnguide_holdings()
    except Exception as exc:
        logger.warning("FnGuide 수량 조회 실패(공공 연말 수량 유지): %s", exc)
        return {}
    out: dict[str, int] = {}
    for r in rows:
        code = resolve_code(r["name"], resolver)
        if code and len(code) == 6:
            out[code] = r["shares"]
    return out


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
    page = FUND_PORTFOLIO_PAGE_URL
    csv_url = FUND_PORTFOLIO_FALLBACK_CSV_URL
    discover = os.getenv("NPS_PUBLIC_DATA_DISCOVER", "1").strip().lower() not in {"0", "false", "no", "off"}
    if discover:
        try:
            html = _download(page).decode("utf-8", "replace")
            m = _PUBLIC_CSV_URL_RE.search(html)
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
        key = _FUND_SECTOR_MAP.get(r[0].strip())
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


def fetch_kosis_fund_monthly() -> list[dict] | None:
    """KOSIS 「기금운용현황(시가)」 월별 부문분해 시계열(2012-01~2024-12, 원 단위).

    DT_32202_B095는 PRD_DE=연도 × C2=월(02~13=1~12월) 구조다. C1(부문) 코드로 자산군을 합성:
      국내주식=주식(A010)-주식해외(A014), 국내채권=채권(A005)-채권해외(A009),
      해외주식=A014, 해외채권=A009, 대체=A015, 단기=A016, 복지·공공=A002+A003, 기타=A017+A018.
    KOSIS_API_KEY 환경변수가 없으면 None(→ data.go.kr/seed 폴백).
    """
    key = os.environ.get("KOSIS_API_KEY", "").strip()
    if not key:
        logger.info("KOSIS_API_KEY 없음 → KOSIS 월별 생략")
        return None
    raw = _download(KOSIS_FUND_URL.format(key=key), timeout=40)
    arr = json.loads(raw.decode("utf-8"))
    if not isinstance(arr, list) or not arr:
        return None
    by_period: dict[str, dict] = defaultdict(dict)
    for r in arr:
        c2 = r.get("C2")
        if not c2 or c2 == "01":  # 01=연간 합계행 제외
            continue
        try:
            month = int(c2) - 1
            year = int(r["PRD_DE"])
            val = float(r["DT"])
        except (TypeError, ValueError, KeyError):
            continue
        if 1 <= month <= 12:
            by_period[f"{year}-{month:02d}"][r.get("C1")] = val
    WON = 1_000_000  # 백만원 → 원
    series: list[dict] = []
    for period in sorted(by_period):
        d = by_period[period]
        def g(k):
            return d.get(k, 0) or 0
        total = g("A001")
        if total <= 0:
            continue
        series.append({
            "period": period,
            "total": round(total * WON),
            "domestic_stock": round((g("A010") - g("A014")) * WON),
            "foreign_stock": round(g("A014") * WON),
            "domestic_bond": round((g("A005") - g("A009")) * WON),
            "foreign_bond": round(g("A009") * WON),
            "alternative": round(g("A015") * WON),
            "short_term": round(g("A016") * WON),
            "welfare": round((g("A002") + g("A003")) * WON),
            "etc": round((g("A017") + g("A018")) * WON),
        })
    return series or None


def _parse_sheet_period(s: str) -> str | None:
    m = re.match(r"\s*(\d{4})\s*[.\-/]\s*(\d{1,2})", str(s or ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else None


def fetch_sheet_fund() -> list[dict] | None:
    """Google Sheet(공표 월별 금융부문, 억원) → 부문별 시계열(원). 공개 링크 CSV export.

    헤더: 기준월/국내채권/해외채권/국내주식/해외주식/대체투자/단기자금. 비공개면 HTML이 와서 None.
    """
    try:
        raw = _download(GOOGLE_SHEET_CSV_URL, timeout=30)
    except Exception as exc:
        logger.warning("시트 수집 실패: %s", exc)
        return None
    text = raw.decode("utf-8", "replace")
    if "<html" in text[:300].lower():
        logger.warning("시트가 비공개(HTML 응답) — 공유를 '링크가 있는 모든 사용자 보기'로 설정 필요")
        return None
    rows = list(csv.reader(io.StringIO(text)))
    hidx = next((i for i, r in enumerate(rows) if r and r[0].strip() == "기준월"), None)
    if hidx is None:
        logger.warning("시트 헤더(기준월) 미발견")
        return None
    header = [h.strip() for h in rows[hidx]]
    idx = {SHEET_COL_MAP[h]: i for i, h in enumerate(header) if h in SHEET_COL_MAP}
    if len(idx) < len(SHEET_COL_MAP):
        logger.warning("시트 컬럼 부족: %s", header)
        return None
    WON = 100_000_000  # 억원 → 원
    out: list[dict] = []
    for r in rows[hidx + 1:]:
        if not r or not r[0].strip():
            continue
        period = _parse_sheet_period(r[0])
        if not period:
            continue
        rec = {"period": period, "source": "sheet"}
        ok = True
        for key, i in idx.items():
            v = _pi(r[i]) if i < len(r) else None
            if v is None:
                ok = False
                break
            rec[key] = v * WON
        if ok:
            out.append(rec)
    return out or None


def _fetch_market_monthly() -> tuple[dict, dict]:
    """yfinance 월말 종가: (S&P500 {period:val}, USD/KRW {period:val}). 추정 입력용."""
    try:
        import yfinance as yf
    except Exception:
        return {}, {}
    res: dict[str, dict] = {}
    for tk, key in (("^GSPC", "sp"), ("KRW=X", "usd")):
        try:
            h = yf.Ticker(tk).history(period="3y", auto_adjust=False)["Close"]
            me = h.resample("ME").last()
            res[key] = {f"{i.year}-{i.month:02d}": float(v) for i, v in me.items() if v == v and v > 0}
        except Exception as exc:
            logger.warning("%s 월말 조회 실패: %s", tk, exc)
            res[key] = {}
    return res.get("sp", {}), res.get("usd", {})


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
    seed = _read_json(SEED_FUND_PORTFOLIO)
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
    _write_json(SEED_FUND_PORTFOLIO, {"unit": "won", "asOf": fp["asOf"], "monthlyFrom": fp["monthlyFrom"],
                                      "series": [s for s in series if not s.get("estimated")]})
    logger.info("기금 포트폴리오 %d기간(%s~%s, 추정 %d)", len(series), series[0]["period"], series[-1]["period"], n_est)
    return fp


# ---------- seed (폴백) ----------
def load_baseline() -> tuple[list[dict], str | None]:
    d = _read_json(SEED_HOLDINGS, {}) or {}
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
    _write_json(SEED_HOLDINGS, {"date": date_iso, "holdings": holdings})


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
        if (i + 1) % 100 == 0:
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


# ---------- 발행 ----------
def write_outputs(snap_date, source, holdings, total_value, nav,
                  today_pct, mtd, ytd, hist, kospi, fund_portfolio=None):
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

    # 초기 로딩은 평가액 상위 TOP_N만(테이블 DOM 렌더 병목 완화). 나머지는 current.json에서 지연 로딩.
    TOP_N = 100
    top = hjson[:TOP_N]

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
        "holdings": top,
        "holdingsTotal": len(hjson),
        "navHistory": [{"date": s["date"], "nav": round(s["nav"], 4)} for s in hist],
        "kospiHistory": kospi,
        "treemap": [
            {"name": h["stock_name"], "value": h["market_value"], "changePct": h.get("change_pct")}
            for h in holdings[:TOP_N] if h["market_value"] > 0
        ],
        "fundPortfolio": fund_portfolio,  # 기금 전체·부문별 평가액 시계열(연말+최신월). 없으면 None.
    }

    with open(os.path.join(ROOT, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.NPS_DATA = " + json.dumps(nps_data, ensure_ascii=False) + ";\n")
    # current.json은 전체 보유내역(지연 로딩 + 허브 인사이트용)
    _write_json(os.path.join(ROOT, "current.json"), {
        "lastUpdated": nps_data["lastUpdated"],
        "asOf": snap_date,
        "source": source,
        "summary": summary,
        "allocation": _latest_allocation(fund_portfolio),
        "holdings": hjson,
    })
    _write_json(os.path.join(DATA, "nav_history.json"), [{
        "date": s["date"], "total_value": s["total_value"],
        "nav": s["nav"], "total_count": s.get("total_count", 0),
    } for s in hist])


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


def main():
    ap = argparse.ArgumentParser(description="국민연금 포트폴리오 대시보드 데이터 생성")
    ap.add_argument("--limit", type=int, default=0, help="테스트용 종목 수 제한")
    ap.add_argument("--until", default=None, help="기준일 상한 YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--no-public", action="store_true", help="공공데이터 생략(seed만 사용)")
    args = ap.parse_args()

    until = args.until or date.today().isoformat()

    # 보유구성 확보: 공공데이터(네트워크) 우선 → 실패 시 seed(정적 파일). 어느 쪽이든 (구성, 기준일).
    holdings = None
    src_date = None
    source = None
    prices: dict[str, list[dict]] = {}
    pub = None if args.no_public else get_public_holdings()
    if pub:
        rows, src_date = pub
        codes = [r["stock_code"] for r in rows]
        # 연말 기준일이 휴장일일 수 있어(예: 12-31), 직전 거래일 종가까지 포함하도록 앞당겨 조회
        since = (date.fromisoformat(src_date) - timedelta(days=10)).isoformat()
        logger.info("공공데이터 %d종목, 종가 조회 %s ~ %s", len(codes), since, until)
        prices = fetch_prices_pykrx(codes, since, until)
        missing = [c for c in codes if c not in prices]
        if missing:
            logger.info("pykrx 미수신 %d종목 → yfinance 폴백", len(missing))
            prices.update(fetch_prices_yf(missing, since, until))
        # 공개 CSV는 주식수가 없으므로 연말 종가로 추정수량 환산
        holdings = []
        for r in rows:
            p0, _ = _close_on_before(prices.get(r["stock_code"], []), src_date)
            if p0 and r.get("source_market_value"):
                holdings.append({
                    "stock_code": r["stock_code"],
                    "stock_name": r["name"],
                    "shares": max(1, round(r["source_market_value"] / p0)),
                    "ownership_pct": r.get("ownership_pct", 0),
                })
        if len(holdings) >= 100:
            save_baseline(holdings, src_date)  # 정적 seed 갱신(클라우드 폴백용)
            source = f"data.go.kr({src_date})"
        else:
            logger.warning("추정수량 환산 종목 부족(%d) → seed 폴백", len(holdings))
            holdings = None

    if holdings is None:
        # 클라우드(GitHub Actions)에서는 data.go.kr 접근이 막히므로 커밋된 정적 seed를 사용한다.
        holdings, src_date = load_baseline()
        if not holdings or not src_date:
            logger.error("seed 보유구성/기준일이 없습니다.")
            sys.exit(1)
        source = f"seed({src_date})"
        codes = [h["stock_code"] for h in holdings]
        since = (date.fromisoformat(src_date) - timedelta(days=10)).isoformat()
        logger.info("seed %d종목, 종가 조회 %s ~ %s", len(codes), since, until)
        prices = fetch_prices_pykrx(codes, since, until)
        missing = [c for c in codes if c not in prices]
        if missing:
            logger.info("pykrx 미수신 %d종목 → yfinance 폴백", len(missing))
            prices.update(fetch_prices_yf(missing, since, until))

    if args.limit:
        holdings = holdings[:args.limit]

    # 공시종목(5%↑ 대량보유) 수량을 FnGuide 최신 분기 값으로 갱신(공공 연말 추정수량 위에 덮음).
    # 5% 미만 종목은 공시가 없어 연말 수량을 유지한다. FnGuide 실패 시 공공 수량 그대로.
    fg = fetch_fnguide_shares(load_resolver())
    if fg:
        applied = sum(1 for h in holdings
                      if h["stock_code"] in fg and fg[h["stock_code"]] != h["shares"])
        for h in holdings:
            if h["stock_code"] in fg:
                h["shares"] = fg[h["stock_code"]]
        logger.info("FnGuide 공시수량 갱신: 매칭 %d종목 중 %d종목 변경", len(fg), applied)

    nav_hist = build_nav_history(holdings, prices, src_date, until)
    if not nav_hist:
        logger.error("NAV 시계열 생성 실패 — 가격을 받지 못했을 수 있습니다.")
        sys.exit(1)
    snap_date = nav_hist[-1]["date"]
    valid = _evaluate_today(holdings, prices, snap_date)

    total_value = nav_hist[-1]["total_value"]
    nav = nav_hist[-1]["nav"]
    if total_value <= 0:
        logger.error("total_value=0")
        sys.exit(1)

    dates = [s["date"] for s in nav_hist]
    kospi = fetch_kospi(min(dates), max(dates))
    kospi = [k for k in kospi if k["date"] in set(dates)]

    today_pct = _today_change_pct(valid)
    mtd = _mtd_pct(nav_hist, snap_date)
    ytd = _ytd_pct(nav_hist, snap_date)

    # 기금 전체·부문별 평가액(시트 공표 + KOSIS + 추정). 추정월 국내주식엔 본 사이트 일별 평가액 사용.
    fund_portfolio = get_fund_portfolio(nav_hist)

    write_outputs(snap_date, source, valid, total_value, nav, today_pct, mtd, ytd,
                  nav_hist, kospi, fund_portfolio)
    fp_n = len(fund_portfolio["series"]) if fund_portfolio else 0
    logger.info("완료: %s | NAV %.2f | 국내주식 %.3f조 | %d종목 | %d일 | 기금부문 %d기간 | 출처 %s",
                snap_date, nav, total_value / 1e12, len(valid), len(nav_hist), fp_n, source)


if __name__ == "__main__":
    main()
