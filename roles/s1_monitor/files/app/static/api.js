/* Shared helpers, API access, stale banner. Loaded before charts.js and app.js. */

/* ---------- api ---------- */
class ApiError extends Error { constructor(status, detail){ super(detail); this.name='ApiError'; this.status=status; } }
let NOW=new Date(), TZ=2, MIN_ITEMS=100, MIN_HOUR=30, MIN_RAW=15, GAP_MIN=11, STALE_DAYS=14;

const API = {
  meta:null,
  /* banner:false for background refreshes, so only the page's own loads move the stale banner */
  async get(path,{banner:useBanner=true}={}){
    const r=await fetch(path,{cache:'no-store'});
    let body=null; try{ body=await r.json(); }catch(e){}
    if(!r.ok) throw new ApiError(r.status,(body&&body.detail)||r.statusText);
    const banner=useBanner?document.getElementById('banner'):null;
    if(banner){
      if(body&&body.stale){ banner.textContent='Showing data from '+fmt(t(body.stale_since))+' SAST, database unreachable'; banner.classList.add('on'); }
      else banner.classList.remove('on');
    }
    return body;
  },
  async loadMeta(){
    API.meta=await API.get('/api/meta');
    NOW=new Date(API.meta.generated_utc);
    TZ=API.meta.tz_offset_hours;
    MIN_ITEMS=API.meta.min_items.day; MIN_HOUR=API.meta.min_items.hour; MIN_RAW=API.meta.min_items.half_hour;
    GAP_MIN=API.meta.offline_gap_minutes; STALE_DAYS=API.meta.stale_days;
  }
};

function errorPanel(el,err){ el.innerHTML='<div class="notice">'+esc(err&&err.status?'Error '+err.status+': '+err.message:String(err&&err.message||err))+'</div>'; }

/* ---------- config and thresholds, from /api/meta ---------- */
function cfg(cust){ return (API.meta&&API.meta.customers.find(c=>c.customer===cust))||{has_dimension:true,has_weight:false,has_hand_scan:false,hand_scan_warn_pct:15,no_weight_warn_pct:5,storage_warn_pct:80,storage_bad_pct:90,good_read_warn_pct:95,good_read_bad_pct:90,no_dim_warn_pct:5,no_dim_bad_pct:10}; }
function thr(deviceId,metric){ const r=((API.meta&&API.meta.thresholds[String(deviceId)])||{})[metric]; return r||{warn:null,bad:null,direction:'high',source:'none'}; }

/* ---------- helpers, unchanged from the approved demo ---------- */
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const C = {good:css('--good'),warn:css('--warn'),bad:css('--bad'),info:css('--info'),ink:css('--ink'),ink2:css('--ink-2'),ink3:css('--ink-3'),line:css('--line-2'),muted:css('--muted-mark'),panel:css('--panel')};
const CUSTCOL = {};
const t = s => new Date(s).getTime();
const sast = ms => ms + TZ*3600e3;           // shift epoch so UTC getters read SAST
const DAY = 86400e3;
const pad = n => String(n).padStart(2,'0');
const DOW=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'], MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function fmt(ms, mode){ const d=new Date(sast(ms));
  if(mode==='time') return pad(d.getUTCHours())+':'+pad(d.getUTCMinutes());
  if(mode==='day') return DOW[d.getUTCDay()]+' '+d.getUTCDate()+' '+MON[d.getUTCMonth()];
  if(mode==='date') return d.getUTCFullYear()+'-'+pad(d.getUTCMonth()+1)+'-'+pad(d.getUTCDate());
  return DOW[d.getUTCDay()]+' '+d.getUTCDate()+' '+MON[d.getUTCMonth()]+' '+pad(d.getUTCHours())+':'+pad(d.getUTCMinutes()); }
