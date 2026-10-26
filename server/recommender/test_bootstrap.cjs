const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync('client-bootstrap.js','utf8').replace('/* ROMAN_EMBEDDED_PAYLOAD */','window.romanEmbedded054=true;');
let scripts=[],timers=[],events=[],styles=[],notices=[],completed=0,success=0,errors=0;
let translatedSuccess="Плагин успешно подключен";
const ctx={window:null,navigator:{userAgent:'test Android'},Date,console,
 setTimeout:(f,ms)=>(timers.push({f,ms}),timers.length),clearTimeout:()=>{},
 XMLHttpRequest:function(){this.open=()=>{};this.setRequestHeader=()=>{};this.send=x=>events.push(JSON.parse(x));},
 document:{head:{appendChild:s=>styles.push(s)},getElementById:id=>styles.find(s=>s.id===id),body:{appendChild:s=>{scripts.push(s);s.parentNode={removeChild:()=>{}};}},createElement:()=>({})},
 addEventListener:()=>{},
 Lampa:{Noty:{show:function(){notices.push({context:this,args:Array.from(arguments)});return 'shown';}},Lang:{translate:()=>translatedSuccess},Utils:{putScriptAsync:()=>{throw Error('old async');},putScript:()=>{throw Error('old sequential');}},
 Storage:{get:()=> 'android'},Platform:{is:()=>true},Component:{},Listener:{},Api:{sources:{cub:{main:Object.assign(function(){},{romanAiHome:true})}}}}};
ctx.window=ctx;vm.createContext(ctx);vm.runInContext(code,ctx);
ctx.Lampa.Utils.putScriptAsync(['http://127.0.0.1:9120/kinopoisk.js?x=1','https://dead/plugin.js'],()=>completed++,()=>errors++,()=>success++);
assert.equal(scripts.length,1);assert.equal(success,1);assert.equal(completed,0);
const late=scripts[0].onload;timers.find(t=>t.ms===6000).f();late();
assert.equal(completed,1);assert.equal(errors,1);assert.equal(success,1);
assert(events.some(e=>e.stage==='plugin' && e.message.includes('timeout')));
scripts=[];
ctx.Lampa.Utils.putScript(['a.js','b.js'],()=>completed++,()=>errors++,()=>success++);
assert.equal(scripts.length,1);scripts[0].onload();assert.equal(scripts.length,2);scripts[1].onload();
assert.equal(completed,2);assert.equal(success,3);
ctx.Lampa.Utils.putScriptAsync(['http://server:9118/gst.js'],()=>completed++,()=>errors++,()=>success++);
assert.equal(scripts.length,2);assert.equal(completed,3);
console.log('Bootstrap: embedded dedup, bounded timeout, late callback, sequential order passed');

assert.equal(styles.length,1);
assert.equal(styles[0].textContent,'.head .halloween__button{display:none!important}','hide only the promotional action, including future insertions');
ctx.Lampa.Noty.show('Плагин успешно подключен');
translatedSuccess='Plugin successfully connected';ctx.Lampa.Noty.show(translatedSuccess);
ctx.Lampa.Noty.show('  Плагин успешно подключен  ');
assert.equal(notices.length,0,'routine plugin success stays silent across language changes');
const options={time:8000},receiver={test:true};
assert.equal(ctx.Lampa.Noty.show.call(receiver,'Не удалось загрузить плагин',options),'shown');
ctx.Lampa.Noty.show('Настройки сохранены');
ctx.Lampa.Noty.show({text:'Ошибка воспроизведения'});
assert.equal(notices.length,3,'errors, explicit action confirmations and structured notices remain available');
assert.equal(notices[0].context,receiver);assert.equal(notices[0].args[1],options);
console.log('Quiet startup: only plugin success muted, localized message handled, errors/options/receiver preserved; late CUB Halloween button hidden with scoped CSS passed');

ctx.HomeCinemaProfiles={ownsHistory:true};scripts=[];
let legacyDone=0,legacySuccess=0;
ctx.Lampa.Utils.putScriptAsync(['http://server:9118/sync/js/family','http://server:9118/bookmark.js','http://server:9118/timecode/js/family','http://server:9118/other.js'],()=>legacyDone++,()=>{throw Error('unexpected plugin error');},()=>legacySuccess++);
assert.equal(scripts.length,1,'profile synchronization excludes legacy whole-history plugins');
assert.equal(legacySuccess,3);scripts[0].onload();assert.equal(legacyDone,1);
console.log('Profiles own history: legacy sync/bookmark/timecode excluded; unrelated loaders and callbacks preserved');
