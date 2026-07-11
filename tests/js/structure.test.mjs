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
