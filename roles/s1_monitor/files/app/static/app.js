/* Routing, the needs-attention bell and the Fleet page. Loaded after api.js and charts.js. */
const main=document.getElementById('main');
let CUST=''; const charts=[]; function dispose(){ while(charts.length) charts.pop().dispose(); }
let RANGE='90d', COMPARE=[], CMP_OPEN=false, BELL_OPEN=false, ATTENTION=[];
/* Every page renderer carries the token of the render that started it and drops out after each
   await if a newer render has begun, so a slow fetch can never paint over a newer route. */
let RENDER_SEQ=0;

async function boot(){
  try{ await API.loadMeta(); }catch(e){ errorPanel(main,e); return; }
  API.meta.customers.forEach((c,i)=>CUSTCOL[c.customer]=css('--c'+((i%8)+1)));
  const sel=document.getElementById('custsel');
  sel.innerHTML='<option value="">All customers</option>'+API.meta.customers.map(c=>'<option>'+esc(c.customer)+'</option>').join('');
  sel.onchange=e=>{ CUST=e.target.value; render(); };
  document.getElementById('bell').onclick=e=>{ e.stopPropagation(); BELL_OPEN=!BELL_OPEN; document.getElementById('attnpanel').hidden=!BELL_OPEN; };
  document.addEventListener('click',e=>{ if(BELL_OPEN&&!e.target.closest('#attnpanel')){ BELL_OPEN=false; document.getElementById('attnpanel').hidden=true; } });
  window.addEventListener('hashchange',render);
  window.addEventListener('resize',()=>charts.forEach(c=>c.resize()));
  setInterval(()=>{ if(!document.hidden) render(); },60000);
  render();
}

async function render(){
  const my=++RENDER_SEQ;
  dispose(); window.scrollTo(0,0);
  const [route,arg,arg2,arg3]=(location.hash||'#fleet').slice(1).split('/');
  if(route==='device'){
    if(arg2) RANGE=arg2;
    COMPARE=(arg3&&arg3.startsWith('cmp='))?arg3.slice(4).split(',').map(Number).filter(Boolean):[];
  }
  document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('on',a.dataset.nav===route));
  try{ await ({fleet:renderFleet,device:renderDevice,trends:renderTrends}[route]||renderFleet)(arg,my); }
  catch(e){ if(my!==RENDER_SEQ) return; errorPanel(main,e); }
  if(my!==RENDER_SEQ) return;
  document.getElementById('clock').textContent='Data as of '+fmt(NOW.getTime())+' SAST';
  renderBell();
  if(route&&route!=='fleet') refreshAttention();
}

/* ---------- BELL (needs attention) ---------- */
/* Off the fleet page the bell has no payload of its own, so refresh it in the background. */
async function refreshAttention(){
  try{
    const F=await API.get('/api/fleet'+(CUST?'?customer='+encodeURIComponent(CUST):''),{banner:false});
    ATTENTION=F.attention||[]; renderBell();
  }catch(e){ /* the page itself already reports API failures */ }
}
function renderBell(){
  const att=ATTENTION||[]; const badge=document.getElementById('badge'); const panel=document.getElementById('attnpanel');
  const bad=att.filter(a=>a.severity==='bad').length;
  badge.hidden=!att.length; badge.textContent=att.length; badge.className='badge'+(bad?'':' warn');
  let h='<div class="ph">Needs attention <small>'+(att.length?att.length+' items, ranked by severity using each device\'s own thresholds':'')+'</small></div>';
  if(!att.length) h+='<div class="empty">Nothing needs attention.</div>';
  for(const a of att){
    h+='<div class="row" data-id="'+esc(a.device_id)+'"><span class="dot '+(a.severity==='bad'?'bad':'warn')+'"></span>'
      +'<span class="who">'+esc(a.label)+'<small>'+esc(a.customer)+'</small></span>'
      +'<span class="rule">'+esc(a.rule)+'</span>'
      +'<span class="val"><b>'+esc(a.value)+'</b> '+(a.limit?'<span>'+esc(a.limit)+'</span>':'')
      +(a.since?'<span class="faint"> · since '+esc(fmt(t(a.since)))+'</span>':'')+'</span></div>';
  }
  panel.innerHTML=h; panel.hidden=!BELL_OPEN;
  panel.querySelectorAll('.row').forEach(r=>r.onclick=()=>{ BELL_OPEN=false; location.hash='device/'+r.dataset.id+'/24h'; });
}

