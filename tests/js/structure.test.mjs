// node --test tests/js 로 실행. 프론트 구조 계약(텍스트 검사) 고정:
// ① index.html 자산 캐시버스팅 ?v= 일치 ② app.css 디자인 토큰 정의
// ③ ≤560px 보유 종목 카드 변환·차트 높이 블록 존재. DOM 렌더링 없이 파일 내용만 검사한다.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const read = rel => readFileSync(fileURLToPath(new URL('../../' + rel, import.meta.url)), 'utf8');
const html = read('index.html');
const css = read('assets/app.css');
const appJs = read('assets/app.js');

test('index.html: assets ?v= 캐시버스팅 버전이 모든 자산에서 동일', () => {
  const versions = [...html.matchAll(/assets\/[\w.-]+\.(?:css|js)\?v=(\d+)/g)].map(m => m[1]);
  assert.ok(versions.length >= 3, 'app.css·format.js·app.js 세 자산 모두 ?v= 파라미터 필요');
  assert.equal(new Set(versions).size, 1, '자산별 ?v= 버전 불일치: ' + versions.join(','));
});

test('app.css: 크기 토큰(--radius-sm/md/lg, --space-1~4)이 :root에 정의', () => {
  for (const token of ['--radius-sm', '--radius-md', '--radius-lg',
                       '--space-1', '--space-2', '--space-3', '--space-4']) {
    assert.match(css, new RegExp(token + ':\\d+px'), token + ' 정의 누락');
  }
});

test('app.css: ≤560px 카드 변환 — 보유 종목 5개 수치 열의 td::before 라벨 존재', () => {
  const phone = css.slice(css.indexOf('@media (max-width:560px)'));
  assert.ok(phone.length > 0, '≤560px 미디어 블록 누락');
  for (const label of ['현재가', '추정수량', '평가금액', '비중', '지분율']) {
    assert.ok(phone.includes('content:"' + label + '"'), '카드 라벨 누락: ' + label);
  }
  // 정렬 칩(thead th 유지)과 검색 결과 없음 행 처리도 계약에 포함
  assert.ok(phone.includes('#npsTable thead th.pf-sortable'), '정렬 칩 규칙 누락');
  assert.ok(phone.includes('.pf-table-empty'), '검색 결과 없음 행 규칙 누락');
});

test('app.css: ≤560px 차트 높이 보정(트리맵 420px·라인 280px) 존재', () => {
  const phone = css.slice(css.lastIndexOf('@media (max-width:560px)'));
  assert.ok(phone.includes('#npsTreemap{height:420px;}'), '트리맵 모바일 높이 규칙 누락');
  assert.ok(phone.includes('.pf-nav-chart-container{height:280px;}'), 'NAV 차트 모바일 높이 규칙 누락');
});

// M-17: index.html의 ECharts preload는 app.js 동적 로더와 같은 파일을 미리 받기 위한 것.
// URL 또는 SRI가 어긋나면 preload가 버려져 이중 다운로드가 되므로 일치를 계약으로 고정한다.
test('index.html: ECharts preload가 app.js의 CDN URL·SRI 상수와 일치', () => {
  const src = (/ECHARTS_SRC='([^']+)'/.exec(appJs) || [])[1];
  const sri = (/ECHARTS_SRI='([^']+)'/.exec(appJs) || [])[1];
  assert.ok(src && sri, 'app.js에서 ECHARTS_SRC/ECHARTS_SRI 상수를 찾지 못함');
  const preload = /<link rel="preload" as="script" href="([^"]+)" integrity="([^"]+)" crossorigin="anonymous">/.exec(html);
  assert.ok(preload, 'index.html에 ECharts preload 링크 누락');
  assert.equal(preload[1], src, 'preload href가 app.js ECHARTS_SRC와 불일치');
  assert.equal(preload[2], sri, 'preload integrity가 app.js ECHARTS_SRI와 불일치');
});

// F-18: 시계열 차트 인사이드 줌 — 모바일 세로 스크롤 보존(preventDefaultMouseMove:false)과
// 휠 무개입(zoom/move 모두 false)이 계약. 휠을 가로채면 페이지 스크롤이 방해받는다.
test('app.js: 시계열 인사이드 줌 계약(F-18) — inside·스크롤 보존 옵션', () => {
  assert.ok(appJs.includes("type:'inside'"), 'dataZoom inside 누락');
  assert.ok(appJs.includes('preventDefaultMouseMove:false'), '모바일 세로 스크롤 보존 옵션 누락');
  assert.ok(appJs.includes('zoomOnMouseWheel:false'), '휠 줌 비활성 옵션 누락');
  assert.ok(appJs.includes('moveOnMouseWheel:false'), '휠 팬 비활성 옵션 누락');
  assert.ok(appJs.includes("dispatchAction({type:'dataZoom', start:0, end:100})"), '더블클릭 줌 리셋 누락');
});

// 추정 시작월은 공표가 진행되면 매 배치 바뀐다. 부제에 연월을 하드코딩하면 데이터와 어긋난
// 채로 남으므로(2026-08 실사례), 정적 문구 금지 + estimatedFrom 기반 렌더를 계약으로 고정한다.
test('자산군별 비중 추이 부제: 연월 하드코딩 금지 · estimatedFrom으로 렌더', () => {
  const sub = /<div class="pf-sub" id="fundCompSub">([^<]*)<\/div>/.exec(html);
  assert.ok(sub, 'index.html에 #fundCompSub 부제 누락');
  assert.doesNotMatch(sub[1], /\d{4}\s*[.\-]\s*\d{1,2}/, '부제에 고정 연월이 하드코딩됨: ' + sub[1]);
  assert.ok(appJs.includes("getElementById('fundCompSub')"), 'app.js가 부제를 채우지 않음');
  assert.ok(appJs.includes('음영=추정({p}~)'), 'estimatedFrom 기반 추정 구간 문구 누락');
});

test('기간 선택 상태·공시 기준 고지·모션 축소 접근성 계약', () => {
  assert.match(html, /data-range="all" class="active" aria-pressed="true"/);
  assert.ok(appJs.includes("setAttribute('aria-pressed',String(active))"));
  assert.ok(html.includes('실제 현재 보유내역이 아닙니다'));
  assert.ok(css.includes('@media (prefers-reduced-motion: reduce)'));
});
