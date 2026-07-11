/* assets/format.js — 순수 포맷/계산 유틸 (classic script, 전역 NpsFormat)
   - DOM·DATA에 의존하지 않는 순수 함수만 둔다. app.js보다 먼저 로드돼야 한다(index.html defer 순서).
   - UMD-lite: 브라우저에선 전역 NpsFormat, Node(node --test tests/js)에선 CommonJS export.
   - 구현은 app.js에서 동작 불변으로 추출한 것 — 수정 시 tests/js/*.test.mjs 동반 갱신. */
(function(root){
  'use strict';

  var LOC='ko-KR';

  /* ---------- XSS 위생: 외부 데이터 유래 문자열은 innerHTML·tooltip HTML 진입 전 esc ---------- */
  var esc = function(s){ return String(s ?? '').replace(/[&<>"']/g, function(c){ return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]; }); };

  /* template {x} 슬롯 치환 (동일 슬롯 반복 치환) */
  function tt(key, vars){
    var s=String(key);
    Object.keys(vars||{}).forEach(function(k){ s=s.split('{'+k+'}').join(vars[k]); });
    return s;
  }

  /* 초기 테마 결정: 쿼리 param → 저장 키 'theme' → 구 키 'nps-theme'(마이그레이션 대상) → 시스템.
     migrate: 'nps-theme'만 있으면 'theme'로 이전해야 할 값(없으면 null). param 유무와 무관하게 이전한다. */
  function resolveInitialTheme(opts){
    opts=opts||{};
    var migrate=(!opts.saved && opts.legacy) ? opts.legacy : null;
    var theme=opts.param || opts.saved || opts.legacy ||
      (opts.prefersDark ? 'dark' : 'light');
    return {theme:theme, migrate:migrate};
  }

  /* ---------- 포맷터 ---------- */
  function fmtKrwJo(v){
    var av=Math.abs(v);
    if(av>=1e12){ var x=v/1e12; var d=av>=1e15?0:av>=1e14?1:av>=1e13?2:3; return x.toLocaleString(LOC,{maximumFractionDigits:d,minimumFractionDigits:d})+'조'; }
    if(av>=1e8){ var y=v/1e8; var e=av>=1e11?0:av>=1e10?1:av>=1e9?2:3; return y.toLocaleString(LOC,{maximumFractionDigits:e,minimumFractionDigits:e})+'억'; }
    return Math.round(v).toLocaleString(LOC)+'원';
  }
  function fmtSignedKrw(v){ if(v==null) return '-'; return (v>0?'+':'')+fmtKrwJo(v); }
  function fmtKrwAxis(v){
    var av=Math.abs(v||0);
    if(av>=1e12) return (v/1e12).toFixed(1)+'조';
    if(av>=1e8) return (v/1e8).toFixed(0)+'억';
    return Math.round(v).toLocaleString(LOC);
  }
  function fmtPct(v){ if(v==null) return '-'; return (v>0?'+':'')+v.toFixed(2)+'%'; }
  function fmtPlainPct(v){ if(v==null) return '-'; return v.toFixed(2)+'%'; }
  function fmtShares(v){
    if(v==null) return '-';
    var av=Math.abs(v);
    return Number(v).toLocaleString(LOC,{maximumFractionDigits:av>=1000?0:2});
  }
  function pctClass(v){ if(v==null||v===0) return 'nps-neutral'; return v>0?'nps-up':'nps-down'; }

  /* 등락률 → 색 (gray→blue/red 보간, ±range clamp) */
  function returnToColor(pct, range){
    range=range||20;
    if(pct==null) return '#9ca3af';
    var t=Math.max(-1,Math.min(1,pct/range)); var a=Math.abs(t);
    var gray=[156,163,175], blue=[37,99,235], red=[220,38,38];
    var tgt=t<0?blue:red;
    var r=Math.round(gray[0]+(tgt[0]-gray[0])*a), g=Math.round(gray[1]+(tgt[1]-gray[1])*a), b=Math.round(gray[2]+(tgt[2]-gray[2])*a);
    return '#'+[r,g,b].map(function(x){ return x.toString(16).padStart(2,'0'); }).join('');
  }
  /* 트리맵 색 (blue→gray→red, ±5% clamp). null이면 테마별 중립색 — isDark는 호출부가 주입. */
  function treemapColor(pct, isDark){
    if(pct==null) return isDark?'#475569':'#9ca3af';
    var c=Math.max(-5,Math.min(5,pct)); var t=(c+5)/10;
    var r,g,b;
    if(t<0.5){ var s=t/0.5; r=Math.round(37+(148-37)*s); g=Math.round(99+(163-99)*s); b=Math.round(235+(184-235)*s); }
    else{ var s2=(t-0.5)/0.5; r=Math.round(148+(220-148)*s2); g=Math.round(163+(38-163)*s2); b=Math.round(184+(38-184)*s2); }
    return 'rgb('+r+','+g+','+b+')';
  }

  /* ---------- 계산 ---------- */
  /* asOf에서 캘린더 기준으로 거슬러 올라간 절단일(YYYY-MM-DD). 'all'·파싱 불가 시 null. */
  function rangeCutoff(range, asOf){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(asOf||'')) return null;
    if(range==='ytd') return asOf.slice(0,4)+'-01-01';
    var months={'1m':1,'3m':3,'6m':6}[range];
    if(!months) return null;
    var p=asOf.split('-').map(Number);
    var y=p[0], m=p[1]-months;
    while(m<1){ m+=12; y--; }
    var lastDay=new Date(Date.UTC(y,m,0)).getUTCDate();   // m(1-based)월의 말일
    var d=Math.min(p[2],lastDay);
    return y+'-'+String(m).padStart(2,'0')+'-'+String(d).padStart(2,'0');
  }

  /* 표본 표준편차 (n-1). 원소 2개 미만이면 null. */
  function stdev(a){
    if(a.length<2) return null;
    var m=a.reduce(function(x,y){ return x+y; },0)/a.length;
    return Math.sqrt(a.reduce(function(x,y){ return x+(y-m)*(y-m); },0)/(a.length-1));
  }

  /* 시계열 재정규화: 첫 유효값(>0)을 1000으로. null은 보존, 유효 시작점 없으면 []. */
  function renormalizeTo1000(values){
    var arr=values||[];
    var base=arr.find(function(v){ return v!=null&&v>0; });
    if(!base) return [];
    return arr.map(function(v){ return v!=null ? +(v/base*1000).toFixed(2) : null; });
  }

  /* 오늘의 기여도: 전일 평가액 prev=mv/(1+chg/100)을 복원해 (mv-prev)/Σprev×100.
     유효 종목이 없거나 Σprev≤0이면 null. */
  function computeContributions(holdings){
    var items=[], totalPrev=0;
    (holdings||[]).forEach(function(h){
      if(!h || h.change_pct==null || !(h.market_value>0)) return;   // change_pct null 제외
      var denom=1+h.change_pct/100;
      if(!(denom>0)) return;
      var prev=h.market_value/denom;
      totalPrev+=prev;
      items.push({name:h.stock_name||h.stock_code||'-', mv:h.market_value, prev:prev});
    });
    if(!items.length || !(totalPrev>0)) return null;
    items.forEach(function(it){ it.contrib=(it.mv-it.prev)/totalPrev*100; });
    return items;
  }

  /* 보유 종목 테이블 정렬 비교자. name=한국어 localeCompare, 그 외 수치(누락은 0). */
  function holdingsComparator(sortKey, sortAsc){
    return function(a,b){
      if(sortKey==='name') return sortAsc? (a.stock_name||'').localeCompare(b.stock_name||'','ko') : (b.stock_name||'').localeCompare(a.stock_name||'','ko');
      var m={change:'change_pct',mv:'market_value',own:'ownership_pct'}[sortKey];
      var va=a[m]||0, vb=b[m]||0; return sortAsc? va-vb : vb-va;
    };
  }

  /* 종목명·코드 부분일치 검색(대소문자 무시, 공백 trim). 빈 검색어면 사본 반환. */
  function filterHoldings(holdings, query){
    var all=holdings||[];
    var q=String(query||'').trim().toLowerCase();
    var rows=all.slice();
    if(q) rows=rows.filter(function(h){
      return String(h.stock_name||'').toLowerCase().indexOf(q)>=0 ||
             String(h.stock_code||'').toLowerCase().indexOf(q)>=0;
    });
    return rows;
  }

  /* 기금 스냅샷 기간 라벨: '2024-01'→'2024', '2024-03'→'2024.3', '2024'→'2024' */
  function fundPeriodLabel(p){ var a=String(p).split('-'); return a[1]&&a[1]!=='01'? a[0]+'.'+(+a[1]) : a[0]; }

  /* 장중 잠정 매매 폴링 시간대: 평일 08:55~15:45 KST. clock={weekday,hhmm} (_kstClock() 산출물). */
  function isIntradayLive(clock){
    return !['Sat','Sun','토','일'].some(function(d){ return clock.weekday.startsWith(d); }) &&
           clock.hhmm>='08:55' && clock.hhmm<='15:45';
  }

  var api={
    esc:esc,
    tt:tt,
    resolveInitialTheme:resolveInitialTheme,
    fmtKrwJo:fmtKrwJo,
    fmtSignedKrw:fmtSignedKrw,
    fmtKrwAxis:fmtKrwAxis,
    fmtPct:fmtPct,
    fmtPlainPct:fmtPlainPct,
    fmtShares:fmtShares,
    pctClass:pctClass,
    returnToColor:returnToColor,
    treemapColor:treemapColor,
    rangeCutoff:rangeCutoff,
    stdev:stdev,
    renormalizeTo1000:renormalizeTo1000,
    computeContributions:computeContributions,
    holdingsComparator:holdingsComparator,
    filterHoldings:filterHoldings,
    fundPeriodLabel:fundPeriodLabel,
    isIntradayLive:isIntradayLive,
  };

  if(typeof module!=='undefined' && module.exports){ module.exports=api; }
  root.NpsFormat=api;
})(typeof globalThis!=='undefined' ? globalThis : this);
