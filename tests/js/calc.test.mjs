// node --test tests/js 로 실행. classic script(assets/format.js)를 CommonJS로 로드한다.
// 계산·정렬·필터·테마 마이그레이션 등 로직 계층 순수 함수 테스트.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const F = require('../../assets/format.js');

/* ---------- resolveInitialTheme: 'theme' 우선, 'nps-theme' 폴백+이전 ---------- */
test('resolveInitialTheme: 쿼리 param이 저장값보다 우선', () => {
  const r = F.resolveInitialTheme({ param: 'light', saved: 'dark' });
  assert.equal(r.theme, 'light');
  assert.equal(r.migrate, null);
});

test("resolveInitialTheme: 'theme' 저장값이 구 키보다 우선, 이전 없음", () => {
  const r = F.resolveInitialTheme({ saved: 'dark', legacy: 'light' });
  assert.equal(r.theme, 'dark');
  assert.equal(r.migrate, null);
});

test("resolveInitialTheme: 'theme' 없으면 'nps-theme' 폴백 + 'theme'로 이전", () => {
  const r = F.resolveInitialTheme({ saved: null, legacy: 'dark' });
  assert.equal(r.theme, 'dark');
  assert.equal(r.migrate, 'dark');
});

test('resolveInitialTheme: param이 있어도 구 키 이전은 수행(기존 동작)', () => {
  const r = F.resolveInitialTheme({ param: 'light', saved: null, legacy: 'dark' });
  assert.equal(r.theme, 'light');
  assert.equal(r.migrate, 'dark');
});

test('resolveInitialTheme: 저장값 전무 시 시스템 선호 반영', () => {
  assert.equal(F.resolveInitialTheme({ prefersDark: true }).theme, 'dark');
  assert.equal(F.resolveInitialTheme({ prefersDark: false }).theme, 'light');
  assert.equal(F.resolveInitialTheme({}).theme, 'light');
});

test('resolveInitialTheme: 빈 문자열 저장값은 없는 것으로 취급(localStorage 계약)', () => {
  const r = F.resolveInitialTheme({ saved: '', legacy: 'dark' });
  assert.equal(r.theme, 'dark');
  assert.equal(r.migrate, 'dark');
});

/* ---------- rangeCutoff: 기간 선택 절단일 ---------- */
test('rangeCutoff: 1m/3m/6m 캘린더 역산', () => {
  assert.equal(F.rangeCutoff('1m', '2026-07-11'), '2026-06-11');
  assert.equal(F.rangeCutoff('3m', '2026-07-11'), '2026-04-11');
  assert.equal(F.rangeCutoff('6m', '2026-07-11'), '2026-01-11');
});

test('rangeCutoff: 연 경계를 넘는 역산', () => {
  assert.equal(F.rangeCutoff('3m', '2026-01-15'), '2025-10-15');
  assert.equal(F.rangeCutoff('6m', '2026-02-01'), '2025-08-01');
});

test('rangeCutoff: 말일 보정(2월 28/29일, 윤년)', () => {
  assert.equal(F.rangeCutoff('1m', '2026-03-31'), '2026-02-28');
  assert.equal(F.rangeCutoff('1m', '2024-03-30'), '2024-02-29'); // 윤년
  assert.equal(F.rangeCutoff('6m', '2025-08-31'), '2025-02-28');
});

test('rangeCutoff: ytd는 그 해 1월 1일', () => {
  assert.equal(F.rangeCutoff('ytd', '2026-07-11'), '2026-01-01');
  assert.equal(F.rangeCutoff('ytd', '2026-01-02'), '2026-01-01');
});

test("rangeCutoff: 'all'·미지원 range·잘못된 asOf는 null", () => {
  assert.equal(F.rangeCutoff('all', '2026-07-11'), null);
  assert.equal(F.rangeCutoff('9m', '2026-07-11'), null);
  assert.equal(F.rangeCutoff('1m', '2026/07/11'), null);
  assert.equal(F.rangeCutoff('1m', ''), null);
  assert.equal(F.rangeCutoff('1m', undefined), null);
});

