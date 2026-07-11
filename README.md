# nps-tracker

국민연금공단(NPS) 국내주식 포트폴리오 추적 대시보드.

`value-invest` 허브에 내장돼 있던 국민연금 기능을 독립 정적 사이트로 분리한 것이다.
공개 보유내역을 수집해 일별 종가로 재평가하고, NAV(기준가) 추이를 KOSPI와 비교한다.

## 데이터 출처
- **보유구성**: 공공데이터포털 「국민연금공단 국내주식 투자정보」(data.go.kr) — 전 종목·연말 기준 공식.
  discover로 최신 연말판을 받아 종목코드를 매핑하고, 보유 주식수가 없으므로 연말 종가로 추정수량을
  환산한다. 받지 못하면 seed(`data/seed_holdings_latest.json`)로 폴백한다.
  (FnGuide는 지분율 5% 이상 대량보유만 제공해 5% 미만 보유주가 누락되므로 쓰지 않는다.)
- **5%↑ 공시 수량**: DART OpenAPI 「대량보유 상황보고」(`DART_API_KEY` 필요) > FnGuide 폴백.
  공시 당일 최신 보유주식수가 연말 추정수량 위에 덮인다. 키가 없으면 해당 소스만 생략.
- **종목코드 매핑**: `data/corp_codes.json`(DART 상장사 전체) + 내장 별칭, 정확/정규화/prefix 매칭.
- **종가**: KIS 일자별 시세(공식 API, 병렬 ~14 req/s, `KIS_APP_KEY`/`KIS_APP_SECRET`) →
  폴백 KRX(pykrx 단일종목) → yfinance(`.KS`/`.KQ`), 증분 캐시(`data/price_cache.json`, 미커밋).
  KIS 응답은 종목당 최근 100행까지라 캐시 소실 등 긴 구간 재조회는 pykrx 경로를 쓴다.
- **KOSPI**: yfinance(`^KS11`)
- **업종분류**: KRX 업종분류현황(pykrx, `KRX_ID`/`KRX_PW` 데이터포털 계정 필요) → KIND
  상장법인목록(익명, 클라우드 IP 차단 가능) → DART 기업개황 KSIC 중분류(`DART_API_KEY`,
  평가액 상위 400종목) — 섹터별 비중·등락·기여도 집계, 30일 캐시(미커밋)
- **해외주식**: 「국민연금공단 해외주식 투자정보」(연 1회, 10억원↑) — 티커가 없어 일별
  재평가 없이 정적 스냅샷 탭으로만 노출. 클라우드 차단 시 `data/seed_foreign_holdings.json` 폴백
- **기금 자산군 시계열**: Google Sheet(공표 확정값 SSOT) > data.go.kr > KOSIS > seed + 최근월 추정
- **연기금·공제회 비교(F-15)**: 공무원·사학연금, 교직원·행정·군인공제회의 규모·자산배분·수익률을
  `data/seed_peer_funds.json`(수동 갱신, 출처 포함)으로 비교. 국민연금은 본 대시보드 최신값.
  타 기관은 종목 공시가 없거나 상위 5개뿐이라 종목 단위 추적은 국민연금 전용.
- API 키는 환경변수로만 받는다: `DART_API_KEY`(대량보유 공시), `KOSIS_API_KEY`(기금 월별).
  GitHub Actions에서는 저장소 secrets 또는 variables에 등록하면 된다.

