// node --test tests/js 로 실행. classic script(assets/format.js)를 CommonJS로 로드한다.
// 포맷터·색상 등 표시 계층 순수 함수 테스트.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const F = require('../../assets/format.js');

test('esc: & < > " \' 모두 이스케이프, null/undefined는 빈 문자열', () => {
  assert.equal(F.esc('<a href="x">&\'</a>'), '&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
  assert.equal(F.esc(null), '');
  assert.equal(F.esc(undefined), '');
  assert.equal(F.esc(0), '0');
  assert.equal(F.esc('삼성전자'), '삼성전자');
});

test('tt: {슬롯} 치환, 반복 슬롯, vars 생략, 미지정 슬롯은 그대로', () => {
  assert.equal(F.tt('기준일 {d} · {n}종목', { d: '2026-07-11', n: '1,234' }), '기준일 2026-07-11 · 1,234종목');
  assert.equal(F.tt('{x}{x}', { x: 'a' }), 'aa');
  assert.equal(F.tt('없음'), '없음');
  assert.equal(F.tt('{a} {b}', { a: 1 }), '1 {b}');
});

test('fmtKrwJo: 1조 이상 조 단위(자릿수 규모별), 콤마 포함', () => {
  assert.equal(F.fmtKrwJo(1e12), '1.000조');       // 1조 → 소수 3자리
  assert.equal(F.fmtKrwJo(1.5e13), '15.00조');     // 10조대 → 2자리
  assert.equal(F.fmtKrwJo(2.5e14), '250.0조');     // 100조대 → 1자리
  assert.equal(F.fmtKrwJo(1.234e15), '1,234조');   // 1000조 이상 → 0자리 + 콤마
  assert.equal(F.fmtKrwJo(-2.5e12), '-2.500조');   // 음수도 절대값 기준 자릿수
});

test('fmtKrwJo: 1억~1조 미만 억 단위, 그 미만 원 단위', () => {
  assert.equal(F.fmtKrwJo(1e8), '1.000억');
  assert.equal(F.fmtKrwJo(5e10), '500.0억');
  assert.equal(F.fmtKrwJo(-5e8), '-5.000억');
  assert.equal(F.fmtKrwJo(123456), '123,456원');
  assert.equal(F.fmtKrwJo(0), '0원');
  assert.equal(F.fmtKrwJo(99999999), '99,999,999원'); // 1억 경계 직전
});

test('fmtSignedKrw: 양수 + 접두, 음수 그대로, null은 -', () => {
  assert.equal(F.fmtSignedKrw(1e12), '+1.000조');
  assert.equal(F.fmtSignedKrw(-5e8), '-5.000억');
  assert.equal(F.fmtSignedKrw(0), '0원');
  assert.equal(F.fmtSignedKrw(null), '-');
  assert.equal(F.fmtSignedKrw(undefined), '-');
});

test('fmtKrwAxis: 축 라벨 축약(조 1자리·억 0자리), null은 0 취급', () => {
  assert.equal(F.fmtKrwAxis(2.5e13), '25.0조');
  assert.equal(F.fmtKrwAxis(-2e12), '-2.0조');
  assert.equal(F.fmtKrwAxis(5.4e9), '54억');
  assert.equal(F.fmtKrwAxis(1234), '1,234');
  assert.equal(F.fmtKrwAxis(0), '0');
  assert.equal(F.fmtKrwAxis(null), '0');
});

test('fmtPct: 부호 있는 소수 2자리 %, null은 -, 0은 부호 없음', () => {
  assert.equal(F.fmtPct(2.5), '+2.50%');
  assert.equal(F.fmtPct(-1.234), '-1.23%');
  assert.equal(F.fmtPct(0), '0.00%');
  assert.equal(F.fmtPct(null), '-');
  assert.equal(F.fmtPct(undefined), '-');
});

test('fmtPlainPct: 부호 없는 소수 2자리 %, null은 -', () => {
  assert.equal(F.fmtPlainPct(12.345), '12.35%');
  assert.equal(F.fmtPlainPct(-3), '-3.00%');
  assert.equal(F.fmtPlainPct(0), '0.00%');
  assert.equal(F.fmtPlainPct(null), '-');
});

test('fmtShares: 1000 이상 정수 반올림, 미만 소수 2자리까지, null은 -', () => {
  assert.equal(F.fmtShares(1234.56), '1,235');
  assert.equal(F.fmtShares(999.5), '999.5');
  assert.equal(F.fmtShares(-1500.7), '-1,501');
  assert.equal(F.fmtShares(0), '0');
  assert.equal(F.fmtShares(null), '-');
});

test('pctClass: 양수 up / 음수 down / 0·null neutral', () => {
  assert.equal(F.pctClass(0.01), 'nps-up');
  assert.equal(F.pctClass(-0.01), 'nps-down');
  assert.equal(F.pctClass(0), 'nps-neutral');
  assert.equal(F.pctClass(null), 'nps-neutral');
  assert.equal(F.pctClass(undefined), 'nps-neutral');
});

test('returnToColor: 0은 회색, ±range에서 적/청 포화, 범위 밖 clamp', () => {
  assert.equal(F.returnToColor(null), '#9ca3af');
  assert.equal(F.returnToColor(0), '#9ca3af');       // gray [156,163,175]
  assert.equal(F.returnToColor(20), '#dc2626');      // red 포화 (기본 range=20)
  assert.equal(F.returnToColor(-20), '#2563eb');     // blue 포화
  assert.equal(F.returnToColor(40), '#dc2626');      // clamp
  assert.equal(F.returnToColor(-999), '#2563eb');    // clamp
  assert.equal(F.returnToColor(10), '#bc656b');      // 중간 보간(gray→red 50%)
  assert.equal(F.returnToColor(5, 5), '#dc2626');    // 커스텀 range
});

test('treemapColor: ±5% clamp, 0은 회색, null은 테마별 중립색', () => {
  assert.equal(F.treemapColor(0, false), 'rgb(148,163,184)');
  assert.equal(F.treemapColor(5, false), 'rgb(220,38,38)');
  assert.equal(F.treemapColor(-5, false), 'rgb(37,99,235)');
  assert.equal(F.treemapColor(99, false), 'rgb(220,38,38)');   // clamp
  assert.equal(F.treemapColor(-99, false), 'rgb(37,99,235)');  // clamp
  assert.equal(F.treemapColor(2.5, false), 'rgb(184,101,111)'); // gray→red 중간
  assert.equal(F.treemapColor(-2.5, false), 'rgb(93,131,210)'); // blue→gray 중간
  assert.equal(F.treemapColor(null, false), '#9ca3af');
  assert.equal(F.treemapColor(null, true), '#475569');
});

test('fundPeriodLabel: 1월·연도만은 연도, 그 외 연.월(선행 0 제거)', () => {
  assert.equal(F.fundPeriodLabel('2024-01'), '2024');
  assert.equal(F.fundPeriodLabel('2024-03'), '2024.3');
  assert.equal(F.fundPeriodLabel('2024-12'), '2024.12');
  assert.equal(F.fundPeriodLabel('2024'), '2024');
});
