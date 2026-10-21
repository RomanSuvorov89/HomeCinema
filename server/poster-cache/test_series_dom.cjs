// Native Lampa classes and render event shape from yumata/lampa-source torrent.js,
// templates/torrent/serial.js, explorer.js and components/full.js.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const events={},timers=[],live=new Set(),requests=[];
const movie={id:85552,kinopoisk_id:'1178445',name:'Эйфория',original_name:'Euphoria'};
function image(kind,src){
 const attrs={src};
 const node={nodeType:1,naturalWidth:0,style:{},classList:{contains:()=>false},
  matches:s=>kind==='torrent'?s.includes('img.torrent-serial__img'):kind==='explorer'?s.includes('explorer-card__head-img'):s.includes('img.full-start__background'),
  querySelectorAll:()=>[],getAttribute:k=>attrs[k],setAttribute:(k,v)=>attrs[k]=v,removeAttribute:k=>delete attrs[k],
  get src(){return attrs.src;},set src(v){attrs.src=v;},closest:()=>row};live.add(node);return node;
}
const thumb=image('torrent','./img/img_broken.svg');
const poster=image('explorer','./img/img_broken.svg');
const backdrop=image('background','./img/img_broken.svg');
const date={textContent:'Выход - --',setAttribute(){}};
const line={textContent:'Сезон - 2 Выход - --',querySelectorAll:()=>[{textContent:'Сезон - 2'},date]};
const row={nodeType:1,matches:s=>s==='.torrent-serial',textContent:'Сезон - 2 Выход - --',
 querySelector:s=>s==='.torrent-serial__line'?line:s==='.torrent-serial__episode'?{textContent:'3'}:null,
 querySelectorAll:s=>s.includes('img.torrent-serial__img')?[thumb]:[]};live.add(row);
const body={nodeType:1,querySelectorAll:s=>s==='.torrent-serial'?[row]:[]};
const document={body,documentElement:{contains:n=>live.has(n)},
 querySelectorAll:s=>s.includes('explorer-card')?[poster]:s.includes('full-start__background')?[backdrop]:[],
 addEventListener:(name,fn)=>events[name]=fn};
let mutate;
const context={window:null,document,Date,console,Image:class{set src(v){this.onload();}},
 setTimeout:fn=>timers.push(fn),setInterval:()=>{},MutationObserver:class{constructor(fn){mutate=fn;}observe(){}},
 Lampa:{Activity:{active:()=>({component:'torrents',movie})},Listener:{follow:(name,fn)=>events[name]=fn},
  Storage:{get:()=>({}),listener:{follow(){}}},Utils:{hash:x=>x}},
 XMLHttpRequest:class{open(method,url){this.url=url;}send(){requests.push(this.url);this.status=200;
 this.responseText=JSON.stringify(this.url.includes('/series/')?{episodes:[{season:2,episode:3,date:'2022-01-23'}]}:{paths:{},ids:{},imdb:{}});this.onload();}}};
context.window=context;
vm.runInNewContext(fs.readFileSync('posters.js','utf8').replace('__POSTER_BASE__','http://cache'),context);
assert.equal(poster.src,'http://cache/poster/kp/1178445.jpg?v=3&season=0','Explorer poster is patched even when image node has no card_data');
assert.equal(date.textContent,'Выход - 23.01.2022','dates read from cached schedule');
assert.equal(backdrop.style.visibility,'hidden','broken SVG must not fill the background');
events.torrent_file({type:'render',params:{movie},element:{season:2,episode:3},item:[row]});
for(const fn of timers.splice(0))fn();
assert.equal(thumb.src,'http://cache/poster/kp/1178445.jpg?v=3&season=2');
assert.equal(thumb.getAttribute('data-src'),thumb.src,'native lazy render must not restore broken original');
thumb.src=thumb.getAttribute('data-src');mutate([{type:'attributes',target:thumb}]);
assert.equal(requests.filter(u=>u.includes('/series/')).length,1,'metadata shared across repeated row renders');
date.textContent='Выход - 24.01.2022';events.torrent_file({type:'render',params:{movie},element:{season:2,episode:3},item:[row]});
for(const fn of timers.splice(0))fn();assert.equal(date.textContent,'Выход - 24.01.2022','known native dates are preserved');
backdrop.src='https://working/backdrop.jpg';mutate([{type:'attributes',target:backdrop}]);assert.equal(backdrop.style.visibility,'','real backdrop is not hidden');
console.log('Native series DOM: torrent thumbnails/data-src, Explorer poster, broken backdrop, cached dates, dedup and existing dates passed');
