/* ECharts builders for the device page. Loaded after api.js and before app.js.
   Everything here reads the server's already-bucketed payloads; nothing is re-aggregated on the client. */

const RANGES={'24h':{hours:24,bucket:30*60e3,label:'30 min'},'48h':{hours:48,bucket:3600e3,label:'hour'},'7d':{days:7},'30d':{days:30},'90d':{days:90}};
const CMPCOL=['#d95926','#199e70','#c98500','#d55181','#9085e9','#e66767'];   // categorical slots 2..7, primary device keeps blue
const SLICE_COL={'Good read':'rgba(57,135,229,.35)','No read, recovered by hand scan':'#d55181','No read, not recovered':'#e66767','No read':'#e66767'};

/* the server's buckets[] in the shape the figures want: shifted x, flattened rates, window edges */
function mkB(S){
  const step=S.bucket_seconds*1000;
  const list=(S.buckets||[]).map(b=>Object.assign({},b,b.rates||{},{x:sast(t(b.ts)),multi:b.more_than_1_item}));
  const map=new Map(list.map(b=>[b.x,b]));
  return {list,map,from:sast(t(S.from)),to:sast(t(S.to))-step,step,minItems:S.min_items,daily:S.style==='line'};
}
/* thresholds travel with the device payload; coerce so fpct/toFixed never see a string */
function dthr(d,key){
  const r=d&&d.thresholds&&d.thresholds[key];
  if(!r) return {warn:null,bad:null,direction:'high',source:'none',baseline_samples:null};
  return Object.assign({},r,{warn:r.warn==null?null:Number(r.warn),bad:r.bad==null?null:Number(r.bad)});
}