## 구조
| 파일 | 설명 |
| --- | --- |
| `fetch_data.py` | 실행 진입점(thin wrapper) — `python fetch_data.py [--limit N] [--until D] [--no-public] [--refresh-prices]` |
| `update_and_push.py` | **로컬 원클릭 발행**: pull → fetch_data.py → 데이터 산출물만 커밋 → push(→ Actions 자동 배포). 추가 인자는 fetch_data.py로 전달 |
| `nps_tracker/` | 파이프라인 패키지: `config`(상수·임계값) · `sources/`(소스별 수집: datago/fnguide/dart/kosis/sheet/market/sector) · `resolver` · `nav` · `fund` · `archive`(연말 스냅샷·YoY) · `validate`(발행 전 검증 게이트) · `publish` · `cli` |
| `index.html` + `assets/` | 정적 대시보드(ECharts). `data.json` fetch → `data.js` 폴백(file:// 호환). `i18n.js` 영문 모드(`?lang=en`), PWA 매니페스트·아이콘, OG 카드(`og-image.png`, 일배치 갱신) |
| `docs/embed.md` | 임베드·JSON 소비 계약(스키마 버전 정책, iframe 파라미터) |
| `data.js` / `data.json` | 차트 데이터(동일 객체, 자동 생성). `data.js`는 구형 임베드·로컬 열람 호환용 |
| `current.json` | 전체 보유내역 · 요약 · 자산배분(자동 생성, 허브 등 외부 소비자용) |
| `data/nav_history.json` | NAV 시계열(매 실행 보유구성 기준일부터 전체 재계산) |
| `data/seed_*.json` · `data/stock_meta.json` | 폴백 seed · 종목코드↔종목명 매핑 |
| `data/archive/holdings_*.json` | 연말 보유구성 원본 보존(불변) — 2개 이상부터 YoY 비교가 발행물에 실림 |
| `tests/` | 오프라인 테스트(파서 골든·NAV 검산·검증 게이트·e2e, `tests/js/` 프론트 순수 함수 `node --test`) — 네트워크 호출 없음 |
| `data/holdings_latest.csv` · `feed.xml` | 재사용 산출물(자동 생성) — 엑셀·시트용 CSV, 일별 NAV Atom 피드 |
| `.github/workflows/` | `pages.yml` 갱신·배포(트리거는 아래 서버 crontab의 workflow_dispatch, +가격 캐시, 실패 시 이슈, NAV ±3% 시 `nav-alert` 이슈) · `ci.yml` ruff+pytest+`node --test tests/js` |
| `scripts/nps-trigger.sh` | **일 배치 트리거**(상시 가동 서버 pi-worker=192.168.68.67의 crontab, 평일 15:45 KST, 실패 시 60초 간격 3회 재시도) — GitHub schedule은 상시 2~3시간 지연·재등록 불능 문제로 미사용. 서버가 내려가면 모서비스(value-invest)도 내려가므로 별도 백업 스케줄 없음. 서버 배치: `~/bin/nps-trigger.sh` + `crontab`(gh CLI 인증 필요), 로그 `~/log/nps-trigger.log` |
| `scripts/intraday_collector.py` | **연기금 장중 매매 수집기**(pi-worker systemd `nps-intraday.service`, 평일 08:50~15:40 KST 1분 폴링) — KIS 시세성 잠정 집계(FHPTJ04030000)를 `/srv/nps-intraday/intraday.json`에 적립, Caddy가 `https://cantabile.tplinkdns.com/nps/intraday.json`(CORS *)으로 서빙. 대시보드는 장중 1분 폴링으로 누적 순매수 곡선 표시, 휴장/장외엔 자동 숨김. 서버 원본: `~/Works/nps-intraday-collector.py`, 자격증명: `~/Works/kis_proxy/.env` 재사용 |

## NAV 모델
첫 스냅샷의 평가총액을 NAV 1000으로 고정한다(총좌수 = 첫 평가총액 / 1000). 이후 현금흐름 없이
평가총액 변동만 NAV에 반영한다. 보유 수량은 연말 공시 추정치(+FnGuide 5%↑ 공시 수량)로 고정되며,
NAV 시계열은 매 실행 시 기준일부터 전체 재계산된다.

## 검증 게이트
발행 직전 `nps_tracker/validate.py`가 데이터 정합성을 검사한다.
**에러**(가격 수신율 < 95%, 새 날짜 일간 NAV ±20% 초과 등)면 발행을 중단하고 기존 산출물을 보존하며
배치가 실패한다(Actions가 `batch-failure` 이슈 생성). **경고**(일간 NAV ±7% 초과, 가격제한폭 초과 등락,
스테일 가격, 구성 기준일 400일 경과)는 산출물의 `warnings` 필드로 발행돼 대시보드 배너에 표시된다.

## 산출물 스키마 (v2)
기존 필드는 불변(외부 소비자 호환), v2에서 `schemaVersion` · `composition{date,source}` · `warnings[]` ·
`fundPortfolio.targets`(중기 자산배분 목표)가 추가됐다.

## 로컬 실행
```bash
pip install -r requirements.txt
python fetch_data.py            # 산출물(data.js, data.json, current.json, data/nav_history.json) 갱신
python -m pytest                # 오프라인 테스트 (requirements-dev.txt: pytest, ruff)
node --test tests/js            # 프론트 순수 함수 테스트 (assets/format.js, 의존성 없음)
ruff check .
```
`index.html`을 브라우저로 열어 확인한다(file://에서는 data.js 폴백 경로로 로드된다).
