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
KIS_TOKEN_CACHE = os.path.join(DATA, "kis_token.json")
# 연말 보유구성 스냅샷 보존 디렉터리(F-6) — 커밋 대상(공시 원본 이력 = 콘텐츠 자산).
ARCHIVE_DIR = os.path.join(DATA, "archive")
# KRX 업종분류 캐시(F-7) — 미커밋, Actions에서는 actions/cache로 영속(DART corpCode와 같은 패턴).
SECTOR_CACHE = os.path.join(DATA, "sector_cache.json")
SECTOR_CACHE_MAX_AGE_DAYS = 30

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
# 해외주식 투자정보(연말 공시, 10억원 미만 제외, 단위 억원·%) — 종목코드가 없어 일별 재평가 불가,
# 연 1회 정적 스냅샷 탭(F-9)으로만 노출. atchFileId 고정 fallback은 없고 discover 전용
# (클라우드에서는 data.go.kr이 막히므로 로컬 실행이 seed를 갱신·커밋하는 국내주식과 같은 패턴).
PUBLIC_FOREIGN_PAGE_URL = "https://www.data.go.kr/data/3070517/fileData.do"
SEED_FOREIGN = os.path.join(DATA, "seed_foreign_holdings.json")
FOREIGN_TOP_N = 50  # 발행물에 싣는 해외주식 상위 종목 수
KIS_BASE_URL = os.environ.get("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443").rstrip("/")
KIS_TOKEN_URL = f"{KIS_BASE_URL}/oauth2/tokenP"
KIS_INVESTOR_TRADE_URL = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"
KIS_PENSION_TRADE_LIMIT = int(os.environ.get("KIS_PENSION_TRADE_LIMIT", "100"))
KIS_REQUEST_SLEEP_SEC = float(os.environ.get("KIS_REQUEST_SLEEP_SEC", "0.05"))
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
DART_COMPANY_URL = "https://opendart.fss.or.kr/api/company.json?crtfc_key={key}&corp_code={corp_code}"
# 종목코드(6자리) → DART 고유번호(8자리) 매핑 캐시 — 미커밋, Actions에서는 actions/cache로 영속.
DART_CORP_CACHE = os.path.join(DATA, "dart_corp_codes.json")
DART_CORP_CACHE_MAX_AGE_DAYS = 30
# 대량보유 보고 대상은 5%↑뿐이므로 연말 지분율 기준 후보를 한정(경계 종목 여유분 포함 ≈290종목).
DART_CANDIDATE_MIN_OWNERSHIP_PCT = 4.5
DART_NPS_REPORTER_SUBSTR = "국민연금"  # 보고자(repror) 매칭 부분문자열

_USER_AGENT = "Mozilla/5.0"
_PUBLIC_DATASET_RE = re.compile(r"국민연금공단_국내주식 투자정보_(\d{8})")
_FOREIGN_DATASET_RE = re.compile(r"국민연금공단_해외주식 투자정보_(\d{8})")
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

# ---------- F-6 연말 스냅샷 YoY ----------
YOY_LIST_MAX = 15        # 신규 편입/전량 매도 노출 상위 종목 수
YOY_TOP_CHANGES = 10     # 수량 증감 상위 노출 종목 수
YOY_MIN_CHANGE_PCT = 0.5  # 수량 변화로 취급할 최소 |증감률|(%) — 그 미만은 라운딩 노이즈

# ---------- F-7 섹터 분석 ----------
SECTOR_UNMAPPED_LABEL = "기타(미분류)"  # 업종 매핑에 없는 종목(스팩·신규상장 등) 묶음
# DART 기업개황 폴백 시 조회할 상위(평가액) 종목 수 — 캐시 만료일(30일 주기)에만 호출되며
# 상위 400종목이 평가액의 98%+를 커버한다. 호출당 ~1초라 전 종목 조회는 과도.
SECTOR_DART_MAX = 400

# 한국표준산업분류(KSIC-10) 중분류(2자리) → 표시명. DART 기업개황 induty_code의 앞 2자리로
# 업종을 묶는다(KRX/KIND 실패 시 폴백 표시용 — 정밀 분류가 아니라 집계 라벨이 목적).
KSIC_DIVISIONS = {
    "01": "농업", "02": "임업", "03": "어업",
    "05": "석탄·원유 광업", "06": "금속 광업", "07": "비금속광물 광업", "08": "광업 지원",
    "10": "식료품", "11": "음료", "12": "담배", "13": "섬유", "14": "의복",
    "15": "가죽·신발", "16": "목재", "17": "펄프·종이", "18": "인쇄",
    "19": "석유정제", "20": "화학", "21": "의약품", "22": "고무·플라스틱",
    "23": "비금속광물제품", "24": "1차금속", "25": "금속가공",
    "26": "전자부품·통신장비", "27": "의료·정밀기기", "28": "전기장비", "29": "기계·장비",
    "30": "자동차", "31": "기타 운송장비", "32": "가구", "33": "기타 제조",
    "34": "산업기계 수리", "35": "전기·가스", "36": "수도", "37": "하수처리",
    "38": "폐기물 처리", "39": "환경 복원",
    "41": "종합건설", "42": "전문공사",
    "45": "자동차 판매", "46": "도매", "47": "소매",
    "49": "육상운송", "50": "수상운송", "51": "항공운송", "52": "물류·운송서비스",
    "55": "숙박", "56": "음식점",
    "58": "출판", "59": "영상·오디오", "60": "방송", "61": "통신",
    "62": "IT서비스·SW", "63": "정보서비스",
    "64": "금융", "65": "보험·연금", "66": "금융·보험 서비스",
    "68": "부동산", "70": "연구개발", "71": "전문서비스",
    "72": "엔지니어링", "73": "기타 과학기술", "74": "사업시설 관리", "75": "사업지원",
    "76": "임대", "84": "공공행정", "85": "교육", "86": "보건", "87": "사회복지",
    "90": "창작·예술", "91": "스포츠·오락", "94": "협회·단체", "95": "수리업", "96": "개인서비스",
}

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