/* ---------- the device figures: summary, doughnut, items, good read, other rates ---------- */
function drawFigures(d,S,cmp,host){
  const B=mkB(S); const RG=S.range; const R=RANGES[RG]||{days:1};
  const rates=S.applicable_rates||[]; const th=dthr(d,'good_read_pct');
  const cmpB=(cmp||[]).map(k=>({d:k.d,B:mkB(k.S),col:k.col}));
  const withData=B.list.filter(x=>!x.nodata);
  const sum=S.summary||{};
  const stat=(o,f)=>['max','min','avg'].map(k=>(o&&o[k]!=null)?f(Number(o[k])):'–');
  const sI=stat(sum.items,v=>num(Math.round(v))), sG=stat(sum.good_read_pct,v=>v.toFixed(1)+'%'), sH=stat(sum.per_unit,v=>num(Math.round(v)));
  const outages=S.outages||[];
  const unit=B.daily?'day':R.label;
  const perLabel=(sum.per_unit&&sum.per_unit.label)||(B.daily?'hour':'packet');
  const unitCol='Items per '+perLabel;
  const tot=S.totals||{items:0};
  // doughnut is a true partition: good read + no read. Hand scan splits the no-read slice where the customer has it.
  const slices=(S.partition||[]).map(p=>({name:p.name,value:p.value,col:SLICE_COL[p.name]||C.ink3}));
  const notMeasured=S.not_measured||[];
  const cap=d.capabilities||{};
  const flags=[cap.has_dimension?{k:'no_dimension',name:'No dimension',col:'#d95926'}:null,cap.has_weight?{k:'no_weight',name:'No weight',col:'#c98500'}:null,
    {k:'not_sent',name:'Not sent',col:'#9085e9'},cap.has_dimension?{k:'more_than_1_item',name:'More than 1 item',col:'#199e70'}:null].filter(Boolean);
  const rangeName=B.daily?R.days+' days':R.hours+' hours';
  let h='<div class="sumgrid"><div class="fig"><div class="pt"><b>Summary, last '+rangeName+'</b><span>'+withData.length+' '+unit+'s with data'+(B.list.length-withData.length?', '+(B.list.length-withData.length)+' with none':'')+'</span></div>'
    +'<table class="wow summary"><thead><tr><th></th><th class="r">Items per '+unit+'</th><th class="r">Good read %</th><th class="r">'+unitCol+'</th></tr></thead><tbody>'
    +'<tr><td>Maximum</td><td class="r tnum">'+sI[0]+'</td><td class="r tnum">'+sG[0]+'</td><td class="r tnum">'+sH[0]+'</td></tr>'
    +'<tr><td>Minimum</td><td class="r tnum">'+sI[1]+'</td><td class="r tnum">'+sG[1]+'</td><td class="r tnum">'+sH[1]+'</td></tr>'
    +'<tr><td>Average</td><td class="r tnum">'+sI[2]+'</td><td class="r tnum">'+sG[2]+'</td><td class="r tnum">'+sH[2]+'</td></tr></tbody></table>'
    +'<div class="notes"><div><b>'+outages.length+'</b> outages over '+GAP_MIN+' min'+(outages.length?', longest '+dur(Math.max.apply(null,outages.map(o=>o.minutes))):'')+'</div>'
    +'<div>Good read limits: warn <b>'+fpct(th.warn)+'</b>, bad <b>'+fpct(th.bad)+'</b> <span class="faint">('+esc(th.source||'none')+(th.baseline_samples?', '+th.baseline_samples+' samples':'')+')</span></div>'
    +'<div class="faint">Good read statistics use '+unit+'s with at least '+B.minItems+' items. '+(B.daily?'Items per hour uses hours with at least one item.':'Items per packet uses 5-minute packets with at least one item.')+'</div></div></div>'
    +'<div class="fig" id="figDonutBox"><div class="pt"><b>Errors, last '+rangeName+'</b><span class="ptr">'+num(tot.items||0)+' items</span></div><div class="donutwrap"><div class="c" id="figDonut"></div><table class="legend"><tbody>'
    +slices.map(k=>'<tr><td><span class="sw" style="background:'+k.col+'"></span>'+esc(k.name)+'</td><td class="r tnum">'+num(k.value)+'</td><td class="r tnum"><b>'+fpct(pct(k.value,tot.items||0))+'</b></td></tr>').join('')
    +'<tr><td colspan="3" class="faint" style="padding-top:10px">Also flagged, can overlap with the above</td></tr>'
    +flags.map(k=>'<tr><td><span class="sw" style="background:'+k.col+'"></span>'+k.name+'</td><td class="r tnum">'+num(tot[k.k]||0)+'</td><td class="r tnum">'+fpct(pct(tot[k.k]||0,tot.items||0))+'</td></tr>').join('')
    +'</tbody></table></div>'+(notMeasured.length?'<div class="faint" style="padding:6px 4px 2px">Not measured on this machine: '+esc(notMeasured.join(', '))+'.</div>':'')+'</div></div>';
  const rangeLabel=B.daily?'Daily':'Per '+R.label;
  h+='<div class="fig" id="figItemsBox"><div class="pt"><b>'+rangeLabel+' total items</b><span class="ptr">'+(B.daily?'weekends shaded':'grey bars: no data received')+'</span></div><div class="c" id="figItems" style="height:280px"></div></div>';
  h+='<div class="fig" id="figGRBox"><div class="pt"><b>'+rangeLabel+' good read %</b><span class="ptr">'+(B.daily?'hollow point':'hollow bar')+': under '+B.minItems+' items in that '+unit+'</span></div><div class="c" id="figGR" style="height:280px"></div></div>';
  const others=rates.filter(r=>r.key!=='good_read_pct');
  h+='<div class="grid3">'+others.map(r=>'<div class="fig" id="fig_'+r.key+'Box"><div class="pt"><b>'+rangeLabel+' '+esc(r.name.toLowerCase())+' %</b><span class="ptr"></span></div><div class="c" id="fig_'+r.key+'" style="height:200px"></div></div>').join('')+'</div>';
  if(B.daily){ const rowH=R.days<=7?30:20; h+='<div class="fig" id="figHeatBox"><div class="pt"><b>Throughput heatmap</b><select class="sel" id="heatsel" style="margin-left:12px;padding:3px 8px"></select><span class="ptr">date by hour of day. Red cells: no data received in that hour. Empty: online but idle.</span></div><div class="c" id="figHeat" style="height:'+(B.list.length*rowH+70)+'px"></div></div>'; }
  h+='<div class="grid2"><div><h2>Outages in range<small>gaps over '+GAP_MIN+' minutes between packets</small></h2><table class="wow"><thead><tr><th>Started</th><th>Ended</th><th class="r">Duration</th></tr></thead><tbody>'
    +(outages.length?outages.slice().reverse().map(o=>'<tr><td>'+fmt(t(o.start))+'</td><td>'+(o.open?'still silent':fmt(t(o.end)))+'</td><td class="r tnum">'+dur(o.minutes)+'</td></tr>').join(''):'<tr><td colspan="3" style="color:var(--ink-2)">No outages in this range.</td></tr>')
    +'</tbody></table></div><div id="devhost"></div></div>';
  host.innerHTML=h;

  // doughnut
  const cd=echarts.init(document.getElementById('figDonut')); charts.push(cd);
  const who=[d.customer,d.location,d.machine_name];
  attachDownload(document.getElementById('figDonutBox'),cd,{title:label(d)+' · Errors, last '+rangeName,sub:d.customer+' · '+num(tot.items||0)+' items',name:who.concat(['errors',RG])});
  cd.setOption({animation:false,tooltip:Object.assign({trigger:'item',formatter:p=>'<b>'+num(p.value)+'</b> '+p.name+'<br>'+fpct(pct(p.value,tot.items||0))+' of items'},TIP),
    series:[{type:'pie',radius:['58%','82%'],center:['50%','50%'],label:{show:false},itemStyle:{borderColor:C.panel,borderWidth:2},data:slices.map(k=>({name:k.name,value:k.value,itemStyle:{color:k.col}}))}],
    graphic:[{type:'text',left:'center',top:'40%',style:{text:fpct(pct(tot.good_read||0,tot.items||0)),fill:C.ink,fontSize:22,fontWeight:600,fontFamily:'Inter',textAlign:'center'}},{type:'text',left:'center',top:'56%',style:{text:'good read',fill:C.ink2,fontSize:12,fontFamily:'Inter',textAlign:'center'}}]});

  // shared x axis
  const xfmt=v=>B.daily?(R.days<=7?fmtS(v,'day'):(function(){const dd=new Date(v);return dd.getUTCDate()+' '+MON[dd.getUTCMonth()];})()):fmtS(v,'time');
  const xAxis={type:'time',min:B.from-B.step/2,max:B.to+B.step/2,axisLabel:{color:C.ink2,hideOverlap:true,formatter:xfmt},axisLine:{lineStyle:{color:C.line}},axisTick:{show:false},splitLine:{show:false}};
  const weekends=B.daily?B.list.filter(x=>[0,6].includes(new Date(x.x).getUTCDay())).map(x=>[{xAxis:x.x-DAY/2},{xAxis:x.x+DAY/2}]):[];
  const nodataAreas=B.daily?[]:B.list.filter(x=>x.nodata).map(x=>[{xAxis:x.x-B.step/2},{xAxis:x.x+B.step/2}]);
  const markAreas={silent:true,itemStyle:{color:B.daily?'rgba(255,255,255,.035)':'rgba(255,255,255,.06)'},data:B.daily?weekends:nodataAreas};
  const lineStyle=(col,size)=>({type:'line',symbol:'circle',symbolSize:size||7,showSymbol:true,lineStyle:{width:1.5,color:col},itemStyle:{color:col,borderColor:C.panel,borderWidth:1.5}});
  const barStyle=col=>({type:'bar',barMaxWidth:24,barCategoryGap:'25%',itemStyle:{color:col,borderRadius:[3,3,0,0]}});
  const tipAt=(fmtv)=>({trigger:'axis',formatter:ps=>{ if(!ps.length) return ''; const x=ps[0].value[0]; let s='<div style="color:'+C.ink2+'">'+(B.daily?fmtS(x,'day'):fmtS(x)+' to '+fmtS(x+B.step,'time'))+'</div>'; const seen=new Set();
    for(const p of ps){ if(seen.has(p.seriesName)) continue; seen.add(p.seriesName); const m=cmpB.find(k=>label(k.d)===p.seriesName); const src=p.seriesName===label(d)?B:(m&&m.B); const dd=src&&src.map.get(x);
      s+='<div><span style="display:inline-block;width:10px;border-top:2px solid '+p.color+';margin-right:6px;vertical-align:middle"></span><b>'+(dd&&!dd.nodata?fmtv(dd):'no data')+'</b> <span style="color:'+C.ink2+'">'+esc(p.seriesName)+'</span></div>'; }
    return s; }});
  const seriesFor=(valFn,primaryCol,lowHollow)=>{
    const out=[]; const all=[{d,B,col:primaryCol,primary:true}].concat(cmpB);
    for(const k of all){ const pts=k.B.list.map(x=>({x:x.x,v:x.nodata?null:valFn(x),low:!x.nodata&&x.low_volume}));
      const st=B.daily?lineStyle(k.col,k.primary?7:5):barStyle(k.col);
      out.push(Object.assign({name:label(k.d),data:pts.map(p=>[p.x,(lowHollow&&p.low)?null:p.v])},st,k.primary?{markArea:markAreas}:{},B.daily?{}:{barGap:'10%'}));
      if(lowHollow) out.push({name:label(k.d),type:B.daily?'scatter':'bar',data:pts.filter(p=>p.low&&p.v!=null).map(p=>[p.x,p.v]),symbolSize:k.primary?7:5,barMaxWidth:24,barCategoryGap:'25%',itemStyle:{color:B.daily?C.panel:'transparent',borderColor:k.primary?C.ink3:k.col,borderWidth:1.5,borderRadius:[3,3,0,0]},tooltip:{show:false}});
    }
    return out;
  };
  const legend=cmpB.length?{legend:{top:0,right:8,textStyle:{color:C.ink2,fontFamily:'Inter'},icon:B.daily?'circle':'rect',itemWidth:10,itemHeight:10,data:[label(d)].concat(cmpB.map(k=>label(k.d)))}}:{};
  const cmpSub=cmpB.length?' · compared with '+cmpB.map(k=>label(k.d)).join(', '):'';
  // items
  const avgI=sum.items&&sum.items.avg!=null?Number(sum.items.avg):null;
  const c1=echarts.init(document.getElementById('figItems')); charts.push(c1);
  attachDownload(document.getElementById('figItemsBox'),c1,{title:label(d)+' · '+rangeLabel+' total items, last '+rangeName,sub:d.customer+cmpSub,name:who.concat(['total-items',RG])});
  const sItems=seriesFor(x=>x.items,C.info,false); sItems[0].markLine={silent:true,symbol:'none',animation:false,data:avgI!=null?[dashed(avgI,C.bad,'Average '+num(Math.round(avgI)),'insideStartTop')]:[]};
  c1.setOption(Object.assign(base(),legend,{grid:{left:60,right:20,top:cmpB.length?30:16,bottom:30},xAxis,yAxis:Object.assign({},AX,{type:'value',min:0,axisLabel:{color:C.ink2,formatter:v=>v>=1000?(v/1000)+'k':v}}),tooltip:Object.assign(tipAt(dd=>num(dd.items)+' items'),TIP),series:sItems}));
  // good read. Every percentage axis is fixed 0 to 100.
  const avgG=sum.good_read_pct&&sum.good_read_pct.avg!=null?Number(sum.good_read_pct.avg):null; const ymin=0;
  const c2=echarts.init(document.getElementById('figGR')); charts.push(c2);
  attachDownload(document.getElementById('figGRBox'),c2,{title:label(d)+' · '+rangeLabel+' good read %, last '+rangeName,sub:d.customer+' · warn '+fpct(th.warn)+', bad '+fpct(th.bad)+cmpSub,name:who.concat(['good-read',RG])});
  const sGR=seriesFor(x=>x.good_read_pct,C.info,true);
  sGR[0].markLine={silent:true,symbol:'none',animation:false,data:[avgG!=null?dashed(avgG,C.ink2,'Average '+avgG.toFixed(1)+'%','insideEndTop'):null, th.warn!=null&&th.warn>=ymin?dashed(th.warn,C.warn,'Warn '+th.warn.toFixed(1)+'%','insideStartTop'):null, th.bad!=null&&th.bad>=ymin?dashed(th.bad,C.bad,'Bad '+th.bad.toFixed(1)+'%','insideStartBottom'):null].filter(Boolean)};
  c2.setOption(Object.assign(base(),legend,{grid:{left:60,right:20,top:cmpB.length?30:16,bottom:30},xAxis,yAxis:Object.assign({},AX,{type:'value',min:0,max:100,interval:20,axisLabel:{color:C.ink2,formatter:v=>v+'%'}}),tooltip:Object.assign(tipAt(dd=>dd.items>0?fpct(dd.good_read_pct)+' good read'+(dd.low_volume?' (under '+B.minItems+' items)':''):'no items'),TIP),series:sGR}));
  // other rates
  for(const r of others){
    const tr=dthr(d,r.key); const ymax=100;
    const avg=mean(withData.filter(x=>!x.low_volume).map(x=>x[r.key]));
    const el=echarts.init(document.getElementById('fig_'+r.key)); charts.push(el);
    attachDownload(document.getElementById('fig_'+r.key+'Box'),el,{title:label(d)+' · '+rangeLabel+' '+r.name.toLowerCase()+' %, last '+rangeName,sub:d.customer,name:who.concat([r.name,RG])});
    const sR=seriesFor(x=>x[r.key],C.info,true);
    sR[0].markLine={silent:true,symbol:'none',animation:false,data:[avg!=null?dashed(avg,C.ink2,'Avg '+avg.toFixed(1)+'%'):null,tr.warn!=null&&tr.warn<=ymax?dashed(tr.warn,C.warn,'Warn '+tr.warn.toFixed(1)+'%','insideStartTop'):null,tr.bad!=null&&tr.bad<=ymax?dashed(tr.bad,C.bad,'Bad '+tr.bad.toFixed(1)+'%','insideStartBottom'):null].filter(Boolean)};
    el.setOption(Object.assign(base(),{grid:{left:44,right:14,top:14,bottom:28},xAxis:Object.assign({},xAxis,{axisLabel:Object.assign({},xAxis.axisLabel,{fontSize:10})}),yAxis:Object.assign({},AX,{type:'value',min:0,max:100,interval:25,axisLabel:{color:C.ink2,fontSize:10,formatter:v=>v+'%'}}),tooltip:Object.assign(tipAt(dd=>dd.items>0?fpct(dd[r.key])+' '+r.name.toLowerCase():'no items'),TIP),series:sR}));
  }
}

