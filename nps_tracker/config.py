"""모든 URL · 상수 · 매핑 · 임계값의 단일 출처.

경로 상수(ROOT/DATA/...)는 테스트에서 monkeypatch로 재지정하므로, 사용처에서는 반드시
`config.X` 속성 접근으로 읽을 것(`from .config import X`로 복사하면 패치가 안 먹는다).
"""
from __future__ import annotations

import os
import re

# ---------- 경로 ----------
# 저장소 루트 = 이 패키지의 상위 디렉터리. NPS_TRACKER_ROOT 환경변수로 재지정 가능(테스트·임시 실행용).
ROOT = os.environ.get("NPS_TRACKER_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SEED_HOLDINGS = os.path.join(DATA, "seed_holdings_latest.json")
SEED_FUND_PORTFOLIO = os.path.join(DATA, "seed_fund_portfolio.json")
NAV_HISTORY = os.path.join(DATA, "nav_history.json")
# 가격 증분 캐시 — git에 커밋하지 않음(.gitignore). GitHub Actions에서는 actions/cache로 영속.
PRICE_CACHE = os.path.join(DATA, "price_cache.json")

# ---------- NAV 모델 ----------
BASE_NAV = 1000.0
# 종가 조회 시작일 = src_date - N일. 연말 기준일이 휴장일일 수 있어(예: 12-31) 직전 거래일을 포함.
PRICE_SINCE_LOOKBACK_DAYS = 10

# ---------- 외부 소스 URL ----------
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

# DART OpenAPI 「대량보유 상황보고」 — 국민연금 5%↑ 지분 공시를 공시 당일 반영(FnGuide 보강·우선).
# 인증키는 환경변수 DART_API_KEY로만 받는다(없으면 조용히 생략 — KOSIS_API_KEY와 같은 패턴).
DART_CORPCODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={key}"
DART_MAJORSTOCK_URL = "https://opendart.fss.or.kr/api/majorstock.json?crtfc_key={key}&corp_code={corp_code}"
# 종목코드(6자리) → DART 고유번호(8자리) 매핑 캐시 — 미커밋, Actions에서는 actions/cache로 영속.
DART_CORP_CACHE = os.path.join(DATA, "dart_corp_codes.json")
DART_CORP_CACHE_MAX_AGE_DAYS = 30
# 대량보유 보고 대상은 5%↑뿐이므로 연말 지분율 기준 후보를 한정(경계 종목 여유분 포함 ≈290종목).
DART_CANDIDATE_MIN_OWNERSHIP_PCT = 4.5
DART_NPS_REPORTER_SUBSTR = "국민연금"  # 보고자(repror) 매칭 부분문자열

_USER_AGENT = "Mozilla/5.0"
_PUBLIC_DATASET_RE = re.compile(r"국민연금공단_국내주식 투자정보_(\d{8})")
_PUBLIC_CSV_URL_RE = re.compile(r'"contentUrl"\s*:\s*"([^"]+fileDownload\.do[^"]+)"')

# ---------- 자산군 매핑 ----------
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

# ---------- 파이프라인 매직넘버 ----------
MIN_RESOLVED_HOLDINGS = 100  # 공공데이터 매핑/추정수량 환산 최소 종목 수(미만이면 seed 폴백)
TOP_N = 100                  # data.js 초기 로딩 상위 종목 수(나머지는 current.json에서 지연 로딩)

# ---------- 검증 게이트 임계값 (validate.py) ----------
MIN_PRICE_COVERAGE = 0.95        # 가격 수신 종목 비율 하한 — 미만이면 발행 중단(--limit 시 검사 생략)
NAV_DAILY_ERROR_PCT = 20.0       # '새 날짜'의 일간 NAV 변동 한도(%) — 초과 시 발행 중단
NAV_DAILY_WARN_PCT = 7.0         # '새 날짜'의 일간 NAV 변동 경고(%)
STOCK_DAILY_LIMIT_PCT = 30.0     # 개별 종목 일간 등락 경고(%) — 한국 시장 가격제한폭
STOCK_LIMIT_WARN_MAX = 10        # 등락 경고에 나열할 최대 종목 수
STALE_PRICE_TRADING_DAYS = 10    # 마지막 실제 가격이 snap_date 대비 이 거래일 수 이상 과거면 스테일
STALE_WEIGHT_MIN_PCT = 0.1       # 스테일 경고 대상 최소 비중(%)
STALE_WARN_NAMES_MAX = 5         # 스테일 경고에 나열할 상위 종목 수
COMPOSITION_MAX_AGE_DAYS = 400   # 보유 구성 기준일(src_date) 경과 경고(일)

# ---------- 발행 계약 v2 ----------
SCHEMA_VERSION = 2
# 중기 자산배분 목표비중(%) — index.html에 하드코딩돼 있던 값을 데이터로 이관. 단기자금은 잔여 운용이라 목표 0.
FUND_TARGETS = {
    "domestic_stock": 20.8, "foreign_stock": 34.7, "domestic_bond": 23.1,
    "foreign_bond": 7.4, "alternative": 14.0, "short_term": 0,
}
FUND_TARGETS_NOTE = "중기 자산배분 목표"
