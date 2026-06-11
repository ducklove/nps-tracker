/* 국민연금 국내주식 포트폴리오 대시보드
   - ES module 미사용(file:// 로컬 열람 호환), IIFE 일반 스크립트(defer).
   - 데이터: data.json(fetch, 캐시버스팅) → 실패 시 data.js(script 폴백) → 둘 다 실패 시 빈 상태.
   - 데이터 계약 v2의 신규 필드(schemaVersion/composition/warnings/fundPortfolio.targets)는
     전부 선택적: 없으면(스키마 v1) 해당 UI를 우아하게 생략하고 기존 동작을 유지한다. */
(function(){
  'use strict';

  /* ---------- XSS 위생: 외부 데이터 유래 문자열은 innerHTML·tooltip HTML 진입 전 esc ---------- */
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  /* ---------- URL 파라미터: ?embed=true (헤더·출처 숨김), ?theme=light|dark (부모 테마 강제) ---------- */
  const _params=new URLSearchParams(location.search);
  const _embed=_params.get('embed')==='true';
  const _themeParam=_params.get('theme');
  if(_embed) document.body.classList.add('embed');

  /* 테마: 쿼리 theme 우선 → localStorage → 시스템. (데이터 로드 전에 즉시 적용) */
  const _savedTheme=localStorage.getItem('nps-theme');
  const _initialTheme=_themeParam || _savedTheme ||
    (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark':'light');
  document.documentElement.setAttribute('data-theme', _initialTheme);

  /* ---------- 영문 모드 (F-11): ?lang=en|ko → localStorage → 기본 ko ----------
     UI 문구만 번역(사전: assets/i18n.js). 종목명·경고문 등 데이터 값은 원문 유지.
     t()=리터럴 치환, tt()=template {x} 슬롯 치환 — 사전에 없는 키는 한국어 원문 그대로. */
  const _langParam=_params.get('lang');
  const _lang=(_langParam==='en'||_langParam==='ko') ? _langParam :
    (localStorage.getItem('nps-lang')==='en' ? 'en' : 'ko');
  document.documentElement.lang=_lang;
  const I18N=(_lang!=='ko' && window.NPS_I18N && window.NPS_I18N[_lang]) || null;
  const t=s=>(I18N && I18N[s])||s;
  const tt=(key,vars)=>{ let s=t(key); Object.keys(vars||{}).forEach(k=>{ s=s.split('{'+k+'}').join(vars[k]); }); return s; };
  const LOC=_lang==='en' ? 'en-US' : 'ko-KR';
  if(I18N){
    document.querySelectorAll('[data-i18n]').forEach(el=>{
      const key=el.getAttribute('data-i18n')||el.textContent.trim();
      if(I18N[key]) el.textContent=I18N[key];
    });
    document.querySelectorAll('[data-i18n-html]').forEach(el=>{   // 사전 통제 HTML(소스 노트) — 사용자 데이터 아님
      const v=I18N[el.getAttribute('data-i18n-html')];
      if(v) el.innerHTML=v;
    });
    const si=document.getElementById('tableSearch');
    if(si){ si.placeholder=t('종목명·코드 검색'); si.setAttribute('aria-label', t('보유 종목 검색')); }
  }

  /* ---------- ECharts CDN 로더 (SRI) ---------- */
  // SHA-384는 npm 패키지 echarts@5.6.0의 dist/echarts.min.js 원본 바이트 기준
  // (jsDelivr /npm/ 엔드포인트는 패키지 파일을 그대로 서빙).
  const ECHARTS_SRC='https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js';
  const ECHARTS_SRI='sha384-pPi0zxBAoDu6+JXW/C68UZLvBUUtU+7zonhif43rqj7pxsGyqyqzcian2Rj37Rss';
  function loadECharts(){
    return new Promise((resolve,reject)=>{
      if(typeof echarts!=='undefined'){ resolve(); return; }
      const s=document.createElement('script');
      s.src=ECHARTS_SRC;
      if(ECHARTS_SRI){ s.integrity=ECHARTS_SRI; s.crossOrigin='anonymous'; }
      s.onload=resolve;
      s.onerror=()=>reject(new Error('echarts load failed'));
      document.head.appendChild(s);
    });
  }
  const _echartsReady=loadECharts();   // 데이터 로드와 병렬로 시작
  _echartsReady.catch(()=>{});         // 데이터 실패 시 unhandled rejection 방지

  /* ---------- 데이터 로더: data.json → data.js 폴백 (document.write 미사용) ----------
     매 로드 고유 t= 파라미터로 GitHub Pages 캐시를 우회해 iframe 임베드에서도 항상 최신을 보장. */
  function loadData(){
    return fetch('data.json?t='+Date.now(), {cache:'no-store'})
      .then(r=>{ if(!r.ok) throw new Error('data.json http '+r.status); return r.json(); })
      .catch(()=>new Promise((resolve,reject)=>{   // 404·file:// 등 → data.js 폴백
        const s=document.createElement('script');
        s.src='data.js?t='+Date.now();
        s.onload=()=>{ window.NPS_DATA ? resolve(window.NPS_DATA) : reject(new Error('NPS_DATA missing')); };
        s.onerror=()=>reject(new Error('data.js load failed'));
        document.head.appendChild(s);
      }));
  }

  function showDataError(){
    document.querySelector('.container').insertAdjacentHTML('beforeend',
      '<div class="empty">'+t('데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')+'</div>');
  }

  /* ---------- 초기화(비동기 진입점) ---------- */
  function init(DATA){

    /* ---------- 포매터 ---------- */
    function fmtKrwJo(v){
      const av=Math.abs(v);
      if(_lang==='en'){   // 영문: ₩ + T(1e12)/B(1e9)/M(1e6) — 조/억 단위는 영어권에 생소
        const u=av>=1e12?[1e12,'T']:av>=1e9?[1e9,'B']:av>=1e6?[1e6,'M']:null;
        if(!u) return '₩'+Math.round(v).toLocaleString(LOC);
        const x=v/u[0]; const d=Math.abs(x)>=100?0:Math.abs(x)>=10?1:2;
        return '₩'+x.toLocaleString(LOC,{maximumFractionDigits:d,minimumFractionDigits:d})+u[1];
      }
      if(av>=1e12){ const x=v/1e12; const d=av>=1e15?0:av>=1e14?1:av>=1e13?2:3; return x.toLocaleString('ko-KR',{maximumFractionDigits:d,minimumFractionDigits:d})+'조'; }
      if(av>=1e8){ const x=v/1e8; const d=av>=1e11?0:av>=1e10?1:av>=1e9?2:3; return x.toLocaleString('ko-KR',{maximumFractionDigits:d,minimumFractionDigits:d})+'억'; }
      return Math.round(v).toLocaleString('ko-KR')+'원';
    }
    function fmtPct(v){ if(v==null) return '-'; return (v>0?'+':'')+v.toFixed(2)+'%'; }
    function pctClass(v){ if(v==null||v===0) return 'nps-neutral'; return v>0?'nps-up':'nps-down'; }

    /* 등락률 → 색 (snapshot_nps의 returnToColor 이식) */
    function returnToColor(pct, range){
      range=range||20;
      if(pct==null) return '#9ca3af';
      let t=Math.max(-1,Math.min(1,pct/range)); const a=Math.abs(t);
      const gray=[156,163,175], blue=[37,99,235], red=[220,38,38];
      const tgt=t<0?blue:red;
      const r=Math.round(gray[0]+(tgt[0]-gray[0])*a), g=Math.round(gray[1]+(tgt[1]-gray[1])*a), b=Math.round(gray[2]+(tgt[2]-gray[2])*a);
      return '#'+[r,g,b].map(x=>x.toString(16).padStart(2,'0')).join('');
    }
    /* 트리맵 색 (blue→gray→red, ±5% clamp) */
    function treemapColor(pct){
      if(pct==null) return _isDark()?'#475569':'#9ca3af';
      const c=Math.max(-5,Math.min(5,pct)); const t=(c+5)/10;
      let r,g,b;
      if(t<0.5){ const s=t/0.5; r=Math.round(37+(148-37)*s); g=Math.round(99+(163-99)*s); b=Math.round(235+(184-235)*s); }
      else{ const s=(t-0.5)/0.5; r=Math.round(148+(220-148)*s); g=Math.round(163+(38-163)*s); b=Math.round(184+(38-184)*s); }
      return 'rgb('+r+','+g+','+b+')';
    }

    /* ---------- 테마 ---------- */
    function _isDark(){ return document.documentElement.getAttribute('data-theme')==='dark'; }
    function _textColor(){ return getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim()||'#888'; }
    function _gridColor(){ return getComputedStyle(document.documentElement).getPropertyValue('--border').trim()||'#ccc'; }

    /* ---------- 요약 카드 ---------- */
    function renderSummary(){
      const s=DATA.summary||{};
      document.getElementById('metaAsOf').textContent =
        tt('기준일 {d} · 갱신 {u} · {n}종목', {d:s.asOf||DATA.asOf||'-', u:DATA.lastUpdated||'-', n:(s.count||0).toLocaleString(LOC)});
      const cards=[
        {label:t('국내주식 평가금액'), value:fmtKrwJo(s.totalValue||0), sub:'NAV '+(s.nav!=null?s.nav.toFixed(2):'-'), cls:''},
        {label:esc(s.asOf||DATA.asOf||t('기준일')), value:fmtPct(s.todayPct), sub:t('일간 등락률(가중평균)'), cls:pctClass(s.todayPct)},
        {label:'MTD', value:fmtPct(s.mtdPct), sub:t('전월말 대비'), cls:pctClass(s.mtdPct)},
        {label:'YTD', value:fmtPct(s.ytdPct), sub:t('연초 대비'), cls:pctClass(s.ytdPct)},
      ];
      document.getElementById('summary').innerHTML = cards.map(c=>
        '<div class="pf-summary-card"><div class="pf-summary-label">'+c.label+'</div>'+
        '<div class="pf-summary-value '+c.cls+'">'+c.value+'</div>'+
        '<div class="pf-summary-sub">'+c.sub+'</div></div>'
      ).join('');
    }

    /* ---------- 출처 배지: 구성(보유내역) 기준 vs 가격 기준 ---------- */
    function renderCompBadge(){
      const el=document.getElementById('compBadge');
      if(!el) return;
      const priceAsOf=(DATA.summary||{}).asOf||DATA.asOf||'';
      let txt='';
      const comp=DATA.composition;
      if(comp && comp.date){
        txt=tt('구성 기준 {d}', {d:comp.date})+' ('+(comp.source==='seed'?t('연말 공시'):t('공공데이터'))+')';
      } else {
        const m=/\((\d{4}-\d{2}-\d{2})\)/.exec(String(DATA.source||''));   // v1 폴백: source에서 날짜 파싱
        if(m) txt=tt('구성 기준 {d}', {d:m[1]});
      }
      if(txt && priceAsOf) txt+=tt(' · 가격 기준 {d}', {d:priceAsOf});
      if(txt){ el.textContent=txt; el.style.display=''; }
      else { el.style.display='none'; }
    }

    /* ---------- 데이터 경고 배너 ---------- */
    function renderWarnings(){
      const el=document.getElementById('warnings');
      if(!el) return;
      const ws=Array.isArray(DATA.warnings) ? DATA.warnings.filter(w=>w!=null && String(w).trim()!=='') : [];
      if(!ws.length){ el.style.display='none'; return; }
      el.innerHTML='<ul class="warn-list">'+ws.map(w=>'<li>'+esc(w)+'</li>').join('')+'</ul>';
      el.style.display='';
    }

    /* ---------- 오늘의 기여도 (F-1) ----------
       holdings(평가액 상위 목록)에서 전일 평가액 prev=mv/(1+chg/100)을 복원해
       기여도 (mv-prev)/Σprev×100 을 계산, 상승·하락 Top5를 미니바로 표시. */
    function renderContrib(){
      const sec=document.getElementById('contribSection');
      if(!sec) return;
      const universe=DATA.holdings||[];
      const items=[]; let totalPrev=0;
      universe.forEach(h=>{
        if(!h || h.change_pct==null || !(h.market_value>0)) return;   // change_pct null 제외
        const denom=1+h.change_pct/100;
        if(!(denom>0)) return;
        const prev=h.market_value/denom;
        totalPrev+=prev;
        items.push({name:h.stock_name||h.stock_code||'-', mv:h.market_value, prev:prev});
      });
      if(!items.length || !(totalPrev>0)){ sec.style.display='none'; return; }   // 데이터 부족 → 숨김
      items.forEach(it=>{ it.contrib=(it.mv-it.prev)/totalPrev*100; });
      const ups=items.filter(it=>it.contrib>0).sort((a,b)=>b.contrib-a.contrib).slice(0,5);
      const downs=items.filter(it=>it.contrib<0).sort((a,b)=>a.contrib-b.contrib).slice(0,5);
      if(!ups.length && !downs.length){ sec.style.display='none'; return; }
      const maxAbs=Math.max.apply(null, ups.concat(downs).map(it=>Math.abs(it.contrib))) || 1;
      const row=(it,dir)=>{
        const w=Math.max(2, Math.abs(it.contrib)/maxAbs*100).toFixed(1);
        return '<div class="contrib-row">'+
          '<span class="contrib-name" title="'+esc(it.name)+'">'+esc(it.name)+'</span>'+
          '<span class="contrib-track"><span class="contrib-bar '+(dir==='up'?'up':'down')+'" style="width:'+w+'%"></span></span>'+
          '<span class="contrib-val '+(dir==='up'?'nps-up':'nps-down')+'">'+fmtPct(it.contrib)+'p</span>'+
        '</div>';
      };
      document.getElementById('contribUp').innerHTML =
        ups.length ? ups.map(it=>row(it,'up')).join('') : '<div class="contrib-none">'+t('상승 기여 종목 없음')+'</div>';
      document.getElementById('contribDown').innerHTML =
        downs.length ? downs.map(it=>row(it,'down')).join('') : '<div class="contrib-none">'+t('하락 기여 종목 없음')+'</div>';
      const sub=document.getElementById('contribSub');
      if(sub) sub.textContent=tt('평가액 상위 {n}종목 기준 추정', {n:universe.length});
      sec.style.display='';
    }

    /* ---------- 섹터 분석 (F-7) ----------
       발행물 sectors(섹터별 비중·등락·기여도)를 가로 막대 목록으로 표시.
       상위 12개 + 잔여 합산 한 줄. 데이터 없으면(업종 매핑 실패) 섹션 숨김 유지. */
    function renderSectors(){
      const sec=document.getElementById('sectorSection');
      const box=document.getElementById('sectorBars');
      if(!sec || !box) return;
      const all=(DATA.sectors||[]).filter(s=>s && s.value>0);
      if(!all.length) return;
      const top=all.slice(0,12), rest=all.slice(12);
      const maxW=Math.max.apply(null, top.map(s=>s.weightPct||0)) || 1;
      const row=s=>'<div class="sector-row">'+
        '<span class="sector-name" title="'+esc(s.name)+' · '+s.count+'종목">'+esc(s.name)+
          ' <em>'+s.count+'</em></span>'+
        '<span class="contrib-track sector-track"><span class="sector-bar" style="width:'+
          Math.max(2,(s.weightPct||0)/maxW*100).toFixed(1)+'%"></span></span>'+
        '<span class="sector-w">'+(s.weightPct!=null?s.weightPct.toFixed(1)+'%':'-')+'</span>'+
        '<span class="sector-chg '+pctClass(s.changePct)+'">'+fmtPct(s.changePct)+'</span>'+
        '<span class="sector-contrib" title="'+t('포트폴리오 일간 기여도')+'">'+
          (s.contribPct!=null?fmtPct(s.contribPct)+'p':'-')+'</span>'+
      '</div>';
      let html=top.map(row).join('');
      if(rest.length){
        const wSum=rest.reduce((a,s)=>a+(s.weightPct||0),0);
        const cnt=rest.reduce((a,s)=>a+(s.count||0),0);
        html+='<div class="sector-row sector-rest">'+tt('그 외 {a}개 섹터 · {b}종목 · 비중 {w}%', {a:rest.length, b:cnt, w:wSum.toFixed(1)})+'</div>';
      }
      box.innerHTML=html;
      const sub=document.getElementById('sectorSub');
      if(sub) sub.textContent=tt('KRX 업종분류 기준 · {n}개 섹터 · 평가액 가중', {n:all.length});
      sec.style.display='';
    }

    /* ---------- 연말 구성 변화 (F-6) ----------
       발행물 yoy(최신 두 연말 아카이브 비교)를 3열로 표시. 아카이브가 2개 미만이면 숨김. */
    function renderYoy(){
      const sec=document.getElementById('yoySection');
      if(!sec) return;
      const y=DATA.yoy;
      if(!y || !y.from || !y.to) return;
      const none='<div class="contrib-none">'+t('없음')+'</div>';
      const li=(name,right,cls,tip)=>'<div class="contrib-row yoy-row" '+(tip?'title="'+esc(tip)+'"':'')+'>'+
        '<span class="contrib-name yoy-name">'+esc(name)+'</span>'+
        '<span class="yoy-val '+(cls||'')+'">'+right+'</span></div>';
      const added=(y.added||[]).map(h=>li(h.stock_name||h.stock_code,
        h.value!=null?fmtKrwJo(h.value):(h.shares||0).toLocaleString(LOC), '',
        tt('지분율 {p}%', {p:h.ownership_pct!=null?h.ownership_pct:'-'}))).join('');
      const removed=(y.removed||[]).map(h=>li(h.stock_name||h.stock_code,
        (h.ownership_pct!=null?tt('지분 {p}%', {p:h.ownership_pct}):(h.shares||0).toLocaleString(LOC)),'')).join('');
      const changed=(y.topChanges||[]).map(h=>li(h.stock_name||h.stock_code,
        fmtPct(h.change_pct), pctClass(h.change_pct),
        tt('{f}주 → {t}주', {f:(h.from_shares||0).toLocaleString(LOC), t:(h.to_shares||0).toLocaleString(LOC)}))).join('');
      document.getElementById('yoyAdded').innerHTML=added||none;
      document.getElementById('yoyRemoved').innerHTML=removed||none;
      document.getElementById('yoyChanged').innerHTML=changed||none;
      const sub=document.getElementById('yoySub');
      if(sub) sub.textContent=tt('{f} → {t} 공시 기준 · 신규 {a} · 전량매도 {r} · 수량변경 {c}종목',
        {f:y.from, t:y.to, a:y.addedTotal||0, r:y.removedTotal||0, c:y.changedTotal||0});
      sec.style.display='';
    }

    /* ---------- 해외주식 스냅샷 (F-9) ----------
       연 1회 공시(티커 없음 → 일별 재평가 불가)라 공시 평가액 그대로 상위 종목만 표시. */
    function renderForeign(){
      const sec=document.getElementById('foreignSection');
      const tbody=document.querySelector('#foreignTable tbody');
      if(!sec || !tbody) return;
      const f=DATA.foreign;
      const rows=(f && f.holdings)||[];
      if(!rows.length) return;
      tbody.innerHTML=rows.slice(0,20).map((h,i)=>'<tr>'+
        '<td>'+(i+1)+'</td>'+
        '<td class="pf-col-name" title="'+esc(h.name)+'">'+esc(h.name)+'</td>'+
        '<td>'+(h.value!=null?fmtKrwJo(h.value):'-')+'</td>'+
        '<td>'+(h.weightPct!=null?h.weightPct.toFixed(2)+'%':'-')+'</td>'+
        '<td>'+(h.ownershipPct!=null?h.ownershipPct.toFixed(2)+'%':'-')+'</td>'+
      '</tr>').join('');
      const sub=document.getElementById('foreignSub');
      if(sub) sub.textContent=tt('{d} 연말 공시 기준 · 공시 {n}종목(원화 10억원 미만 제외) 중 상위 {k}종목 · 공시 평가액 합 {v}',
        {d:f.date, n:f.count||rows.length, k:Math.min(rows.length,20), v:fmtKrwJo(f.total||0)});
      sec.style.display='';
    }

    /* ---------- 테이블 (정렬 + 검색 F-3) ---------- */
    let _sortKey='mv', _sortAsc=false;
    let _allHoldings=null;
    let _searchQuery='';
    function _holdings(){ return _allHoldings || DATA.holdings || []; }
    function renderTable(){
      const tbody=document.querySelector('#npsTable tbody');
      const all=_holdings();
      const q=_searchQuery.trim().toLowerCase();
      let rows=all.slice();
      if(q) rows=rows.filter(h=>
        String(h.stock_name||'').toLowerCase().indexOf(q)>=0 ||
        String(h.stock_code||'').toLowerCase().indexOf(q)>=0);
      rows.sort((a,b)=>{
        if(_sortKey==='name') return _sortAsc? (a.stock_name||'').localeCompare(b.stock_name||'','ko') : (b.stock_name||'').localeCompare(a.stock_name||'','ko');
        const m={change:'change_pct',mv:'market_value',own:'ownership_pct'}[_sortKey];
        const va=a[m]||0, vb=b[m]||0; return _sortAsc? va-vb : vb-va;
      });
      tbody.innerHTML = rows.map((h,i)=>{       // 번호는 필터·정렬 결과 기준 재번호
        const cp=h.change_pct;
        return '<tr>'+
          '<td class="pf-col-num">'+(i+1)+'</td>'+
          '<td class="pf-col-name">'+esc(h.stock_name)+'</td>'+
          '<td class="'+pctClass(cp)+'">'+fmtPct(cp)+'</td>'+
          '<td>'+(h.price?Math.round(h.price).toLocaleString('ko-KR'):'-')+'</td>'+
          '<td>'+(h.shares?h.shares.toLocaleString('ko-KR'):'-')+'</td>'+
          '<td>'+(h.market_value?Math.round(h.market_value).toLocaleString('ko-KR'):'-')+'</td>'+
          '<td>'+(h.weight!=null?h.weight.toFixed(1)+'%':'-')+'</td>'+
          '<td>'+(h.ownership_pct!=null?h.ownership_pct.toFixed(2)+'%':'-')+'</td>'+
        '</tr>';
      }).join('') || (q ? '<tr><td colspan="8" class="pf-table-empty">'+t('검색 결과가 없습니다')+'</td></tr>' : '');
      const cnt=document.getElementById('searchCount');
      if(cnt) cnt.textContent = q ? rows.length+' / '+all.length : '';
      document.querySelectorAll('#npsTable th.pf-sortable').forEach(th=>{
        const base=th.textContent.replace(/[▲▼]/g,'').trim();
        th.textContent = th.dataset.sort===_sortKey ? base+(_sortAsc?' ▲':' ▼') : base;
      });
      const wrap=document.querySelector('.load-all-wrap');
      const total=DATA.holdingsTotal || _holdings().length;
      if(wrap){
        if(!_allHoldings && total > _holdings().length){
          document.getElementById('loadAllBtn').textContent=tt('전체 {n}종목 보기 (현재 상위 {k})', {n:total.toLocaleString(LOC), k:_holdings().length});
          wrap.style.display='';
        } else { wrap.style.display='none'; }
      }
    }
    document.querySelectorAll('#npsTable th.pf-sortable').forEach(th=>{
      th.addEventListener('click',()=>{
        const k=th.dataset.sort;
        if(_sortKey===k) _sortAsc=!_sortAsc; else { _sortKey=k; _sortAsc=(k==='name'); }
        renderTable();
      });
    });
    document.getElementById('loadAllBtn').addEventListener('click', async function(){
      this.textContent=t('불러오는 중…'); this.disabled=true;
      try{
        const r=await fetch('current.json',{cache:'no-cache'});
        const j=await r.json();
        _allHoldings=j.holdings||[];
        renderTable();
      }catch(e){ this.textContent=t('불러오기 실패 — 다시 시도'); this.disabled=false; }
    });
    const _searchInput=document.getElementById('tableSearch');
    if(_searchInput){
      _searchInput.addEventListener('input',()=>{ _searchQuery=_searchInput.value; renderTable(); });
    }

    /* ---------- 차트 ---------- */
    let _charts=[];
    function _newChart(el){
      const prev=echarts.getInstanceByDom(el);              // 개별 재렌더(기간 선택) 시 기존 인스턴스 정리
      if(prev){ prev.dispose(); _charts=_charts.filter(c=>c!==prev); }
      const c=echarts.init(el); _charts.push(c); return c;
    }

    /* 차트 공통 보일러플레이트: 테마 색 적용된 축·범례 팩토리 (각 차트 최종 옵션은 기존과 동일) */
    function _chartTheme(){
      const tc=_textColor(), gc=_gridColor();
      return {
        tc:tc, gc:gc,
        /* category 축 (기본 axisLabel: tc/10px) */
        cat(data, axisLabel, extra){
          return Object.assign({type:'category', data:data,
            axisLine:{lineStyle:{color:gc}},
            axisLabel:axisLabel||{color:tc,fontSize:10}}, extra||{});
        },
        /* value 축 (축선 숨김 + 옅은 splitLine) */
        val(axisLabel, extra){
          return Object.assign({type:'value', axisLine:{show:false},
            axisLabel:axisLabel||{color:tc,fontSize:10},
            splitLine:{lineStyle:{color:gc,width:0.5}}}, extra||{});
        },
        legend(extra){
          return Object.assign({textStyle:{color:tc,fontSize:11}}, extra||{});
        },
      };
    }

    function renderTreemap(){
      const el=document.getElementById('npsTreemap');
      const raw=(DATA.treemap||[]).slice().sort((a,b)=>(b.value||0)-(a.value||0)).slice(0,60);
      if(!raw.length) return;
      const isDark=_isDark();
      const leaf=d=>({name:d.name, value:d.value, changePct:d.changePct, itemStyle:{color:treemapColor(d.changePct)}});
      // 업종 정보가 있으면 섹터 1단계 그룹(F-7) — 단, 분류가 너무 세분화돼(KIND 산업분류 등)
      // 그룹이 16개를 넘으면 가독성이 떨어지므로 평면 유지(섹터 분석 섹션이 집계를 대신함).
      let data, levels;
      const sectorCount=new Set(raw.filter(d=>d.sector).map(d=>d.sector)).size;
      if(sectorCount>0 && sectorCount<=16){
        const groups={};
        raw.forEach(d=>{const k=d.sector||t('기타'); (groups[k]=groups[k]||[]).push(d);});
        data=Object.keys(groups).map(k=>({name:k, children:groups[k].map(leaf)}));
        levels=[
          {itemStyle:{borderColor:'transparent', gapWidth:3}},
          {upperLabel:{show:true, height:18, fontSize:10, fontWeight:600,
             color:isDark?'#cbd5e1':'#475569', overflow:'truncate'},
           itemStyle:{color:isDark?'#1e293b':'#f1f5f9',
             borderColor:isDark?'#334155':'#e5e7eb', borderWidth:1, gapWidth:1}},
          {itemStyle:{borderColor:isDark?'#334155':'#e5e7eb', borderWidth:1}}
        ];
      }else{
        data=raw.map(leaf);
      }
      _newChart(el).setOption({
        tooltip:{formatter(info){
          const d=info.data||{};
          let s='<strong>'+esc(info.name)+'</strong><br/>'+t('평가')+': '+Number(info.value).toLocaleString(LOC);
          if(d.changePct!=null) s+='<br/>'+t('일간')+': '+fmtPct(d.changePct);
          return s;
        }},
        series:[{type:'treemap', left:0,right:0,top:0,bottom:0, roam:false, nodeClick:false, breadcrumb:{show:false},
          itemStyle:{borderColor:isDark?'#334155':'#e5e7eb', borderWidth:1},
          levels:levels,
          label:{show:true, formatter(p){const cp=p.data.changePct; const s=cp!=null?(cp>0?'+':'')+cp.toFixed(2)+'%':''; return '{name|'+p.name+'}\n{pct|'+s+'}';},
            rich:{name:{fontSize:11,fontWeight:600,color:'#fff',lineHeight:16}, pct:{fontSize:10,color:'rgba(255,255,255,0.85)',lineHeight:14}}},
          data:data}]
      });
    }

    /* ---------- NAV vs KOSPI (+ 기간 선택 F-2) ---------- */
    let _navRange='all';
    /* asOf에서 캘린더 기준으로 거슬러 올라간 절단일(YYYY-MM-DD). 'all'·파싱 불가 시 null. */
    function _rangeCutoff(range, asOf){
      if(!/^\d{4}-\d{2}-\d{2}$/.test(asOf||'')) return null;
      if(range==='ytd') return asOf.slice(0,4)+'-01-01';
      const months={'1m':1,'3m':3,'6m':6}[range];
      if(!months) return null;
      const p=asOf.split('-').map(Number);
      let y=p[0], m=p[1]-months;
      while(m<1){ m+=12; y--; }
      const lastDay=new Date(Date.UTC(y,m,0)).getUTCDate();   // m(1-based)월의 말일
      const d=Math.min(p[2],lastDay);
      return y+'-'+String(m).padStart(2,'0')+'-'+String(d).padStart(2,'0');
    }

    /* ---------- 구간 성과 지표 (F-8): 선택 구간의 수익률·KOSPI 대비·변동성·MDD ---------- */
    function _stdev(a){
      if(a.length<2) return null;
      const m=a.reduce((x,y)=>x+y,0)/a.length;
      return Math.sqrt(a.reduce((x,y)=>x+(y-m)*(y-m),0)/(a.length-1));
    }
    function renderNavStats(nav, kRaw){
      const el=document.getElementById('navStats');
      if(!el) return;
      if(!nav || nav.length<2){ el.style.display='none'; return; }
      const ret=(nav[nav.length-1].nav/nav[0].nav-1)*100;
      const kVals=(kRaw||[]).filter(v=>v!=null&&v>0);
      const kRet=kVals.length>1 ? (kVals[kVals.length-1]/kVals[0]-1)*100 : null;
      const daily=[];
      for(let i=1;i<nav.length;i++){ const p=nav[i-1].nav; if(p>0) daily.push(nav[i].nav/p-1); }
      const sd=_stdev(daily);
      const vol=sd!=null ? sd*Math.sqrt(252)*100 : null;   // 일간 수익률 표준편차의 연환산
      let peak=-Infinity, mdd=0;
      nav.forEach(d=>{ if(d.nav>peak) peak=d.nav; const dd=d.nav/peak-1; if(dd<mdd) mdd=dd; });
      const chips=[
        {k:t('구간 수익률'), v:fmtPct(ret), cls:pctClass(ret)},
        {k:'KOSPI', v:fmtPct(kRet), cls:pctClass(kRet)},
        {k:t('초과수익'), v:kRet!=null?fmtPct(ret-kRet)+'p':'-', cls:kRet!=null?pctClass(ret-kRet):'nps-neutral'},
        {k:t('변동성(연환산)'), v:vol!=null?vol.toFixed(1)+'%':'-', cls:''},
        {k:'MDD', v:(mdd*100).toFixed(1)+'%', cls:mdd<0?'nps-down':'nps-neutral'},
      ];
      el.innerHTML=chips.map(c=>
        '<span class="stat-chip"><span class="stat-k">'+c.k+'</span>'+
        '<span class="stat-v '+c.cls+'">'+c.v+'</span></span>').join('');
      el.style.display='';
    }

    function renderNavWithKospi(){
      const el=document.getElementById('npsNavChart');
      const navAll=DATA.navHistory||[];
      if(!navAll.length) return;
      /* 선택 구간 절단. '전체'는 원본 그대로(기존과 동일) — 그 외엔 구간 시작점=1000 재정규화 */
      let nav=navAll, renorm=false;
      if(_navRange!=='all'){
        const asOf=(DATA.summary||{}).asOf||DATA.asOf||navAll[navAll.length-1].date;
        const cut=_rangeCutoff(_navRange, asOf);
        if(cut){ const w=navAll.filter(d=>d.date>=cut); if(w.length){ nav=w; renorm=true; } }
      }
      const labels=nav.map(d=>d.date.slice(5));
      const navBase=renorm && nav[0].nav>0 ? nav[0].nav : null;
      const navValues=navBase ? nav.map(d=>+(d.nav/navBase*1000).toFixed(2)) : nav.map(d=>d.nav);
      /* 선 색: 선택 구간 수익률 기반('전체'는 기존처럼 최근 365포인트 기준) */
      let navColor='#9ca3af';
      if(nav.length>1){
        const w=_navRange==='all' ? nav.slice(-365) : nav;
        if(w.length>1){ navColor=returnToColor((nav[nav.length-1].nav/w[0].nav-1)*100); }
      }
      /* KOSPI도 같은 구간에서 시작점=1000으로 정규화 */
      const kospiByDate=Object.fromEntries((DATA.kospiHistory||[]).map(d=>[d.date,d.value]));
      const kRaw=nav.map(d=>kospiByDate[d.date]!=null?kospiByDate[d.date]:null);
      let kNorm=[]; const kBase=kRaw.find(v=>v!=null&&v>0);
      if(kBase) kNorm=kRaw.map(v=>v!=null?+(v/kBase*1000).toFixed(2):null);
      renderNavStats(nav, kRaw);   // 구간 성과 지표(F-8) — 기간 선택과 함께 갱신
      const series=[{name:t('국민연금'), type:'line', data:navValues, symbol:'none', smooth:false,
        lineStyle:{color:navColor,width:2}, itemStyle:{color:navColor},
        areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:navColor+'33'},{offset:1,color:navColor+'00'}]}}}];
      if(kNorm.length){ series.push({name:'KOSPI', type:'line', data:kNorm, symbol:'none', smooth:false, lineStyle:{color:'#94a3b8',width:1.5,type:'dashed'}, itemStyle:{color:'#94a3b8'}}); }
      const T=_chartTheme();
      _newChart(el).setOption({
        grid:{left:60,right:14,top:28,bottom:26},
        legend:T.legend({show:kNorm.length>0, top:0, right:0}),
        xAxis:T.cat(labels, null, {splitLine:{show:false}}),
        yAxis:T.val(null, {scale:true}),
        /* 값이 구간 시작=1000 기준이므로 퍼센트도 구간 시작 대비 */
        tooltip:{trigger:'axis', formatter(ps){let s=esc(ps[0].axisValue); ps.forEach(p=>{const pct=((p.value/1000-1)*100).toFixed(2); s+='<br/>'+p.marker+' '+p.seriesName+': '+p.value.toLocaleString()+' ('+(pct>0?'+':'')+pct+'%)';}); return s;}},
        series:series
      });
    }
    const _rangeWrap=document.getElementById('navRange');
    if(_rangeWrap){
      _rangeWrap.querySelectorAll('button[data-range]').forEach(btn=>{
        btn.addEventListener('click',()=>{
          if(btn.dataset.range===_navRange) return;
          _navRange=btn.dataset.range;
          _rangeWrap.querySelectorAll('button[data-range]').forEach(b=>b.classList.toggle('active', b===btn));
          if(typeof echarts!=='undefined') renderNavWithKospi();
        });
      });
    }

    /* ---------- 기금 전체·부문별(공식 스냅샷) ---------- */
    const FUND_SECTORS=[
      {key:'domestic_stock', name:t('국내주식'), color:'#2563eb'},
      {key:'foreign_stock',  name:t('해외주식'), color:'#16a34a'},
      {key:'domestic_bond',  name:t('국내채권'), color:'#f59e0b'},
      {key:'foreign_bond',   name:t('해외채권'), color:'#fbbf24'},
      {key:'alternative',    name:t('대체투자'), color:'#a855f7'},
      {key:'short_term',     name:t('단기자금'), color:'#06b6d4'},
    ];
    // 추정 구간(estimatedFrom~끝) 음영 markArea
    function _fundEstMark(periods){
      const ef=(DATA.fundPortfolio||{}).estimatedFrom;
      if(!ef) return undefined;
      const i=periods.indexOf(ef); if(i<0) return undefined;
      return {silent:true, itemStyle:{color:_isDark()?'rgba(250,204,21,0.13)':'rgba(245,158,11,0.10)'},
        label:{show:true, position:'insideTop', color:_textColor(), fontSize:10, formatter:t('추정')},
        data:[[{xAxis:periods[i]},{xAxis:periods[periods.length-1]}]]};
    }
    function fundPeriodLabel(p){ const a=String(p).split('-'); return a[1]&&a[1]!=='01'? a[0]+'.'+(+a[1]) : a[0]; }
    function _fundSeries(){ const fp=DATA.fundPortfolio; return fp&&fp.series&&fp.series.length? fp.series : null; }
    // 월별 X축 라벨: 매년 1월과 마지막 포인트만 표시(연도 또는 연.월)
    function _fundAxisLabel(periods){
      const N=periods.length;
      return {color:_textColor(), fontSize:10,
        interval:(idx,val)=> String(val).slice(5)==='01' || idx===N-1,
        formatter:v=>fundPeriodLabel(v)};
    }

    function renderFundTotalChart(){
      const el=document.getElementById('npsFundTotalChart'), sec=document.getElementById('fundTotalSection');
      const series=_fundSeries();
      if(!series){ if(sec)sec.style.display='none'; return; }
      if(sec)sec.style.display='';
      const periods=series.map(s=>s.period);
      const totals=series.map(s=>s.total||0);
      const T=_chartTheme();
      const primary=getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()||'#2563eb';
      _newChart(el).setOption({
        grid:{left:62,right:16,top:16,bottom:26},
        xAxis:T.cat(periods, _fundAxisLabel(periods), {boundaryGap:false, axisTick:{show:false}}),
        yAxis:T.val({color:T.tc,fontSize:10, formatter:v=>_lang==='en'?'₩'+(v/1e12).toFixed(0)+'T':(v/1e12).toFixed(0)+'조'}, {min:0}),
        tooltip:{trigger:'axis', formatter(ps){const p=ps[0]; return esc(fundPeriodLabel(p.axisValue))+'<br/>'+t('기금 전체')+' '+fmtKrwJo(p.value);}},
        series:[{type:'line', data:totals, symbol:'none', smooth:false, lineStyle:{color:primary,width:2}, itemStyle:{color:primary},
          markArea:_fundEstMark(periods),
          areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:primary+'40'},{offset:1,color:primary+'00'}]}}}]
      });
    }

    function renderFundCompChart(){
      const el=document.getElementById('npsFundCompChart'), sec=document.getElementById('fundCompSection');
      const series=_fundSeries();  // 전체(공표 + 추정), 추정 구간은 음영으로 구분
      if(!series){ if(sec)sec.style.display='none'; return; }
      if(sec)sec.style.display='';
      const periods=series.map(s=>s.period);
      const amt=series.map(s=>FUND_SECTORS.map(se=> s[se.key]||0));
      const pct=series.map((s,i)=>{ const t=s.total || amt[i].reduce((a,b)=>a+b,0); return amt[i].map(v=> t? +(v/t*100).toFixed(2):0); });
      const T=_chartTheme();
      const echSeries=FUND_SECTORS.map((se,j)=>({
        name:se.name, type:'line', stack:'pct', smooth:false, symbol:'none',
        lineStyle:{width:0}, areaStyle:{opacity:0.88}, emphasis:{focus:'series'},
        itemStyle:{color:se.color},
        data:pct.map(row=>row[j]),
      }));
      if(echSeries[0]) echSeries[0].markArea=_fundEstMark(periods);  // 추정 구간 음영
      _newChart(el).setOption({
        grid:{left:44,right:16,top:36,bottom:26},
        legend:T.legend({top:2, itemWidth:12, itemHeight:8, itemGap:10}),
        xAxis:T.cat(periods, _fundAxisLabel(periods), {boundaryGap:false, axisTick:{show:false}}),
        yAxis:T.val({color:T.tc,fontSize:10, formatter:'{value}%'}, {min:0, max:100}),
        tooltip:{trigger:'axis', confine:true, formatter(ps){
          let s=esc(fundPeriodLabel(ps[0].axisValue));
          ps.slice().reverse().forEach(p=>{ const a=amt[p.dataIndex][p.seriesIndex];
            s+='<br/>'+p.marker+p.seriesName+': '+p.value.toFixed(1)+'%  ('+fmtKrwJo(a)+')'; });
          return s;
        }},
        series:echSeries
      });
    }

    // 중기 자산배분 목표비중(%): 데이터(fundPortfolio.targets) 우선, 없으면 하드코딩 폴백.
    // 단기자금은 잔여 운용이라 목표 0.
    const FUND_TARGET=(DATA.fundPortfolio && DATA.fundPortfolio.targets) ||
      {domestic_stock:20.8, foreign_stock:34.7, domestic_bond:23.1, foreign_bond:7.4, alternative:14.0, short_term:0};
    // 현재 vs 목표 비중을 가로 그룹막대로 비교(div id는 기존 npsFundPieChart 재사용).
    function renderFundPieChart(){
      const el=document.getElementById('npsFundPieChart'), sec=document.getElementById('fundPieSection');
      const all=_fundSeries();
      if(!all){ if(sec)sec.style.display='none'; return; }
      if(sec)sec.style.display='';
      const latest=all[all.length-1];  // 최신(추정 포함) 시점
      const tot=FUND_SECTORS.reduce((a,se)=>a+(latest[se.key]||0),0) || 1;
      // 부문별 현재%/목표%/편차. 목표 큰 순 정렬.
      const rows=FUND_SECTORS.map(se=>({name:se.name, color:se.color,
        cur:+((latest[se.key]||0)/tot*100).toFixed(1), tgt:FUND_TARGET[se.key]||0}))
        .sort((a,b)=>(b.tgt-a.tgt)||(b.cur-a.cur));
      const cats=rows.map(r=>r.name);
      const T=_chartTheme();
      const sub=document.getElementById('fundPieSub');
      if(sub){
        let txt=tt('{p} 현재 vs 중기 자산배분 목표 · 현재 막대 끝 = 목표 대비 편차(%p)', {p:fundPeriodLabel(latest.period)+' '+(latest.estimated?t('추정'):t('공표'))});
        const note=DATA.fundPortfolio && DATA.fundPortfolio.targetsNote;
        if(note) txt+=' · '+note;
        sub.textContent=txt;
      }
      _newChart(el).setOption({
        grid:{left:66,right:64,top:28,bottom:24},
        legend:T.legend({top:0, right:0, data:[t('현재'),t('목표')]}),
        tooltip:{trigger:'axis', axisPointer:{type:'shadow'}, formatter(ps){
          const r=rows[ps[0].dataIndex]; const d=+(r.cur-r.tgt).toFixed(1);
          return '<strong>'+r.name+'</strong><br/>'+t('현재')+' '+r.cur+'%<br/>'+t('목표')+' '+r.tgt+'%<br/>'+t('편차')+' '+(d>=0?'+':'')+d+'%p';
        }},
        xAxis:T.val({formatter:'{value}%',color:T.tc,fontSize:10}),
        yAxis:T.cat(cats, {color:T.tc,fontSize:11}, {axisTick:{show:false}}),
        series:[
          {name:t('현재'), type:'bar', barGap:'10%', barWidth:'36%',
            data:rows.map(r=>({value:r.cur, diff:+(r.cur-r.tgt).toFixed(1), itemStyle:{color:r.color}})),
            label:{show:true, position:'right', fontSize:10, color:T.tc,
              formatter:p=>p.value+'% ('+(p.data.diff>=0?'+':'')+p.data.diff+')'}},
          {name:t('목표'), type:'bar', barWidth:'36%',
            data:rows.map(r=>r.tgt), itemStyle:{color:_isDark()?'#475569':'#cbd5e1'},
            label:{show:true, position:'right', fontSize:10, color:T.tc, formatter:'{c}%'}}
        ]
      });
    }

    function renderCharts(){
      _charts.forEach(c=>c.dispose()); _charts=[];
      if(typeof echarts==='undefined') return;
      renderTreemap(); renderNavWithKospi();
      renderFundTotalChart(); renderFundCompChart(); renderFundPieChart();
    }

    /* ECharts CDN 로드 실패: 빈 화면 대신 안내 문구. 기금 데이터가 없는 섹션은 기존처럼 숨김. */
    function showChartError(){
      const hasFund=!!_fundSeries();
      [
        {id:'npsTreemap'},
        {id:'npsNavChart'},
        {id:'npsFundTotalChart', section:'fundTotalSection', needsFund:true},
        {id:'npsFundCompChart',  section:'fundCompSection',  needsFund:true},
        {id:'npsFundPieChart',   section:'fundPieSection',   needsFund:true},
      ].forEach(cs=>{
        if(cs.needsFund && !hasFund){
          const sec=document.getElementById(cs.section); if(sec) sec.style.display='none';
          return;
        }
        const el=document.getElementById(cs.id);
        if(el) el.innerHTML='<div class="chart-error">'+t('차트 라이브러리를 불러오지 못했습니다')+'</div>';
      });
    }

    /* ---------- 테마 토글 (embed 또는 theme 지정 시 숨김 — 부모가 제어) ---------- */
    const _toggle=document.getElementById('themeToggle');
    if(_embed || _themeParam){
      _toggle.style.display='none';
    } else {
      const syncToggleLabel=()=>{ _toggle.textContent = _isDark()?t('라이트 모드'):t('다크 모드'); };
      _toggle.addEventListener('click',()=>{
        const next=_isDark()?'light':'dark';
        document.documentElement.setAttribute('data-theme',next);
        localStorage.setItem('nps-theme',next);
        syncToggleLabel(); renderCharts();
      });
      syncToggleLabel();
    }

    /* ---------- 언어 토글 (F-11) — embed 또는 ?lang 지정 시 숨김(부모가 제어).
       문구가 정적 번역 패스·차트에 퍼져 있어 토글은 저장 후 새로고침으로 일괄 적용. */
    const _langBtn=document.getElementById('langToggle');
    if(_langBtn){
      if(_embed || _langParam){
        _langBtn.style.display='none';
      } else {
        _langBtn.textContent=_lang==='en'?'한국어':'EN';
        _langBtn.addEventListener('click',()=>{
          localStorage.setItem('nps-lang', _lang==='en'?'ko':'en');
          location.reload();
        });
      }
    }

    /* ---------- 실행 ---------- */
    renderSummary();
    renderCompBadge();
    renderWarnings();
    renderContrib();
    renderSectors();
    renderYoy();
    renderForeign();
    renderTable();
    _echartsReady.then(renderCharts, showChartError);
    window.addEventListener('resize',()=>_charts.forEach(c=>c.resize()));
  }

  loadData().then(init, showDataError);
})();
