# 임베드 · 데이터 소비 가이드 (F-10)

외부 페이지/서비스가 이 대시보드를 iframe으로 내장하거나 JSON을 직접 소비할 때의 계약 문서.

## 1. 엔드포인트

| URL | 용도 |
| --- | --- |
| `https://ducklove.github.io/nps-tracker/data.json` | 대시보드 페이로드(요약·상위 보유·NAV/KOSPI 시계열·섹터·YoY·해외주식) |
| `https://ducklove.github.io/nps-tracker/current.json` | 전체 보유내역 + 요약 + 자산배분(목록형 소비자용) |
| `https://ducklove.github.io/nps-tracker/data.js` | `window.NPS_DATA = {...}` 래퍼(구형 임베드·`file://` 열람 호환용) — 신규 소비자는 `data.json` 사용 |
| `https://ducklove.github.io/nps-tracker/data/holdings_latest.csv` | 전체 보유내역 CSV(utf-8-sig) — 엑셀·구글시트에서 바로 열람 |
| `https://ducklove.github.io/nps-tracker/feed.xml` | Atom 피드 — 일별 NAV 업데이트 구독(RSS 리더·자동화 트리거용) |

- GitHub Pages는 `access-control-allow-origin: *`을 내려주므로 브라우저 fetch에 CORS 제약이 없다.
- CDN 캐시 우회: `data.json?t=<timestamp>` 처럼 고유 쿼리를 붙여 요청할 것(본 대시보드도 동일).
- 갱신 주기: 평일 2회 스케줄(16:22 본 실행 + 21:37 보조, KST — GitHub 스케줄 특성상 1~3시간 지연 가능)
  + 수시 수동 실행. 보조 실행은 데이터 변화가 없으면 커밋을 생략한다.

## 2. 버전·호환성 정책

- 최상위 `schemaVersion`(정수)이 계약 버전이다. 현재 **2**.
- **같은 버전 안에서는 추가만 한다**: 기존 필드의 이름·타입·의미는 바꾸지 않고, 새 필드는 항상
  "없을 수 있음"(optional)으로 추가된다.
- 호환이 깨지는 변경(필드 제거·의미 변경)은 `schemaVersion`을 올리고 README에 공지한다.
- 소비자 권장 규칙: 모르는 필드는 무시하고, optional 필드는 `null`/부재를 동일하게 처리할 것.
  `schemaVersion`이 기대보다 크면 핵심 필드(아래 v2 안정 필드)만 사용하는 것이 안전하다.

### v2 안정 필드 (data.json · current.json 공통)

```
lastUpdated, asOf, source, schemaVersion,
composition { date, source },
warnings [string],
summary { totalValue, nav, count, todayPct, mtdPct, ytdPct, asOf }
```

`data.json` 추가: `holdings`(상위 100) · `holdingsTotal` · `navHistory[{date,nav}]` ·
`kospiHistory[{date,value}]` · `treemap` · `fundPortfolio(+targets)` ·
`sectors[]` · `yoy|null` · `foreign|null` · `peerFunds|null`
`current.json` 추가: `holdings`(전체) · `allocation` · `sectors[]` · `peerFunds|null`

`peerFunds`(F-15, optional): 연기금·공제회 비교 —
`{updated, note, funds[{key,name,kind,asOf,total(원),returnPct|null,returnYear,allocation{stock,bond,altEtc}|null,basis,source}]}`.
타 기관은 수동 갱신 seed(연 2~4회), 국민연금 항목은 발행 시 본 대시보드 최신 시계열로 대체된다.

보유 항목(holding) 필드: `stock_code, stock_name, shares, ownership_pct, price,
market_value, change_pct, weight, sector|null`

## 3. iframe 임베드

```html
<iframe src="https://ducklove.github.io/nps-tracker/?embed=true&theme=dark"
        style="width:100%;height:1200px;border:0;" loading="lazy"></iframe>
```

| 파라미터 | 값 | 효과 |
| --- | --- | --- |
| `embed` | `true` | 헤더·출처 노트 숨김, 여백 축소(부모 페이지가 맥락 제공 전제) |
| `theme` | `light` \| `dark` | 테마 강제 + 토글 숨김(부모가 제어) |
| `lang` | `ko` \| `en` | UI 언어(F-11). 데이터 값(종목명·경고문 등)은 원문 유지 |

## 4. 소비 예시

```js
const res = await fetch('https://ducklove.github.io/nps-tracker/current.json?t=' + Date.now());
const cur = await res.json();
if ((cur.schemaVersion ?? 1) >= 2 && cur.warnings?.length) console.warn(cur.warnings);
const top10 = cur.holdings.slice(0, 10).map(h => `${h.stock_name} ${h.weight?.toFixed(1)}%`);
```
