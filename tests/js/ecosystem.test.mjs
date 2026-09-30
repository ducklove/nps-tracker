// node --test tests/js 로 실행. Value Compass 생태계 통합 계약을 고정한다.
//  ① index.html 구조: vc:theme-boot 마커(인라인 부트, 스타일시트보다 앞), vc-tokens.css → app.css 순서,
//     vc-shell.js(defer, app.js보다 앞), body 최상단 <vc-shell tool="nps-tracker"> + 허브 링크 폴백
//  ② 벤더링 파일이 저장소 루트(= Pages 루트)에 있고, app.css가 방향색·폰트를 공용 토큰으로 alias
//  ③ format.js 계약 헬퍼(?embed 해석, ?code 정규화, 허브 메시지 검증)
//  ④ app.js 행위(가짜 DOM + node:vm): vc:ready 송신, vc:theme 수신, 토글 → VCShell.setTheme,
//     localStorage 차단 방어, ?code 포커스 → VCShell.setStock, embed 워치독은 리로드 대신 재렌더
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const require = createRequire(import.meta.url);
const F = require('../../assets/format.js');
const path = rel => fileURLToPath(new URL('../../' + rel, import.meta.url));
const read = rel => readFileSync(path(rel), 'utf8');
const html = read('index.html');
const css = read('assets/app.css');
const appSrc = read('assets/app.js');
const formatSrc = read('assets/format.js');
const HUB = 'https://ducklove.duckdns.org:3691';

/* ---------- ① index.html 구조 계약 ---------- */
test('head: vc:theme-boot 블록이 모든 스타일시트보다 앞에 한 번만 있고 채워져 있다', () => {
  const blocks = html.match(/<!-- vc:theme-boot -->[\s\S]*?<!-- \/vc:theme-boot -->/g) || [];
  assert.equal(blocks.length, 1);
  assert.match(blocks[0], /<script>[\s\S]*vc-theme-boot v1[\s\S]*<\/script>/, 'sync-ecosystem.mjs --write로 채워야 한다');
  assert.ok(blocks[0].includes("'nps-theme'"), '부트가 구 키 nps-theme를 이전해야 한다');
  const bootAt = html.indexOf('<!-- vc:theme-boot -->');
  const firstStyle = Math.min(...['<link rel="stylesheet"', '<style'].map(t => html.indexOf(t)).filter(i => i >= 0));
  assert.ok(bootAt < firstStyle, 'theme-boot은 첫 스타일시트보다 앞(FOUC 방지)');
  assert.doesNotMatch(html, /<html[^>]*data-theme=/, '<html>에 고정 data-theme를 두지 않는다(부트/폴백이 결정)');
});

test('head: vc-tokens.css → app.css, vc-shell.js(defer)가 format.js·app.js보다 앞', () => {
  const tokens = html.indexOf('<link rel="stylesheet" href="./vc-tokens.css?v=');
  const appCss = html.indexOf('<link rel="stylesheet" href="assets/app.css?v=');
  assert.ok(tokens > 0 && appCss > tokens, 'vc-tokens.css가 app.css보다 먼저');
  const shell = html.search(/<script src="\.\/vc-shell\.js\?v=[^"]+" defer><\/script>/);
  const fmt = html.indexOf('<script src="assets/format.js');
  const app = html.indexOf('<script src="assets/app.js');
  assert.ok(shell > 0 && shell < fmt && fmt < app, 'vc-shell.js → format.js → app.js (defer 실행 순서)');
});

test('body: 최상단 <vc-shell tool="nps-tracker"> + 허브 링크 폴백, 헤더의 수제 허브 링크는 제거', () => {
  const body = html.slice(html.indexOf('<body>'));
  const firstEl = /<body>\s*(?:<!--[\s\S]*?-->\s*)*<([a-z-]+)/.exec(body);
  assert.equal(firstEl[1], 'vc-shell');
  assert.match(body, /<vc-shell tool="nps-tracker"><a class="hub-link" href="https:\/\/ducklove\.duckdns\.org:3691" rel="noopener">Value Compass ↗<\/a><\/vc-shell>/);
  assert.equal((html.match(/class="hub-link"/g) || []).length, 1, '허브 링크는 셸 폴백 한 곳만');
});