const fmtS = (shifted, mode) => fmt(shifted-TZ*3600e3, mode);   // for already-shifted axis values
function ago(ms){ const m=Math.max(0,Math.round((NOW-ms)/60000)); if(m<60) return m+' min'; const h=Math.floor(m/60); if(h<48) return h+' h '+(m%60)+' min'; return Math.floor(h/24)+' d'; }
const dur = m => m>=1440?Math.floor(m/1440)+' d '+Math.floor((m%1440)/60)+' h':m>=60?Math.floor(m/60)+' h '+(m%60)+' min':m+' min';
const num = n => n==null?'–':Number(n).toLocaleString('en-ZA');
const pct = (a,b) => b>0 ? 100*a/b : null;
const fpct = v => v==null?'–':v.toFixed(1)+'%';
const label = d => d.machine_name+' @ '+d.location;
const esc = s => String(s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const median = a => { const v=a.filter(x=>x!=null).sort((x,y)=>x-y); if(!v.length) return null; return v.length%2?v[(v.length-1)/2]:(v[v.length/2-1]+v[v.length/2])/2; };
const mean = a => { const v=a.filter(x=>x!=null); return v.length?v.reduce((s,x)=>s+x,0)/v.length:null; };
const STATE_DOT={online:'good',offline:'bad',stale:'off',never:'off'};
function sevColor(v, th, dir){ if(v==null||th.warn==null) return null; if(dir==='low'){ if(th.bad!=null&&v<th.bad) return 'bad'; if(v<th.warn) return 'warn'; return 'good'; } if(th.bad!=null&&v>th.bad) return 'bad'; if(v>th.warn) return 'warn'; return 'good'; }

function spark(vals, opts={}){ // inline svg sparkline, vals: [{y,low}]
  const w=opts.w||120,h=opts.h||24; const ys=vals.map(v=>v.y).filter(v=>v!=null); if(!ys.length) return '<svg class="spark" width="'+w+'" height="'+h+'"></svg>';
  const max=opts.max??Math.max(...ys,1), min=opts.min??0; const n=vals.length;
  const X=i=>(i/(n-1||1))*(w-2)+1, Y=v=>h-1-((Math.min(max,Math.max(min,v))-min)/(max-min||1))*(h-2);
  if(opts.bars){ const bw=Math.max(1,(w-2)/n-1); return '<svg class="spark" width="'+w+'" height="'+h+'">'+vals.map((v,i)=>v.y==null?'':'<rect x="'+(X(i)-bw/2)+'" y="'+Y(v.y)+'" width="'+bw+'" height="'+(h-1-Y(v.y))+'" fill="'+(opts.color||C.info)+'" opacity=".85"/>').join('')+'</svg>'; }
  let d='',prev=false; vals.forEach((v,i)=>{ if(v.y==null||v.low){prev=false;return;} d+=(prev?'L':'M')+X(i).toFixed(1)+' '+Y(v.y).toFixed(1)+' '; prev=true; });
  let lines=''; if(opts.warn!=null&&opts.warn>=min){ lines+='<line x1="1" x2="'+(w-1)+'" y1="'+Y(opts.warn)+'" y2="'+Y(opts.warn)+'" stroke="'+C.warn+'" stroke-width="1" stroke-dasharray="3 3" opacity=".8"/>'; }
  const dots=vals.map((v,i)=>v.y==null?'':v.low?'<circle cx="'+X(i)+'" cy="'+Y(v.y)+'" r="2" fill="'+C.panel+'" stroke="'+C.ink3+'"/>':(opts.dots?'<circle cx="'+X(i)+'" cy="'+Y(v.y)+'" r="1.6" fill="'+(opts.color||C.info)+'"/>':'')).join('');
  return '<svg class="spark" width="'+w+'" height="'+h+'">'+lines+'<path d="'+d+'" fill="none" stroke="'+(opts.color||C.info)+'" stroke-width="1.5" stroke-linejoin="round"/>'+dots+'</svg>';
}

/* ---------- image download ---------- */
const DL_ICON='<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
const slug = x => String(x).replace(/[^A-Za-z0-9]+/g,'-').replace(/^-|-$/g,'');
function stamp(){ const d=new Date(sast(NOW.getTime())); return d.getUTCFullYear()+pad(d.getUTCMonth()+1)+pad(d.getUTCDate())+'-'+pad(d.getUTCHours())+pad(d.getUTCMinutes()); }
/* meta: {title, sub, name:[parts...]} -> renders header text above the chart into one PNG */
function attachDownload(hostEl, chart, meta){
  if(!hostEl) return;
  const btn=document.createElement('button'); btn.className='dl'; btn.title='Download as image'; btn.innerHTML=DL_ICON;
  const slot=hostEl.querySelector('.ptr')||hostEl.querySelector('.pt')||hostEl.querySelector('.t'); (slot||hostEl).appendChild(btn);
  btn.onclick=e=>{ e.stopPropagation(); const pr=2; const src=chart.getDataURL({pixelRatio:pr,backgroundColor:C.panel});
    const img=new Image(); img.onload=()=>{ const head=(meta.sub?76:56)*pr, padx=16*pr; const cv=document.createElement('canvas'); cv.width=img.width; cv.height=img.height+head; const g=cv.getContext('2d');
      g.fillStyle=C.panel; g.fillRect(0,0,cv.width,cv.height); g.fillStyle=C.ink; g.font='600 '+(15*pr)+'px Inter, system-ui, sans-serif'; g.fillText(meta.title,padx,26*pr);
      g.fillStyle=C.ink2; g.font=(11*pr)+'px Inter, system-ui, sans-serif'; if(meta.sub) g.fillText(meta.sub,padx,46*pr);
      g.fillText('S1 Remote Monitoring · '+fmt(NOW.getTime())+' SAST',padx,(meta.sub?66:46)*pr);
      g.drawImage(img,0,head); const a=document.createElement('a'); a.download='S1_'+meta.name.map(slug).filter(Boolean).join('_')+'_'+stamp()+'.png'; a.href=cv.toDataURL('image/png'); a.click(); };
    img.src=src; };
}

/* ---------- echarts theme ---------- */
const AX = {axisLine:{lineStyle:{color:C.line}},axisTick:{show:false},axisLabel:{color:C.ink2,fontFamily:'Inter'},splitLine:{lineStyle:{color:css('--line')}}};
const TIP = {backgroundColor:'#1c232e',borderColor:'rgba(255,255,255,.1)',borderWidth:1,textStyle:{color:C.ink,fontFamily:'Inter',fontSize:12},padding:[8,10],extraCssText:'box-shadow:0 6px 20px rgba(0,0,0,.4)'};
const base = () => ({useUTC:true,animation:false,textStyle:{fontFamily:'Inter',color:C.ink2},tooltip:Object.assign({trigger:'axis',axisPointer:{type:'line',lineStyle:{color:C.ink3}}},TIP)});
const dashed = (y,color,text,pos) => ({yAxis:y,lineStyle:{color,type:'dashed',width:1.2},label:{show:!!text,position:pos||'insideEndTop',formatter:text,color,fontSize:11,fontFamily:'Inter'}});