/* ---------- FLEET ---------- */
function tile(l,v,sev,d,sz){ return '<div class="tile"><div class="l">'+l+'</div><div class="v '+(sz||'')+'">'+v+'</div>'+(d?'<div class="d"><span class="dot '+sev+'"></span>'+d+'</div>':'')+'</div>'; }

async function renderFleet(arg,my){
  const F=await API.get('/api/fleet'+(CUST?'?customer='+encodeURIComponent(CUST):''));
  if(my!==RENDER_SEQ) return;
  NOW=new Date(F.generated_utc); ATTENTION=F.attention||[];
  const ds=F.devices||[]; const S=F.strip||{};
  const wAge=S.db_write_age_s==null?null:S.db_write_age_s/60;
  const wSev=wAge==null?'off':wAge>30?'bad':wAge>10?'warn':'good';
  const total=S.total==null?ds.length:S.total;
  const off=S.offline||0, disabled=S.disabled||0;
  let h='<h1>Fleet</h1><p class="sub">'+ds.length+' devices'+(CUST?' at '+esc(CUST):' across '+new Set(ds.map(d=>d.customer)).size+' customers')+'. Today is '+fmt(NOW.getTime(),'day')+' SAST.</p>';
  h+='<div class="strip" style="grid-template-columns:repeat(7,minmax(0,1fr))">'
   +tile('Online',S.online||0,'good',(S.online||0)+' of '+total)
   +tile('Offline',off,off?'bad':'good',off?'silent over '+GAP_MIN+' min':'none')
   +tile('Stale',S.stale||0,'off','silent over '+STALE_DAYS+' days'+(disabled?', '+disabled+' disabled':''))
   +tile('Items today',num(S.items_today),'info','fleet total so far')
   +tile('Good read today',fpct(S.good_read_today_pct),'info','fleet, weighted by items')
   +tile('Good read, 30 days',fpct(S.good_read_30d_pct),'info',num(S.items_30d)+' items')
   +tile('Last DB write',wAge==null?'–':Math.round(wAge)+' min ago',wSev,S.last_db_write_utc?fmt(t(S.last_db_write_utc),'time')+' SAST':'never','s')
   +'</div>';
  h+='<h2>Devices<small>today so far. Good read over 30 days is weighted by items and coloured against the device\'s own warn and bad limits.</small></h2>'
   +'<table class="dev"><thead><tr><th>Device</th><th>State</th><th>Last seen</th><th class="r">Items today</th><th class="r">Good read today</th><th class="r">Good read, 30 days</th><th>Items, 24h</th><th>C: drive</th><th>App</th></tr></thead><tbody>';
  let cur=null;
  for(const d of ds){
    if(d.customer!==cur){ cur=d.customer; h+='<tr class="cust"><td colspan="9"><span class="dot" style="background:'+esc(CUSTCOL[cur]||'')+'"></span> '+esc(cur)+'</td></tr>'; }
    const c=cfg(d.customer), th=thr(d.id,'good_read_pct');
    const gr=d.today.good_read_pct, lv=d.today.low_volume, sv=lv?null:sevColor(gr,th,'low');
    const g30=d.d30.good_read_pct, sv30=d.d30.low_volume?null:sevColor(g30,th,'low');
    const hours=(d.spark24||[]).map(y=>({y}));
    const cu=d.c_usage; const cs=cu==null?'':cu>c.storage_bad_pct?'bad':cu>c.storage_warn_pct?'warn':'';
    const muted=d.muted_until&&t(d.muted_until)>NOW;
    h+='<tr class="d'+(d.reporting_enabled?'':' dim')+'" data-id="'+esc(d.id)+'">'
      +'<td class="name">'+esc(label(d))+'<small>'+esc(d.serial_number||'')+'</small>'+(d.reporting_enabled?'':'<span class="tag">reporting disabled</span>')+(muted?'<span class="tag">muted</span>':'')+'</td>'
      +'<td><span class="dot '+(STATE_DOT[d.state]||'off')+'"></span> '+esc(d.state)+'</td>'
      +'<td class="tnum" style="color:var(--ink-2)">'+(d.last_seen?ago(t(d.last_seen))+' ago':'never')+'</td>'
      +'<td class="r tnum">'+num(d.today.items||0)+'</td>'
      +'<td class="r tnum big"><span class="pct">'+(gr==null?'<span style="color:var(--ink-3);font-size:13px;font-weight:400">no items</span>':(lv?'<span style="color:var(--ink-3)">'+fpct(gr)+'</span><span class="dot hollow" title="under '+MIN_ITEMS+' items"></span>':fpct(gr)+'<span class="dot '+sv+'"></span>'))+'</span></td>'
      +'<td class="r tnum big"><span class="pct">'+(g30==null?'<span style="color:var(--ink-3);font-size:13px;font-weight:400">no items</span>':(sv30==null?'<span style="color:var(--ink-3)">'+fpct(g30)+'</span><span class="dot hollow"></span>':fpct(g30)+'<span class="dot '+sv30+'"></span>'))+'</span></td>'
      +'<td>'+spark(hours,{bars:true,w:120,h:26,color:C.muted})+'</td>'
      +'<td>'+(cu==null?'–':'<span class="meter"><span class="bar"><i class="'+cs+'" style="width:'+Number(cu).toFixed(1)+'%"></i></span><span class="tnum">'+Number(cu).toFixed(0)+'%</span></span>')+'</td>'
      +'<td>'+(d.app_running==null?'–':d.app_running?'<span class="dot good"></span> running':'<span class="dot bad"></span> stopped')+'</td></tr>';
  }
  h+='</tbody></table>';
  main.innerHTML=h;
  main.querySelectorAll('table.dev tr.d').forEach(r=>r.onclick=()=>{ location.hash='device/'+r.dataset.id; });
}