/* ---------- ② 벤더링·토큰 alias ---------- */
test('벤더링 파일(vc-shell.js·vc-tokens.css)이 Pages 루트에 있고 직접 수정 금지 헤더를 가진다', () => {
  for (const f of ['vc-shell.js', 'vc-tokens.css']) assert.ok(existsSync(path(f)), f + ' 없음');
  assert.match(read('vc-shell.js'), /window\.VCShell/);
  assert.match(read('vc-tokens.css'), /--vc-up:/);
  assert.match(read('nps_tracker/vc_publish.py'), /^# vendored from value-invest/);
});

test('app.css: 상승·하락 색과 본문 폰트를 공용 토큰으로 alias(폴백 포함), 포커스 행 스타일', () => {
  assert.match(css, /--up:var\(--vc-up, #dc2626\); --down:var\(--vc-down, #2563eb\);/);
  assert.match(css, /--up:var\(--vc-up, #fca5a5\); --down:var\(--vc-down, #93c5fd\);/);
  assert.match(css, /font-family:var\(--vc-font-sans,/);
  assert.ok(css.includes('#npsTable tbody tr.pf-row-focus'));
  assert.ok(css.includes('html[data-embed] vc-shell{display:none;}'));
});

test('app.js: localStorage는 try/catch 래퍼로만 접근, postMessage는 허브 origin 지정("*" 금지)', () => {
  const direct = appSrc.split('\n').filter(l => /localStorage\.(get|set)Item/.test(l) && !/function _ls(Get|Set)/.test(l));
  assert.deepEqual(direct, []);
  assert.ok(!/postMessage\([^)]*'\*'\)/.test(appSrc));
  assert.ok(appSrc.includes("window.VCShell.setTheme(next)"));
  assert.ok(appSrc.includes("addEventListener('vc:themechange'"));
});

/* ---------- ③ format.js 계약 헬퍼 ---------- */
test('isEmbedParam: ?embed=true·1·빈 값은 embed, 0·false·없음은 아님', () => {
  for (const v of ['true', '1', '', 'yes']) assert.equal(F.isEmbedParam(v), true, v);
  for (const v of [null, undefined, '0', 'false']) assert.equal(F.isEmbedParam(v), false, String(v));
});

test('normalizeStockCode: 대소문자 무시 6자리 영숫자만', () => {
  assert.equal(F.normalizeStockCode('005930'), '005930');
  assert.equal(F.normalizeStockCode(' 0126z0 '), '0126Z0');
  for (const v of ['5930', '0059301', 'A05930!', '', null]) assert.equal(F.normalizeStockCode(v), null);
});

test('isVcMessage: source·type·origin이 모두 맞아야 true', () => {
  const origin = F.originOf(HUB + '/nps');
  assert.equal(origin, HUB);
  assert.equal(F.isVcMessage({ source: 'vc', type: 'vc:theme', theme: 'dark' }, HUB, origin, 'vc:theme'), true);
  assert.equal(F.isVcMessage({ source: 'vc', type: 'vc:theme' }, 'https://evil.example', origin, 'vc:theme'), false);
  assert.equal(F.isVcMessage({ source: 'x', type: 'vc:theme' }, HUB, origin, 'vc:theme'), false);
  assert.equal(F.isVcMessage('vc:theme', HUB, origin, 'vc:theme'), false);
  assert.equal(F.originOf('not a url'), null);
});

/* ---------- ④ app.js 행위 (가짜 DOM) ---------- */
function makeEl(id) {
  const listeners = {};
  const attrs = {};
  const el = {
    id, style: {}, dataset: {}, textContent: '', innerHTML: '', disabled: false,
    classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      toggle(c, on) { (on ?? !this._s.has(c)) ? this._s.add(c) : this._s.delete(c); }, contains(c) { return this._s.has(c); } },
    setAttribute(k, v) { attrs[k] = String(v); }, getAttribute(k) { return k in attrs ? attrs[k] : null },
    hasAttribute(k) { return k in attrs; },
    addEventListener(t, f) { (listeners[t] ||= []).push(f); },
    fire(t, ev) { (listeners[t] || []).forEach(f => f.call(el, ev || {})); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    insertAdjacentHTML(_, h) { el.innerHTML += h; }, appendChild() {}, closest() { return null; },
  };
  return el;
}

const DATA = {
  lastUpdated: '2026-09-25 15:48', asOf: '2026-09-23', source: 'seed(2024-12-31)',
  summary: { totalValue: 4e14, nav: 3092.31, count: 2, todayPct: 1.01, mtdPct: 3.9, ytdPct: 71.5, asOf: '2026-09-23' },
  holdings: [
    { stock_code: '005930', stock_name: '삼성전자', shares: 1, price: 1, market_value: 2, change_pct: 1, weight: 60, ownership_pct: 7 },
    { stock_code: '000660', stock_name: 'SK하이닉스', shares: 1, price: 1, market_value: 1, change_pct: -1, weight: 40, ownership_pct: 7 },
  ],
  holdingsTotal: 2, navHistory: [], kospiHistory: [], treemap: [],
};

async function boot({ search = '', framed = false, shell = true, storageThrows = false, data = DATA, fetchImpl } = {}) {
  const els = {};
  const byId = id => (els[id] ||= makeEl(id));
  const tbody = byId('#npsTable tbody');
  const htmlAttrs = {};
  const docListeners = {};
  const winListeners = {};
  const posted = [];
  const calls = { setTheme: [], setStock: [], reload: 0 };
  const document = {
    documentElement: {
      setAttribute(k, v) { htmlAttrs[k] = String(v); }, getAttribute(k) { return k in htmlAttrs ? htmlAttrs[k] : null; },
      set lang(v) { htmlAttrs.lang = v; },
    },
    body: makeEl('body'), head: { appendChild() {} }, visibilityState: 'visible',
    getElementById: byId,
    querySelector: sel => (sel === '#npsTable tbody' ? tbody : sel === '.container' ? byId('container') : byId(sel)),
    querySelectorAll: () => [],
    createElement: () => makeEl('script'),
    addEventListener(t, f) { (docListeners[t] ||= []).push(f); },
    dispatchEvent(ev) { (docListeners[ev.type] || []).forEach(f => f(ev)); return true; },
  };
  const storage = {
    _m: new Map(),
    getItem(k) { if (storageThrows) throw new Error('SecurityError'); return this._m.has(k) ? this._m.get(k) : null; },
    setItem(k, v) { if (storageThrows) throw new Error('SecurityError'); this._m.set(k, String(v)); },
  };
  const parent = { postMessage(msg, origin) { posted.push({ msg, origin }); } };
  const location = { search, pathname: '/nps-tracker/', hash: '', reload() { calls.reload++; } };
  const history = { state: null, replaceState(_s, _t, url) { location.search = url.slice(url.indexOf('?') >= 0 ? url.indexOf('?') : url.length); } };
  const responses = fetchImpl || (url => {
    if (url.startsWith('data.json')) return { ok: true, json: async () => data };
    return { ok: false, json: async () => null };
  });
  const ctx = {
    document, location, history, URLSearchParams, URL, Intl, CustomEvent, Promise, Object, Array, String, Math, Date, JSON,
    console, setTimeout, clearTimeout,
    setInterval: () => 0,
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    matchMedia: () => ({ matches: false }),
    fetch: async url => responses(url),
    addEventListener(t, f) { (winListeners[t] ||= []).push(f); },
  };
  Object.defineProperty(ctx, 'localStorage', { get() { return storage; } });
  ctx.window = ctx;
  ctx.parent = framed ? parent : ctx;
  if (shell) {
    ctx.VCShell = {
      registry: { hub: HUB },
      setTheme(t) { calls.setTheme.push(t); htmlAttrs['data-theme'] = t; document.dispatchEvent(new CustomEvent('vc:themechange', { detail: { theme: t } })); },
      setStock(code, name) { calls.setStock.push([code, name]); },
    };
  }
  vm.createContext(ctx);
  vm.runInContext(formatSrc, ctx);
  vm.runInContext(appSrc, ctx);
  const flush = async () => { for (let i = 0; i < 10; i++) await new Promise(r => setImmediate(r)); };
  await flush();
  return { ctx, els, byId, tbody, htmlAttrs, docListeners, winListeners, posted, calls, flush, document };
}

test('embed(?embed=1)+iframe: body.embed, 허브 origin으로 vc:ready 송신, 테마 토글 숨김', async () => {
  const w = await boot({ search: '?embed=1', framed: true });
  assert.ok(w.document.body.classList.contains('embed'));
  assert.equal(w.posted.length, 1);
  assert.equal(w.posted[0].origin, HUB);
  assert.equal(w.posted[0].msg.source, 'vc');
  assert.equal(w.posted[0].msg.type, 'vc:ready');
  assert.equal(w.posted[0].msg.tool, 'nps-tracker');
  assert.equal(w.byId('themeToggle').style.display, 'none');
});

test('단독 페이지: vc:ready를 보내지 않고, 토글은 VCShell.setTheme → vc:themechange로 라벨 갱신', async () => {
  const w = await boot({});
  assert.equal(w.posted.length, 0);
  assert.equal(w.htmlAttrs['data-theme'], 'light');   // 부트 없음 → 폴백(prefers light)
  w.byId('themeToggle').fire('click');
  assert.deepEqual(w.calls.setTheme, ['dark']);
  assert.equal(w.byId('themeToggle').textContent, '라이트 모드');
});

test('셸 없이 허브의 vc:theme 메시지: 허브 origin만 적용하고 vc:themechange 발행(리로드 없음)', async () => {
  const w = await boot({ search: '?embed=true', framed: true, shell: false });
  let changed = 0;
  w.document.addEventListener('vc:themechange', () => changed++);
  const onMsg = w.winListeners.message[0];
  onMsg({ origin: 'https://evil.example', data: { source: 'vc', type: 'vc:theme', theme: 'dark' } });
  assert.notEqual(w.htmlAttrs['data-theme'], 'dark');
  onMsg({ origin: HUB, data: { source: 'vc', type: 'vc:theme', theme: 'dark' } });
  assert.equal(w.htmlAttrs['data-theme'], 'dark');
  assert.equal(changed, 1);
  assert.equal(w.calls.reload, 0);
});

test('localStorage 접근이 throw해도 초기화·토글이 동작한다', async () => {
  const w = await boot({ shell: false, storageThrows: true });
  assert.match(w.byId('metaAsOf').textContent, /2026-09-23/);
  w.byId('themeToggle').fire('click');
  assert.equal(w.htmlAttrs['data-theme'], 'dark');
});

test('?code=005930: 행 하이라이트 + VCShell.setStock(코드, 이름), 없는 코드는 조용히 무시', async () => {
  const w = await boot({ search: '?code=005930' });
  assert.deepEqual(w.calls.setStock.at(-1), ['005930', '삼성전자']);
  assert.match(w.tbody.innerHTML, /<tr data-code="005930" class="pf-row-focus" aria-selected="true">/);
  assert.match(w.tbody.innerHTML, /<tr data-code="000660">/);
  const miss = await boot({ search: '?code=999999' });
  assert.deepEqual(miss.calls.setStock.at(-1), [null, null]);
  assert.doesNotMatch(miss.tbody.innerHTML, /pf-row-focus/);
});

test('행 클릭: 포커스·?code 되쓰기, 같은 행 재클릭은 해제', async () => {
  const w = await boot({});
  const row = { getAttribute: k => (k === 'data-code' ? '000660' : null) };
  const target = { closest: () => row };
  w.tbody.fire('click', { target });
  assert.deepEqual(w.calls.setStock.at(-1), ['000660', 'SK하이닉스']);
  assert.equal(w.ctx.location.search, '?code=000660');
  w.tbody.fire('click', { target });
  assert.deepEqual(w.calls.setStock.at(-1), [null, null]);
  assert.equal(w.ctx.location.search, '');
});

test('신선도 워치독: embed는 새 스냅샷을 리로드 없이 재렌더, 단독 페이지는 리로드', async () => {
  let current = DATA;
  const fetchImpl = url => (url.startsWith('data.json')
    ? { ok: true, json: async () => current } : { ok: false, json: async () => null });
  const w = await boot({ search: '?embed=true', framed: true, fetchImpl });
  current = { ...DATA, lastUpdated: '2026-09-26 15:48', summary: { ...DATA.summary, asOf: '2026-09-24' } };
  w.docListeners.visibilitychange.forEach(f => f());
  await w.flush();
  assert.equal(w.calls.reload, 0);
  assert.match(w.byId('metaAsOf').textContent, /2026-09-26 15:48/);

  current = DATA;
  const s = await boot({ fetchImpl });
  current = { ...DATA, lastUpdated: '2026-09-26 15:48' };
  s.docListeners.visibilitychange.forEach(f => f());
  await s.flush();
  assert.equal(s.calls.reload, 1);
});

test('신선도 워치독: version.json 해시가 그대로면 data.json을 다시 받지 않는다', async () => {
  const seen = [];
  const fetchImpl = url => {
    seen.push(url.split('?')[0]);
    if (url.startsWith('version.json')) return { ok: true, json: async () => ({ files: { 'summary.json': 'sha256:' + 'a'.repeat(64) } }) };
    return { ok: true, json: async () => DATA };
  };
  const w = await boot({ fetchImpl });
  const realNow = Date.now;
  try {
    let t = realNow();
    w.ctx.Date = class extends Date { static now() { return t; } };
    // 첫 확인: 해시를 모르므로 data.json까지 확인 후 기준 해시 기억
    w.docListeners.visibilitychange.forEach(f => f());
    await w.flush();
    t += 120000;
    w.docListeners.visibilitychange.forEach(f => f());
    await w.flush();
  } finally { w.ctx.Date = Date; }
  const afterInit = seen.slice(seen.indexOf('version.json'));
  assert.deepEqual(afterInit, ['version.json', 'data.json', 'version.json']);
});
