/* 영문 모드(F-11) 사전 — UI 문구만 번역한다(종목명·검증 경고 등 데이터 값은 원문 유지).
   키는 한국어 원문(또는 {x} 슬롯 템플릿). app.js의 t()/tt()가 조회하며, 없는 키는 원문 출력. */
window.NPS_I18N = {
  en: {
    /* 헤더·공통 */
    "국민연금 국내주식 포트폴리오": "NPS Korea Domestic Equity Portfolio",
    "다크 모드": "Dark mode",
    "라이트 모드": "Light mode",
    "기준일 {d} · 갱신 {u} · {n}종목": "As of {d} · updated {u} · {n} stocks",
    "구성 기준 {d}": "Composition as of {d}",
    "연말 공시": "year-end filing",
    "공공데이터": "open data",
    " · 가격 기준 {d}": " · prices as of {d}",
    "source-note":
      "Holdings disclosed by the National Pension Service (NPS) revalued at daily closing prices — estimates. " +
      "The first snapshot is fixed at NAV 1000; only valuation changes move the NAV. " +
      '<a href="https://www.data.go.kr/data/3070507/fileData.do" target="_blank" rel="noopener noreferrer">Source</a>',
    "데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.": "Failed to load data. Please try again shortly.",
    "차트 라이브러리를 불러오지 못했습니다": "Failed to load the chart library",

    /* 요약 카드 */
    "국내주식 평가금액": "Domestic equity value",
    "일간 등락률(가중평균)": "Daily change (weighted)",
    "전월말 대비": "vs prior month-end",
    "연초 대비": "vs start of year",
    "기준일": "As of",
    "연기금 순매수": "Pension fund net buy",
    "기준일 {d} · {n}종목": "As of {d} · {n} stocks",
    "기준일 {d} · {n}{unit}": "As of {d} · {n} {unit}",
    "시장": "markets",
    "개 시장": "markets",
    "종목": "stocks",
    " · 커버리지 {c}%": " · coverage {c}%",
    "조회 실패": "Fetch failed",
    "KIS 조회 실패 · {n}종목 시도": "KIS fetch failed · {n} attempted",

    /* 기여도 */
    "오늘의 기여도": "Today's contributors",
    "상승 Top 5": "Top 5 gainers",
    "하락 Top 5": "Top 5 losers",
    "상승 기여 종목 없음": "No positive contributors",
    "하락 기여 종목 없음": "No negative contributors",
    "평가액 상위 {n}종목 기준 추정": "Estimated from top {n} holdings by value",

    /* 섹터 */
    "섹터 분석": "Sector breakdown",
    "KRX 업종분류 기준 · 평가액 가중": "By industry classification · value-weighted",
    "KRX 업종분류 기준 · {n}개 섹터 · 평가액 가중": "By industry classification · {n} sectors · value-weighted",
    "그 외 {a}개 섹터 · {b}종목 · 비중 {w}%": "{a} more sectors · {b} stocks · {w}% weight",
    "포트폴리오 일간 기여도": "Daily contribution to portfolio",

    /* 연말 구성 변화 */
    "연말 구성 변화": "Year-over-year changes",
    "신규 편입": "New positions",
    "전량 매도": "Fully exited",
    "수량 증감 상위": "Largest share changes",
    "없음": "None",
    "{f} → {t} 공시 기준 · 신규 {a} · 전량매도 {r} · 수량변경 {c}종목": "{f} → {t} filings · {a} new · {r} exited · {c} changed",
    "지분 {p}%": "{p}% stake",
    "{f}주 → {t}주": "{f} → {t} shares",
    "지분율 {p}%": "{p}% ownership",

    /* 차트 섹션 */
    "포트폴리오 구성 (평가액 상위 60)": "Portfolio map (top 60 by value)",
    "연기금 일별 매매동향": "Pension fund daily trading",
    "KOSPI+KOSDAQ 시장 기준": "KOSPI + KOSDAQ markets",
    "기준일 {d} · {n}개 시장 · {source}": "As of {d} · {n} markets · {source}",
    "매수/매도 총액 미제공 · 순매수만 표시": "Gross buy/sell unavailable · showing net buy only",
    "매수": "Buy",
    "매도": "Sell",
    "순매수": "Net buy",
    "NAV 추이 (vs KOSPI)": "NAV trend (vs KOSPI)",
    "전체": "All",
    "국민연금 기금 규모": "NPS fund size",
    "자산군별 비중 추이": "Asset class weights over time",
    "현재 vs 목표 자산군 비중": "Current vs target allocation",
    "최신 시점 기준": "Latest period",
    "금융부문 6대 자산군 합계(시가) · 2012~ 월별 · 음영=추정(공식 공표 시 자동 교체)":
      "Six financial asset classes, market value · monthly since 2012 · shaded = estimated",
    "금융부문 6대 자산군(국내·해외 주식/채권, 대체투자, 단기자금) · 2012~ 월별 · 음영=추정(2026.3~)":
      "Six asset classes (domestic/foreign equity & bonds, alternatives, cash) · monthly since 2012 · shaded = estimated",
    "구간 수익률": "Period return",
    "초과수익": "Excess return",
    "변동성(연환산)": "Volatility (ann.)",
    "평가": "Value",
    "일간": "Daily",
    "현재": "Current",
    "목표": "Target",
    "편차": "Gap",
    "기금 전체": "Total fund",
    "공표": "official",
    "추정": "estimated",
    "{p} 현재 vs 중기 자산배분 목표 · 현재 막대 끝 = 목표 대비 편차(%p)":
      "{p} current vs mid-term allocation target · bar label = gap vs target (%p)",
    "국내주식": "Domestic equity",
    "해외주식": "Foreign equity",
    "국내채권": "Domestic bonds",
    "해외채권": "Foreign bonds",
    "대체투자": "Alternatives",
    "단기자금": "Cash",
    "기타": "Other",

    /* 보유 종목 테이블 */
    "보유 종목": "Holdings",
    "종목명": "Name",
    "등락률": "Change",
    "현재가": "Price",
    "추정수량": "Est. shares",
    "평가금액": "Value",
    "비중": "Weight",
    "지분율": "Ownership",
    "종목명·코드 검색": "Search name or code",
    "보유 종목 검색": "Search holdings",
    "검색 결과가 없습니다": "No results",
    "전체 {n}종목 보기 (현재 상위 {k})": "Show all {n} holdings (top {k} shown)",
    "불러오는 중…": "Loading…",
    "불러오기 실패 — 다시 시도": "Failed — try again",

    /* 해외주식 */
    "해외주식 보유 (연 1회 공시)": "Foreign equity holdings (annual filing)",
    "국가": "Country",
    "평가금액(공시일)": "Value (filing date)",
    "비중(공시일)": "Weight (filing date)",
    "평가금액(현재)": "Value (current)",
    "비중(현재)": "Weight (current)",
    "자산군 내 비중": "Asset class weight",
    "{d} 연말 공시 기준 · 공시 {n}종목(원화 10억원 미만 제외) 중 상위 {k}종목 · 공시 평가액 합 {v} · 현재가 추정 {p}/{k}종목":
      "Year-end filing {d} · top {k} of {n} disclosed holdings (≥ ₩1bn) · disclosed total {v} · current estimates {p}/{k}"
  }
};