/* ---------- DEVICE ---------- */
const devHash=id=>'device/'+id+'/'+RANGE+(COMPARE.length?'/cmp='+COMPARE.join(','):'');
/* navigate through the hash so back/forward and deep links keep working; re-render when it does not change */
function goDevice(id){ const h='#'+devHash(id); if(location.hash===h) render(); else location.hash=h; }
const uptimeD=s=>s?(Number(s)/86400).toFixed(1)+' days':'–';
const numOr=(v,suffix)=>v==null?'–':Number(v).toFixed(0)+(suffix||'');

async function renderDevice(arg,my){
  const devices=(API.meta&&API.meta.devices)||[];
  const id=Number(arg)||(devices.length?devices[0].id:0);
  let d;
  try{ d=await API.get('/api/device/'+id); }
  catch(e){
    if(my!==RENDER_SEQ) return;
    if(e&&e.status===404){ main.innerHTML='<h1>Device</h1><div class="notice">Unknown device</div>'; return; }
    throw e;   // 503 and the rest land in render()'s errorPanel
  }
  if(my!==RENDER_SEQ) return;
  COMPARE=COMPARE.filter(x=>x!==id);
  const S=await API.get('/api/device/'+id+'/series?range='+RANGE);
  if(my!==RENDER_SEQ) return;
  let cmp=[];
  if(COMPARE.length){
    cmp=(await Promise.all(COMPARE.map(async(cid,i)=>{
      try{ return {d:await API.get('/api/device/'+cid),S:await API.get('/api/device/'+cid+'/series?range='+RANGE),col:CMPCOL[i%CMPCOL.length]}; }
      catch(e){ return null; }
    }))).filter(Boolean);
    if(my!==RENDER_SEQ) return;
    COMPARE=cmp.map(k=>k.d.id);
  }

  const cap=d.capabilities||{};
  const caps=[cap.has_dimension?'dimension':null,cap.has_weight?'weight':null,cap.has_hand_scan?'hand scan':null].filter(Boolean);
  const drives=d.drives||[];
  const opts=devices.map(x=>'<option value="'+x.id+'"'+(x.id==id?' selected':'')+'>'+esc(x.customer+' · '+label(x))+'</option>').join('');
  let h='<div class="devhead"><div class="id"><h1>'+esc(label(d))+'</h1><div class="meta">'+esc(d.customer)+' · serial '+esc(d.serial_number||'–')+'</div><div class="meta">'+esc(caps.join(', '))+'</div></div>'
    +'<div class="kv"><span>State</span><b><span class="dot '+(STATE_DOT[d.state]||'off')+'"></span> '+esc(d.state||'–')+'</b><span>Last seen</span><b>'+(d.last_seen?ago(t(d.last_seen))+' ago':'never')+'</b>'
    +'<span>App</span><b>'+(d.application_running==null?'–':d.application_running?'running':'stopped')+'</b><span>Uptime</span><b>'+uptimeD(d.uptime_seconds)+'</b></div>'
    +'<div class="kv"><span>Drives</span><b>'+(drives.length?esc(drives.map(x=>x.drive+' '+numOr(x.usage_percent,'%')).join(', ')):'–')+'</b>'
    +'<span>CPU</span><b>'+numOr(d.cpu_percent,'%')+'</b><span>Memory</span><b>'+numOr(d.mem_usage_pct,'%')+'</b><span>Temperature</span><b>'+(d.temp_celsius==null?'–':numOr(d.temp_celsius)+' °C')+'</b></div>'
    +'<div class="kv"><span>OS</span><b>'+esc(d.os_version||'–')+'</b><span>Host history</span><b class="faint">starts when snapshots begin</b></div></div>';
  const cmpDevs=devices.filter(x=>x.id!==id);
  h+='<div class="toolrow"><select class="sel" id="devsel">'+opts+'</select>'
    +'<span class="seg" id="rng">'+['7d','30d','90d'].map(r=>'<button class="'+(r===RANGE?'on':'')+'" data-r="'+r+'">'+r+'</button>').join('')+'</span>'
    +'<span class="seg" id="rng2">'+['24h','48h'].map(r=>'<button class="'+(r===RANGE?'on':'')+'" data-r="'+r+'">'+r+' detail</button>').join('')+'</span>'
    +'<span class="cmp"><button class="btn" id="cmpbtn">Compare with…</button><div class="menu" id="cmpmenu" '+(CMP_OPEN?'':'hidden')+'>'
    +cmpDevs.map(x=>{ const on=COMPARE.includes(x.id); const col=on?CMPCOL[COMPARE.indexOf(x.id)%CMPCOL.length]:'';
        return '<label><input type="checkbox" data-id="'+x.id+'" '+(on?'checked':'')+'><span class="sw" style="background:'+(col||'var(--ink-3)')+'"></span>'+esc(x.customer+' · '+label(x))+'</label>'; }).join('')
    +'</div></span>'
    +cmp.map((k,i)=>'<span class="chip"><span class="sw" style="background:'+CMPCOL[i%CMPCOL.length]+'"></span>'+esc(label(k.d))+' <span class="faint">'+esc(k.d.customer)+'</span><button data-rm="'+k.d.id+'" title="Remove">×</button></span>').join('')
    +'<span class="hint">'+(S.style==='line'?'One point per day, in SAST.':'Bars per '+((RANGES[S.range]||{}).label||'bucket')+', in SAST.')+' Hover for the numbers.</span></div>';
  h+='<div id="devbody"></div>';
  main.innerHTML=h;
  document.getElementById('devsel').onchange=e=>{ COMPARE=[]; location.hash='device/'+e.target.value+'/'+RANGE; };
  main.querySelectorAll('#rng button,#rng2 button').forEach(b=>b.onclick=()=>{ RANGE=b.dataset.r; goDevice(id); });
  document.getElementById('cmpbtn').onclick=e=>{ e.stopPropagation(); CMP_OPEN=!CMP_OPEN; document.getElementById('cmpmenu').hidden=!CMP_OPEN; };
  document.getElementById('cmpmenu').onclick=e=>e.stopPropagation();
  main.querySelectorAll('#cmpmenu input').forEach(cb=>cb.onchange=()=>{ const v=Number(cb.dataset.id); if(cb.checked){ if(!COMPARE.includes(v)) COMPARE.push(v); } else COMPARE=COMPARE.filter(x=>x!==v); goDevice(id); });
  main.querySelectorAll('.chip button').forEach(b=>b.onclick=()=>{ COMPARE=COMPARE.filter(x=>x!==Number(b.dataset.rm)); goDevice(id); });
  document.addEventListener('click',()=>{ if(CMP_OPEN){ CMP_OPEN=false; const m=document.getElementById('cmpmenu'); if(m) m.hidden=true; } },{once:true});

  const body=document.getElementById('devbody');
  drawFigures(d,S,cmp,body);
  if(S.style==='line') drawHeat(d,S,body);
  let H;
  try{ H=await API.get('/api/device/'+id+'/health?range='+RANGE); }
  catch(e){   // the host history is its own request; a failure there must not blank the figures
    if(my!==RENDER_SEQ) return;
    const slot=document.getElementById('devhost');
    if(slot) slot.innerHTML='<div class="fig"><div class="pt"><b>Host history</b><span class="ptr">disk, memory, CPU, temperature, app restarts</span></div>'
      +'<div class="notice" style="padding:8px 4px 10px">Host history is unavailable. '+esc(e&&e.status?'Error '+e.status+': '+e.message:String(e&&e.message||e))+'</div></div>';
    return;
  }
  if(my!==RENDER_SEQ) return;
  const slot=document.getElementById('devhost');
  if(slot) drawHost(d,H,slot);
}

/* ---------- TRENDS lands in the next task ---------- */
async function renderTrends(){ main.innerHTML='<h1>Trends</h1><div class="notice">Coming in the next task</div>'; }

boot();
