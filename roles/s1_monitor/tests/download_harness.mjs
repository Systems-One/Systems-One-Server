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
function el(tag){ const e={tag,className:'',title:'',style:{},children:[],appendChild(c){ this.children.push(c); },querySelector(){ return null; },click(){ calls.push({op:'click',download:this.download}); }};
  if(tag==='canvas'){ e.width=0; e.height=0; const g=ctx(); e.getContext=()=>g; e.toDataURL=()=>{ calls.push({op:'png',w:e.width,h:e.height}); return 'data:png'; }; }
  return e; }
const host = el('div');
class Image { set src(v){ this.width=meta.imgW; this.height=meta.imgH; this.onload&&this.onload(); } }
const sandbox = { document:{documentElement:{}, getElementById:()=>null, createElement:el}, getComputedStyle:()=>({getPropertyValue:()=>'#123456'}), Image, console, Date, Math, JSON };
sandbox.window = sandbox; vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(apiPath,'utf8')+'\n;globalThis.__attach=attachDownload;', sandbox);
sandbox.__attach(host, {getDataURL:()=>'data:chart'}, meta);
const btn = host.children[0]; btn.onclick({stopPropagation(){}});
process.stdout.write(JSON.stringify(calls));