/* ---------- heatmap with selectable metric, daily ranges only ---------- */
let HEAT_METRIC='items', HEAT_CHART=null;
const HEAT_METRICS=c=>[{k:'items',name:'Items per hour'},{k:'good_read_pct',name:'Good read %'},{k:'no_read_pct',name:'No read %'},
  c.has_dimension?{k:'no_dim_pct',name:'No dimension %'}:null,c.has_hand_scan?{k:'hand_scan_pct',name:'Hand scanned %'}:null,c.has_weight?{k:'no_weight_pct',name:'No weight %'}:null,{k:'not_sent_pct',name:'Not sent %'}].filter(Boolean);
function drawHeat(d,S,host){
  const el=(host||document).querySelector('#figHeat'); if(!el) return;
  const cap=d.capabilities||{}; const RG=S.range; const R=RANGES[RG]||{days:1};
  const metrics=HEAT_METRICS(cap); if(!metrics.find(m=>m.k===HEAT_METRIC)) HEAT_METRIC='items';
  const m=metrics.find(x=>x.k===HEAT_METRIC); const isPct=HEAT_METRIC!=='items';
  const sel=(host||document).querySelector('#heatsel');
  if(sel){ sel.innerHTML=metrics.map(x=>'<option value="'+x.k+'"'+(x.k===HEAT_METRIC?' selected':'')+'>'+x.name+'</option>').join('');
    sel.onchange=()=>{ HEAT_METRIC=sel.value; if(HEAT_CHART){ HEAT_CHART.dispose(); const i=charts.indexOf(HEAT_CHART); if(i>=0) charts.splice(i,1); }
      const btn=(host||document).querySelector('#figHeatBox .dl'); if(btn) btn.remove(); drawHeat(d,S,host); }; }
  const dates=(S.buckets||[]).map(b=>sast(t(b.ts)));
  const hourMap=new Map((S.hourly||[]).map(r=>[sast(t(r.ts)),r]));
  const nowS=sast(NOW.getTime());
  const cells=[], nodata=[]; let maxV=1;
  dates.forEach((dk,di)=>{ for(let hh=0;hh<24;hh++){ const key=dk+hh*3600e3; const r=hourMap.get(key);
    if(r&&!r.nodata){ if(isPct){ if(r.items>0) cells.push([hh,di,Number(r.rates[m.k]||0),r.items]); } else { cells.push([hh,di,r.items,r.items]); maxV=Math.max(maxV,r.items); } }
    else if(key<nowS) nodata.push([hh,di,1]); } });
  const c4=echarts.init(el); charts.push(c4); HEAT_CHART=c4;
  const vmax=isPct?100:maxV;
  c4.setOption({useUTC:true,animation:false,textStyle:{fontFamily:'Inter'},grid:{left:96,right:70,top:26,bottom:8},
    xAxis:{type:'category',position:'top',data:[...Array(24).keys()].map(x=>pad(x)+':00'),axisLabel:{color:C.ink2,fontSize:10,interval:0},axisLine:{show:false},axisTick:{show:false}},
    yAxis:{type:'category',data:dates.map(x=>fmtS(x,R.days<=7?'day':'date')),inverse:true,axisLabel:{color:C.ink2,fontSize:10,interval:0},axisLine:{show:false},axisTick:{show:false}},
    visualMap:{seriesIndex:0,min:0,max:vmax,calculable:false,orient:'vertical',right:8,top:26,itemHeight:140,textStyle:{color:C.ink2,fontSize:10},inRange:{color:['#1c2533','#1c3a66','#1c5cab','#2a78d6','#3987e5','#5598e7','#86b6ef']},text:[isPct?'100%':num(maxV),'0']},
    tooltip:Object.assign({trigger:'item',formatter:p=>{ if(p.seriesName==='nodata') return '<b>No data received</b><br>'+fmtS(dates[p.value[1]],'day')+' '+pad(p.value[0])+':00';
      return '<b>'+(isPct?p.value[2].toFixed(1)+'% '+m.name.replace(' %','').toLowerCase():num(p.value[2])+' items')+'</b>'+(isPct?'<br>'+num(p.value[3])+' items'+(p.value[3]<MIN_HOUR?' (under '+MIN_HOUR+', rate not trusted)':''):'')+'<br>'+fmtS(dates[p.value[1]],'day')+' '+pad(p.value[0])+':00 to '+pad(p.value[0]+1)+':00';}},TIP),
    series:[{name:'v',type:'heatmap',data:cells,label:{show:true,fontSize:10,fontFamily:'Inter',color:C.ink,formatter:p=>isPct?(p.value[3]<MIN_HOUR?'':Math.round(p.value[2])):(p.value[2]>0?p.value[2]:'')},itemStyle:{borderColor:C.panel,borderWidth:1},emphasis:{itemStyle:{borderColor:C.ink,borderWidth:1}}},
      {name:'nodata',type:'heatmap',data:nodata,itemStyle:{color:'rgba(208,59,59,.45)',borderColor:C.panel,borderWidth:1},label:{show:false}}]});
  attachDownload((host||document).querySelector('#figHeatBox'),c4,{title:label(d)+' · '+m.name+' heatmap, last '+R.days+' days',sub:d.customer+' · date by hour of day'+(isPct?' · hours under '+MIN_HOUR+' items left blank':''),name:[d.customer,d.location,d.machine_name,m.name+' heatmap',RG]});
}