/* ---------- stdev: 표본 표준편차 ---------- */
test('stdev: 표본 표준편차(n-1), 2개 미만은 null', () => {
  assert.equal(F.stdev([]), null);
  assert.equal(F.stdev([1]), null);
  assert.equal(F.stdev([3, 3, 3]), 0);
  assert.ok(Math.abs(F.stdev([1, 2, 3, 4]) - Math.sqrt(5 / 3)) < 1e-12);
  assert.ok(Math.abs(F.stdev([-1, 1]) - Math.SQRT2) < 1e-12);
});

/* ---------- renormalizeTo1000: NAV·KOSPI 구간 재정규화 ---------- */
test('renormalizeTo1000: 첫 유효값을 1000으로, 소수 2자리 반올림', () => {
  assert.deepEqual(F.renormalizeTo1000([50, 55, 45]), [1000, 1100, 900]);
  assert.deepEqual(F.renormalizeTo1000([1000, 1001]), [1000, 1001]);
  assert.deepEqual(F.renormalizeTo1000([3, 1]), [1000, 333.33]);
});

test('renormalizeTo1000: null 보존, 시작 null은 건너뛰고 기준 탐색', () => {
  assert.deepEqual(F.renormalizeTo1000([null, 200, 210, null, 190]), [null, 1000, 1050, null, 950]);
});

test('renormalizeTo1000: 유효 시작점(>0) 없으면 빈 배열', () => {
  assert.deepEqual(F.renormalizeTo1000([]), []);
  assert.deepEqual(F.renormalizeTo1000([null, null]), []);
  assert.deepEqual(F.renormalizeTo1000([0, 0]), []);
  assert.deepEqual(F.renormalizeTo1000(undefined), []);
});

/* ---------- computeContributions: 오늘의 기여도 ---------- */
test('computeContributions: 전일 평가액 복원 후 기여도 %p 계산', () => {
  // A: mv 110, +10% → prev 100 / B: mv 95, -5% → prev 100 / Σprev=200
  const items = F.computeContributions([
    { stock_name: 'A', market_value: 110, change_pct: 10 },
    { stock_name: 'B', market_value: 95, change_pct: -5 },
  ]);
  assert.equal(items.length, 2);
  assert.ok(Math.abs(items[0].contrib - 5) < 1e-9);
  assert.ok(Math.abs(items[1].contrib - -2.5) < 1e-9);
});

test('computeContributions: change_pct null·mv 0 이하·-100% 이하는 제외', () => {
  const items = F.computeContributions([
    { stock_name: '유효', market_value: 100, change_pct: 0 },
    { stock_name: '등락없음', market_value: 100, change_pct: null },
    { stock_name: '평가0', market_value: 0, change_pct: 5 },
    { stock_name: '음수평가', market_value: -10, change_pct: 5 },
    { stock_name: '하한밖', market_value: 100, change_pct: -100 },
    null,
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].name, '유효');
  assert.equal(items[0].contrib, 0);
});

test('computeContributions: 유효 종목 없으면 null, 이름은 종목명→코드→- 폴백', () => {
  assert.equal(F.computeContributions([]), null);
  assert.equal(F.computeContributions(null), null);
  assert.equal(F.computeContributions([{ market_value: 100, change_pct: null }]), null);
  const items = F.computeContributions([
    { stock_code: '005930', market_value: 100, change_pct: 1 },
    { market_value: 100, change_pct: 1 },
  ]);
  assert.equal(items[0].name, '005930');
  assert.equal(items[1].name, '-');
});

/* ---------- holdingsComparator: 테이블 정렬 ---------- */
test('holdingsComparator: 평가금액 내림/오름차순, 누락값은 0 취급', () => {
  const hs = [{ market_value: 5 }, { market_value: null }, { market_value: 10 }];
  assert.deepEqual(hs.slice().sort(F.holdingsComparator('mv', false)).map(h => h.market_value), [10, 5, null]);
  assert.deepEqual(hs.slice().sort(F.holdingsComparator('mv', true)).map(h => h.market_value), [null, 5, 10]);
});

