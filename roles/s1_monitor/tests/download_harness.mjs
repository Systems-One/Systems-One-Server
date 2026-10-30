// Loads static/api.js in a stub DOM, clicks the download button once and prints
// what was drawn on the export canvas as JSON. Used by test_download_image.py.
import fs from 'node:fs'; import vm from 'node:vm';
const [apiPath, metaJson] = process.argv.slice(2);
const meta = JSON.parse(metaJson);
const calls = [];
// text width model: 0.55em per character, so the harness is independent of any font.
const px = f => parseFloat((f.match(/(\d+(?:\.\d+)?)px/) || [0, 0])[1]);
function ctx(){ return {font:'', fillStyle:'', textAlign:'left', fillRect(){}, measureText(s){ return {width:String(s).length*px(this.font)*0.55}; },
  fillText(s,x,y){ calls.push({op:'text',s:String(s),x,y,font:this.font,fill:this.fillStyle}); },
  drawImage(img,x,y){ calls.push({op:'img',x,y,w:img.width,h:img.height}); } }; }
function el(tag){ const e={tag,className:'',title:'',style:{},children:[],appendChild(c){ this.children.push(c); },querySelector(){ return null; },click(){ calls.push({op:'click',download:this.download,href:String(this.href||'').slice(0,5)}); }};
  if(tag==='canvas'){ e.width=0; e.height=0; const g=ctx(); e.getContext=()=>g; e.toDataURL=()=>{ calls.push({op:'png',w:e.width,h:e.height}); return el.__png; }; }
  return e; }
const host = el('div');
// delivery: meta.ua picks the browser, meta.canShare says whether the Web Share API accepts files
const navigator = { userAgent: meta.ua || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130', platform: meta.platform || 'Win32', maxTouchPoints: meta.touch || 0,
  canShare: meta.canShare ? (d => !!(d && d.files && d.files.length)) : undefined,
  share: d => { calls.push({op:'share', files:d.files.length, name:d.files[0].name, type:d.files[0].type, title:d.title}); return Promise.resolve(); } };
const URLx = { createObjectURL: f => { calls.push({op:'objecturl', name:f.name, type:f.type, size:f.size}); return 'blob:fake'; }, revokeObjectURL(){} };
const sandbox = { document:{documentElement:{}, getElementById:()=>null, createElement:el}, getComputedStyle:()=>({getPropertyValue:()=>'#123456'}), console, Date, Math, JSON,
  navigator, URL: URLx, File, Blob, Uint8Array, atob, setTimeout: ()=>0 /* the real one would keep node alive for the blob-URL cleanup */ };
sandbox.window = sandbox; vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(apiPath,'utf8')+';globalThis.__attach=attachDownload;', sandbox);
// a 1x1 transparent PNG, so the base64 to File path has real bytes to chew on
el.__png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
sandbox.__attach(host, {renderToCanvas:()=>({width:meta.imgW,height:meta.imgH})}, meta);
const btn = host.children[0]; btn.onclick({stopPropagation(){}});
process.stdout.write(JSON.stringify(calls));
