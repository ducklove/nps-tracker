"""국민연금(NPS) 국내주식 포트폴리오 정적 대시보드 데이터 생성기 — 실행 진입점(thin wrapper).

실제 구현은 nps_tracker 패키지에 있다(수집 sources/ · 계산 fund/nav · 검증 validate · 발행 publish).

보유구성 소스 (우선순위):
  1) 공공데이터포털 「국민연금공단 국내주식 투자정보」(data.go.kr) — 전 종목·연말 기준 공식 데이터.
     공개 CSV에는 보유 주식수가 없으므로 연말(source_date) 종가로 추정수량을 환산한 뒤, 그 구성을
     고정하고 source_date부터 현재까지 각 거래일 종가로 평가해 NAV 시계열을 매번 재계산한다.
  2) seed(data/seed_holdings_latest.json) — 공공데이터가 받아지지 않을 때의 폴백(클라우드 등).

종목코드 매핑: corp_codes(DART 상장사 전체) + stock_meta + aliases, 정확/정규화/prefix 매칭.
종가: KIS 일자별 시세(공식 API, 병렬) → pykrx 단일종목 → yfinance(.KS/.KQ) 폴백,
증분 캐시(data/price_cache.json).
KOSPI: yfinance(^KS11). NAV: 첫 거래일 평가총액을 1000으로 고정(총좌수 고정), 현금흐름 없음.
발행: data.js(window.NPS_DATA), data.json, current.json, data/nav_history.json.

보유구성(지분) 변동은 공개 공시 주기로만 갱신된다(공공데이터=연 1회). 일별 매매는 비공개라
어떤 소스로도 추적 불가하며, 공시 사이에는 수량 고정 + 가격 변동만 반영된다.

사용법: python fetch_data.py [--limit N] [--until YYYY-MM-DD] [--no-public] [--refresh-prices]
"""
from nps_tracker.cli import main

if __name__ == "__main__":
    main()
