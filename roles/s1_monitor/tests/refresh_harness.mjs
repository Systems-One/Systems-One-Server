// Loads api.js, charts.js and app.js into a stub DOM and drives render() with a controllable API.
// Prints what happened as JSON. Used by test_refresh_no_flicker.py.
import fs from 'node:fs'; import vm from 'node:vm';
const dir = process.argv[2];
let disposed = 0;
const main = {innerHTML:'', querySelectorAll(){ return []; }};
const els = {main};
const stub = () => ({innerHTML:'', textContent:'', hidden:false, className:'', style:{}, classList:{add(){},remove(){},toggle(){}}, querySelectorAll(){ return []; }, closest(){ return null; }});
const sandbox = {
  document:{documentElement:{}, hidden:false, getElementById:id=>els[id]||(els[id]=stub()), querySelectorAll:()=>[], addEventListener(){}, createElement:()=>stub()},
  getComputedStyle:()=>({getPropertyValue:()=>'#123456'}),
  echarts:{init:()=>({setOption(){}, dispose(){ disposed++; }, resize(){}, isDisposed:()=>false, getDataURL:()=>'', on(){}})},
  location:{hash:'#fleet'}, fetch:()=>Promise.reject(new Error('no network')),
  setInterval(){}, console, Date, Math, JSON, Promise, Number, String, Array, Object, Set,
  scrollY:0, scrolls:[], addEventListener(){}, scrollTo(x,y){ this.scrolls.push(y); },
};
sandbox.window = sandbox; vm.createContext(sandbox);
for (const f of ['api.js','charts.js','app.js']) vm.runInContext(fs.readFileSync(dir+'/'+f,'utf8'), sandbox, {filename:f});
const tick = () => new Promise(r => setTimeout(r, 10));
await tick();   // let boot() fail harmlessly on the missing network
vm.runInContext(`API.meta={customers:[],devices:[],thresholds:{},min_items:{day:1,hour:1,half_hour:1},offline_gap_minutes:11,stale_days:14,tz_offset_hours:2,generated_utc:'2026-10-30T06:00:00Z'};`, sandbox);
const payload = {generated_utc:'2026-10-30T06:00:00Z', devices:[], strip:{}, attention:[]};
let pending = null;
sandbox.__get = () => pending ? pending.promise : Promise.resolve(payload);
vm.runInContext('API.get=(...a)=>__get(...a)', sandbox);
const deferred = () => { const d = {}; d.promise = new Promise((res, rej) => { d.resolve = res; d.reject = rej; }); return d; };
const R = {};

await vm.runInContext('render()', sandbox); await tick();
R.first_len = main.innerHTML.length;
vm.runInContext('charts.push(echarts.init({}))', sandbox);   // a live chart on the current page
disposed = 0; const before = main.innerHTML;

// background poll while the fetch is pending
pending = deferred(); sandbox.scrollY = 321; sandbox.scrolls.length = 0;
const p = vm.runInContext('render({bg:true})', sandbox); await tick();
R.pending_unchanged = main.innerHTML === before;
R.pending_disposed = disposed;
pending.resolve(Object.assign({}, payload, {devices:[], strip:{online:7, total:7}})); await p; await tick();
R.resolved_changed = main.innerHTML !== before && main.innerHTML.length > 0;
R.resolved_disposed = disposed;
R.scrolls_after_poll = sandbox.scrolls.slice();
R.scroll_y_restored = sandbox.scrolls.length ? sandbox.scrolls[sandbox.scrolls.length-1] : null;
const good = main.innerHTML;

// background poll that fails
pending = deferred();
const p2 = vm.runInContext('render({bg:true})', sandbox); await tick();
pending.reject(new Error('boom')); await p2; await tick();
R.failed_bg_kept_page = main.innerHTML === good;

// a user-initiated render that fails still shows the error panel
pending = deferred();
const p3 = vm.runInContext('render()', sandbox); await tick();
pending.reject(new Error('boom')); await p3; await tick();
R.failed_user_shows_error = main.innerHTML !== good;
process.stdout.write(JSON.stringify(R));