test('holdingsComparator: 등락률·지분율 키 매핑', () => {
  const hs = [{ change_pct: -2, ownership_pct: 3 }, { change_pct: 1, ownership_pct: 9 }];
  assert.equal(hs.slice().sort(F.holdingsComparator('change', false))[0].change_pct, 1);
  assert.equal(hs.slice().sort(F.holdingsComparator('own', false))[0].ownership_pct, 9);
});

test('holdingsComparator: 종목명 한국어 정렬(ko locale), 누락 이름은 빈 문자열', () => {
  const hs = [{ stock_name: '현대차' }, { stock_name: '삼성전자' }, {}];
  const asc = hs.slice().sort(F.holdingsComparator('name', true)).map(h => h.stock_name || '');
  assert.deepEqual(asc, ['', '삼성전자', '현대차']);
  const desc = hs.slice().sort(F.holdingsComparator('name', false)).map(h => h.stock_name || '');
  assert.deepEqual(desc, ['현대차', '삼성전자', '']);
});

/* ---------- filterHoldings: 종목명·코드 검색 ---------- */
const HOLDINGS = [
  { stock_name: '삼성전자', stock_code: '005930' },
  { stock_name: '삼성SDI', stock_code: '006400' },
  { stock_name: 'NAVER', stock_code: '035420' },
];

test('filterHoldings: 부분일치(이름·코드), 대소문자 무시', () => {
  assert.equal(F.filterHoldings(HOLDINGS, '삼성').length, 2);
  assert.equal(F.filterHoldings(HOLDINGS, 'naver').length, 1);
  assert.equal(F.filterHoldings(HOLDINGS, '0059')[0].stock_name, '삼성전자');
  assert.equal(F.filterHoldings(HOLDINGS, 'sdi')[0].stock_name, '삼성SDI');
});

test('filterHoldings: 공백 trim, 빈 검색어는 전체 사본(원본 비파괴)', () => {
  assert.equal(F.filterHoldings(HOLDINGS, '  삼성  ').length, 2);
  const all = F.filterHoldings(HOLDINGS, '');
  assert.equal(all.length, 3);
  assert.notEqual(all, HOLDINGS);          // 사본
  assert.equal(F.filterHoldings(HOLDINGS, '   ').length, 3);
  assert.equal(F.filterHoldings(HOLDINGS, '없는종목').length, 0);
  assert.deepEqual(F.filterHoldings(null, '삼성'), []);
});

/* ---------- isIntradayLive: 장중 폴링 시간대 ---------- */
test('isIntradayLive: 평일 08:55~15:45 경계 포함', () => {
  assert.equal(F.isIntradayLive({ weekday: 'Mon', hhmm: '09:30' }), true);
  assert.equal(F.isIntradayLive({ weekday: 'Fri', hhmm: '08:55' }), true);  // 시작 경계
  assert.equal(F.isIntradayLive({ weekday: 'Fri', hhmm: '15:45' }), true);  // 끝 경계
  assert.equal(F.isIntradayLive({ weekday: 'Mon', hhmm: '08:54' }), false);
  assert.equal(F.isIntradayLive({ weekday: 'Mon', hhmm: '15:46' }), false);
});

test('isIntradayLive: 주말은 영문·한글 요일 모두 제외', () => {
  assert.equal(F.isIntradayLive({ weekday: 'Sat', hhmm: '10:00' }), false);
  assert.equal(F.isIntradayLive({ weekday: 'Sun', hhmm: '10:00' }), false);
  assert.equal(F.isIntradayLive({ weekday: '토', hhmm: '10:00' }), false);
  assert.equal(F.isIntradayLive({ weekday: '일', hhmm: '10:00' }), false);
  assert.equal(F.isIntradayLive({ weekday: '월', hhmm: '10:00' }), true);
});
