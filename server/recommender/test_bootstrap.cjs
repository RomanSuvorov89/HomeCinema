const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync('client-bootstrap.js','utf8').replace('/* ROMAN_EMBEDDED_PAYLOAD */','window.romanEmbedded054=true;');
let scripts=[],timers=[],events=[],completed=0,success=0,errors=0;
const ctx={window:null,navigator:{userAgent:'test Android'},Date,console,
 setTimeout:(f,ms)=>(timers.push({f,ms}),timers.length),clearTimeout:()=>{},
 XMLHttpRequest:function(){this.open=()=>{};this.setRequestHeader=()=>{};this.send=x=>events.push(JSON.parse(x));},
 document:{body:{appendChild:s=>{scripts.push(s);s.parentNode={removeChild:()=>{}};}},createElement:()=>({})},
 addEventListener:()=>{},
 Lampa:{Utils:{putScriptAsync:()=>{throw Error('old async');},putScript:()=>{throw Error('old sequential');}},
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
