# nps-tracker

국민연금공단(NPS) 국내주식 포트폴리오 추적 대시보드.

`value-invest` 허브에 내장돼 있던 국민연금 기능을 독립 정적 사이트로 분리한 것이다.
공개 보유내역을 수집해 일별 종가로 재평가하고, NAV(기준가) 추이를 KOSPI와 비교한다.

## 데이터 출처
- **보유구성**: 공공데이터포털 「국민연금공단 국내주식 투자정보」(data.go.kr) — 전 종목·연말 기준 공식.
  discover로 최신 연말판을 받아 종목코드를 매핑하고, 보유 주식수가 없으므로 연말 종가로 추정수량을
  환산한다. 받지 못하면 seed(`data/seed_holdings_latest.json`)로 폴백한다.
  (FnGuide는 지분율 5% 이상 대량보유만 제공해 5% 미만 보유주가 누락되므로 쓰지 않는다.)
- **종목코드 매핑**: `data/corp_codes.json`(DART 상장사 전체) + 내장 별칭, 정확/정규화/prefix 매칭.
- **종가**: KRX(pykrx, 원주가) · 폴백 yfinance(`.KS`/`.KQ`)
- **KOSPI**: yfinance(`^KS11`)
- **과거 NAV 시계열**(2025-12-30 ~ 2026-05-08): `value-invest` 운영 DB에서 1회 백필(`data/seed_nav_history.json`)

## 구조
| 파일 | 설명 |
| --- | --- |
| `fetch_data.py` | 데이터 수집 · NAV 계산 · 산출물 생성 |
| `index.html` | 정적 대시보드(ECharts) |
| `data.js` | 차트 데이터(`window.NPS_DATA`), 자동 생성 |
| `current.json` | 최신 보유내역 · 요약, 자동 생성 |
| `data/nav_history.json` | NAV 시계열 누적(seed에서 시작) |
| `data/seed_*.json` · `data/stock_meta.json` | 백필 seed · 종목코드↔종목명 매핑 |
| `.github/workflows/` | 일 1회 자동 갱신 · 배포 |

## NAV 모델
첫 스냅샷의 평가총액을 NAV 1000으로 고정한다(총좌수 = 첫 평가총액 / 1000). 이후 현금흐름 없이
평가총액 변동만 NAV에 반영한다. 이는 분리 전 `value-invest`의 `snapshot_nps.py`와 동일한 모델이다.

## 로컬 실행
```bash
pip install -r requirements.txt
python fetch_data.py
```
산출물(`data.js`, `current.json`, `data/nav_history.json`)이 갱신된다. `index.html`을 브라우저로 열어 확인한다.
