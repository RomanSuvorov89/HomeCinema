const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('kinopoisk.js','utf8');
const values={file_view:{'754600950':{percent:100},'Partial Movie':{percent:40},'28Startup Show':{percent:100}},
 roman_home_shelves_releases_v1:{items:[{kp_id:42,season:2,episode:8,next_air_date:null}]}};
const initial=JSON.stringify(values),elements=[],listeners={},timelineEvents={};let writes=0;
function on(events,name,fn){(events[name]||(events[name]=[])).push(fn);}
function send(name,event){(listeners[name]||[]).forEach(fn=>fn(event));}
function element(card){const classes=new Set();return{card_data:card,classList:{toggle:(key,on)=>on?classes.add(key):classes.delete(key),contains:key=>classes.has(key)}};}
const movie={id:5,original_title:'Startup Movie',media_type:'movie'},partial={id:6,original_title:'Partial Movie',media_type:'movie'},
 show={id:7,kinopoisk_id:42,original_name:'Startup Show',media_type:'tv'};
const ctx={window:{appready:false},console,
 Storage:{get:(key,fallback)=>Object.hasOwn(values,key)?values[key]:fallback,set:()=>writes++},
 Account:{Permit:{sync:false}},Utils:{hash:text=>text==='Startup Movie'?'754600950':String(text),onceInit:fn=>{let done=false;return()=>{if(!done){done=true;fn();}};}},
 Subscribe:()=>({follow:(name,fn)=>on(timelineEvents,name,fn),send:(name,event)=>(timelineEvents[name]||[]).forEach(fn=>fn(event))}),
 document:{body:{classList:{toggle(){}}},head:{appendChild(){}},createElement:()=>({}),querySelectorAll:()=>elements},
 reviewForCard:()=>({}),cacheGet:()=>null,ratingKey:c=>String(c.id),data:{ratings:[]},
 Lampa:{Listener:{follow:(name,fn)=>on(listeners,name,fn),send},Favorite:{get:()=>[]},Activity:{active:()=>({component:'main'})},Component:{get:()=>null}}};
ctx.Lampa.Storage=ctx.Storage;ctx.Lampa.Utils=ctx.Utils;ctx.Lampa.Storage.listener={follow:(name,fn)=>on(listeners,'storage:'+name,fn)};
vm.createContext(ctx);
const upstream=fs.readFileSync('tests/fixtures/lampa-timeline.js','utf8').replace(/^import .*\n/gm,'').replace('export default {','globalThis.NativeTimeline = {');
vm.runInContext(upstream,ctx);ctx.Lampa.Timeline=ctx.NativeTimeline;
assert.throws(()=>ctx.NativeTimeline.watched(movie,true),/754600950/,'upstream reproduces the exact pre-init undefined map from the screenshot');
vm.runInContext(source.slice(source.indexOf('  function sameHomeCard('),source.indexOf('  function homeRowKind(')),ctx);
ctx.installHomeNavigation();
let planned;
assert.doesNotThrow(()=>planned=ctx.combinedWatchCards([movie,partial]),'a fast home snapshot must not read uninitialized native Timeline');
assert.equal(planned.length,2,'keep unconfirmed cards until playback initialization finishes');
let resume;
assert.doesNotThrow(()=>resume=ctx.continueHomeCards([show]),'same lifecycle applies to episode completion');
assert.equal(resume.length,1);
const watchedElement=element(planned[0]),partialElement=element(planned[1]),showElement=element(resume[0]);
elements.push(watchedElement,partialElement,showElement);
ctx.NativeTimeline.init();
assert.equal(watchedElement.classList.contains('homecinema-watch-completed'),false,'timeline read can precede app-ready');
ctx.window.appready=true;send('app',{type:'ready'});
assert(watchedElement.classList.contains('homecinema-watch-completed'),'already painted completed movie is removed once native data is ready');
assert(!partialElement.classList.contains('homecinema-watch-completed'),'partially watched movie remains');
assert(showElement.classList.contains('homecinema-caught-up'),'already painted completed finale is updated too');
assert.deepEqual(Array.from(ctx.combinedWatchCards([movie,partial]),c=>c.id),[6]);
assert.equal(ctx.continueHomeCards([show]).length,0);
// Subsequent native reads (including a different profile) use that profile's actual map.
ctx.Account.Permit={sync:true,account:{profile:{id:7}}};values.file_view_7={'754600950':{percent:10},'28Startup Show':{percent:10}};
ctx.NativeTimeline.read();
assert(!watchedElement.classList.contains('homecinema-watch-completed'));
assert(!showElement.classList.contains('homecinema-caught-up'));
assert.equal(writes,0,'display lifecycle must not initialize or overwrite native history itself');
delete values.file_view_7;assert.equal(JSON.stringify(values),initial,'existing history remains byte-for-byte equivalent');
console.log('Real upstream Timeline: exact pre-init crash reproduced; fast startup snapshots safe; app-ready rechecks movies/series, partial progress and profile reads; history unchanged passed');
