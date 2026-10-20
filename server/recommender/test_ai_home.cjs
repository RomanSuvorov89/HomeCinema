const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('kinopoisk.js','utf8');
const filters=source.slice(source.indexOf('  function filterReviewItems('),source.indexOf('  function openReviewList('));
const code=source.slice(source.indexOf('  function filterReleaseCards('),source.indexOf('  var data = null;'));
const upstream=fs.readFileSync('tests/fixtures/lampa-home-upstream.js','utf8');
async function run(fail=false) {
 let pushed,opened=0,requestCount=0; const persisted={};
 const titles={title_latest:'Последнее добавление',title_fire:'Огонь!',title_now_watch:'Сейчас смотрят',
   title_recomend_watch:'Рекомендуем посмотреть',title_trailers:'Трейлеры',title_new:'Новинки',title_in_high_quality:'В высоком качестве'};
 const year=new Date().getFullYear();
 const ctx={Promise,Date,Object,Array,setTimeout,clearTimeout,REVIEW_COMPONENT:'review',COMPONENT:'watch',reviewBase:'http://local:9120',reviewItems:{},reviewCards:{},
  reviewForCard(){return null;},cacheGet(){return null;},ratingKey(){return '';},
  openWatchlist(){opened++;},openReviewList(){opened++;},
  loadData(done){done({watchlist:[{kp_id:77,title:'Watch'}]});},
  reviewRequest(){throw Error('Home requested recalculation');},
  resolveAll(){throw Error('Home searched cards on client');},
  component:'content_rows',day:1,Permit:{},TMDB:{genres:{movie:[{id:28,title:'action'},{id:35,title:'comedy'}]}},
  Arrays:{isArray:Array.isArray,isObject:x=>x && typeof x==='object',insert(a,i,v){a.splice(i,0,v);},shuffleArrayFromIndex(){}},
  Storage:{get(){return true;}},Template:{string(){return '';}},LineModule:{MASK:{base:0},toggle(){return 0;}},
  Utils:{protocol(){return 'https://';},capitalizeFirstLetter:x=>x},Manifest:{cub_domain:'test'},
  network:{silent(url,done){done({results:[]});}},
  get(url,params,done){requestCount++;setTimeout(()=>done({url,results:[{id:url,release_quality:'WEBRip'},{id:'bad',release_quality:'TS'}]}),url.includes('fire')?12:1);},
  trailers(type,done){setTimeout(()=>done({title:'Трейлеры - Новинки',results:[{id:300}]}),2);},
  rows:[{screen:'main',name:'resume',index:8,call(){return cb=>setTimeout(()=>cb({title:'Продолжить просмотр',results:[{id:101}]}),20);}},
    {screen:'main',name:'recommend',index:0,call(){return cb=>cb({title:'Рекомендуем посмотреть',results:[{id:102}]});}}],
  Progress:class {append(p){this.p=p;} start(done){Promise.all(this.p.map(p=>new Promise(resolve=>p(resolve)))).then(done);}},
  Lampa:{Lang:{translate(k){return titles[k]||k;}},Activity:{push(p){pushed=p;}},Api:{sources:{cub:{}}}}
 };
 const snapshot={rows:[
  {kind:'continue',title:'Продолжить просмотр',results:[{id:101},{id:999,title:'Rated airing',media_type:'tv',roman_review:{kp_id:999,my_rating:8,continue_reason:'rated_airing'}}]},
  {kind:'ai',title:'Рекомендация AI',results:[{id:1,title:'AI',media_type:'movie',roman_review:{kp_id:1}}]},
  {kind:'archive',title:'Из прошлых лет — для тебя',results:[{id:2,title:'Old'}]},
  {kind:'watch',title:'Буду смотреть',results:[{id:3,title:'Watch'}]}]};
 ctx.Lampa.Reguest=class {timeout(){} silent(url,done,error){assert(url.endsWith('/home.json'));setTimeout(()=>fail?error():done(snapshot),1);}};
 ctx.Lampa.Storage={get:(k,d)=>persisted[k] || d,set:(k,v)=>{persisted[k]=JSON.parse(JSON.stringify(v));}};
 ctx.Lang=ctx.Lampa.Lang;ctx.Api={partPersons(){return cb=>cb({title:'Persons',results:[{id:200}]});}};
 vm.createContext(ctx);vm.runInContext(upstream,ctx);
 ctx.ContentRows={call:ctx.call};ctx.Lampa.ContentRows=ctx.ContentRows;ctx.Api.partNext=ctx.partNext;ctx.Lampa.Api.partNext=ctx.partNext;
 Object.defineProperty(ctx.Api,"partNext",{get(){return ctx.Lampa.Api.partNext;}});
 ctx.Lampa.Api.sources.cub.main=ctx.main;
 vm.runInContext(filters+code,ctx);ctx.installAiHome();ctx.installAiHome();
 let more;
 const first=await new Promise((resolve,reject)=>{more=ctx.Lampa.Api.sources.cub.main({},resolve,reject);});
 const expected=fail?['Продолжить просмотр','Огонь!','Сейчас смотрят']:
  ['Продолжить просмотр','Рекомендация AI','Огонь!','Сейчас смотрят — для тебя','Из прошлых лет — для тебя','Буду смотреть'];
 // Native pagination may put the sixth priority row into the second batch.
 assert(!first.some(r=>/Трейлер|Последнее|высоком/.test(r.title)));
 assert(first.every(r=>r.results.every(c=>c.release_quality!=='TS')));
 let all=first.slice();for(let i=0;i<20;i++){const batch=await new Promise(resolve=>more(resolve,()=>resolve(null)));if(!batch)break;all=all.concat(batch);}
 assert.deepEqual(Array.from(all.slice(0,expected.length),r=>r.title),expected.filter(t=>t!=='Рекомендуем посмотреть'));
 assert.equal(all.filter(r=>r.title==='Огонь!').length,1);
 if(!fail){const resume=all.find(r=>r.title==='Продолжить просмотр');assert.deepEqual(Array.from(resume.results,c=>c.id),[101,999]);}
 assert.equal(all.filter(r=>r.title==='Буду смотреть').length,fail?0:1);
 assert(all.some(r=>r.title==='action'));assert(all.some(r=>r.title==='comedy'));
 if(!fail){all[1].params.emit.onlyMore();assert.equal(opened,1);}
 // Reinstall in a fresh plugin closure with expired, JSON-persisted shelf caches.
 ctx.Date=class extends Date {static now(){return Date.now()+120000;}};
 ctx.Lampa.Api.sources.cub.main=ctx.main;ctx.Lampa.ContentRows.call=ctx.call;
 ctx.Lampa.Reguest=class {timeout(){} silent(){}};
 vm.runInContext(filters+code,ctx);ctx.installAiHome();
 // Home cache is also read on a fresh page load (JSON round-trip above).
 const started=Date.now();
 ctx.get=function(url,params,done){if(/now_playing|fire/.test(url)) return;done({url,results:[{id:url}]});};
 const warm=await Promise.race([new Promise(resolve=>ctx.Lampa.Api.sources.cub.main({},resolve,()=>resolve([]))),new Promise((_,reject)=>setTimeout(()=>reject(Error('warm home blocked by network')),250))]);
 assert(warm.some(r=>r.title==='Огонь!'));assert(warm.some(r=>/^Сейчас смотрят/.test(r.title)));
 assert(Date.now()-started<250);
 if(!fail){
  for(const key of Object.keys(persisted))delete persisted[key];
  ctx.Lampa.Api.sources.cub.main=ctx.main;ctx.Lampa.ContentRows.call=ctx.call;
  let release;
  ctx.Lampa.Reguest=class {timeout(){} silent(url,done){release=done;}};
  vm.runInContext(filters+code,ctx);ctx.installAiHome();
  const coldStart=Date.now();let coldNext;
  const cold=await Promise.race([
   new Promise(resolve=>{coldNext=ctx.Lampa.Api.sources.cub.main({},resolve,()=>resolve([]));}),
   new Promise((_,reject)=>setTimeout(()=>reject(Error('cold first paint blocked')),2300))]);
  assert(cold.some(row=>row.title==='Продолжить просмотр'));
  assert(Date.now()-coldStart<250,'Continue Watching waited for a cold recommendations cache');
  assert(!cold.some(row=>/Трейлер|Последнее|высоком/.test(row.title)));
  release(snapshot);
  await new Promise(resolve=>setTimeout(resolve,5));
  const late=await new Promise(resolve=>coldNext(resolve,()=>resolve([])));
  assert(late.some(row=>row.title==='Рекомендация AI'),'late cold-cache result was lost');
 }
 ctx.Lampa.Activity.push({url:'roman-ai://archive'});assert.equal(pushed.review_period,'archive');
 ctx.Lampa.Activity.push({url:'roman-kp://watchlist'});assert.equal(pushed.component,'watch');
 for(const title of ['Трейлеры - Новинки','Трейлеры — Новинки','#{title_trailers} - Новинки','UHD']) assert(ctx.hiddenHomeRow({title}));
 assert.equal(ctx.filterReleaseCards(['TS','HDTS','CAMRip','HDCAM','TC','DVDSCR','WEB-DL','WEBRip','BDRip','4K',''].map(quality=>({quality}))).length,5);
}
(async()=>{await run();await run(true);console.log('CUB: order, trailers, pagination; warm AND empty cache with stalled requests: first Continue Watching <250ms; late rows retained: passed');})().catch(e=>{console.error(e);process.exitCode=1;});