/* ---------- host history: disk, memory, CPU, temperature and the app/reboot markers ---------- */
function drawHost(d,H,host){
  const box=document.createElement('div'); box.className='fig'; box.id='figHostBox';
  if(!H.rows.length){ box.innerHTML='<div class="pt"><b>Host history</b><span class="ptr">disk, memory, CPU, temperature, app restarts</span></div><div class="notice" style="padding:8px 4px 10px">'+(H.history_since?'No snapshots in this range. History starts '+fmt(t(H.history_since),'day')+'.':'Fills in from the day the site starts recording snapshots. Nothing before that exists in the database.')+'</div>'; host.appendChild(box); return; }
  box.innerHTML='<div class="pt"><b>Host history</b><span class="ptr">C: drive, memory, CPU, temperature · markers: app stop/start, reboot</span></div><div class="c" id="figHost" style="height:260px"></div>';
  host.appendChild(box);
  const ch=echarts.init(document.getElementById('figHost')); charts.push(ch);
  const xs=H.rows.map(r=>sast(t(r.ts)));
  const series=[['c_usage_percent','C: drive %',C.info],['mem_usage_pct','Memory %','#199e70'],['cpu_percent','CPU %','#c98500'],['temp_celsius','Temperature °C','#d55181']]
    .map(([k,name,col])=>({name,type:'line',data:H.rows.map((r,i)=>[xs[i],r[k]]),symbol:'none',lineStyle:{width:1.5,color:col},itemStyle:{color:col}}));
  const marks=(H.events||[]).map(e=>({xAxis:sast(t(e.ts)),lineStyle:{color:e.kind==='app_stopped'?C.bad:e.kind==='uptime_reset'?C.warn:C.ink3,type:'dashed',width:1},label:{show:true,formatter:e.kind.replace('_',' '),color:C.ink2,fontSize:10,position:'insideEndTop'}}));
  series[0].markLine={silent:true,symbol:'none',animation:false,data:marks};
  const lim=d.storage_limits||{};
  if(lim.warn) series[0].markLine.data.push(dashed(Number(lim.warn),C.warn,'C: warn '+lim.warn+'%','insideStartTop'));
  if(lim.bad) series[0].markLine.data.push(dashed(Number(lim.bad),C.bad,'C: bad '+lim.bad+'%','insideStartBottom'));
  ch.setOption(Object.assign(base(),{legend:{top:0,right:8,textStyle:{color:C.ink2,fontFamily:'Inter'},icon:'rect',itemWidth:10,itemHeight:10},
    grid:{left:60,right:20,top:30,bottom:30},
    xAxis:{type:'time',min:xs[0],max:xs[xs.length-1],axisLabel:{color:C.ink2,hideOverlap:true,formatter:v=>fmtS(v)},axisLine:{lineStyle:{color:C.line}},axisTick:{show:false},splitLine:{show:false}},
    yAxis:Object.assign({},AX,{type:'value',min:0,max:100,interval:20,axisLabel:{color:C.ink2}}),
    tooltip:Object.assign({trigger:'axis',formatter:ps=>'<div style="color:'+C.ink2+'">'+fmtS(ps[0].value[0])+'</div>'+ps.map(p=>'<div><b>'+(p.value[1]==null?'–':p.value[1])+'</b> <span style="color:'+C.ink2+'">'+p.seriesName+'</span></div>').join('')},TIP),
    series}));
  attachDownload(box,ch,{title:label(d)+' · Host history, last '+RANGE,sub:d.customer,name:[d.customer,d.location,d.machine_name,'host-history',RANGE]});
}
