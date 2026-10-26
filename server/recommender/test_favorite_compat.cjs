const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('kinopoisk.js.template','utf8');
const upstream=fs.readFileSync('tests/fixtures/lampa-favorite.js','utf8')
 .replace(/^import .*\n/gm,'').replace('export default {','globalThis.NativeFavorite = {');
for(const legacy of [false,true]){
 const values={favorite:{card:[{id:1,title:'Planned'},{id:2,title:'Seen'}],wath:[1],viewed:[2]}};
 let writes=0,reads=0;
 const ctx={window:{appready:false},Storage:{get:(k,d)=>values[k]||d,set:()=>writes++},
 Arrays:{extend:(obj,defaults)=>{for(const k in defaults)if(typeof obj[k]==='undefined')obj[k]=defaults[k];return obj;}},
 Subscribe:()=>({send(){}}),Account:{Permit:{sync:false}},Utils:{onceInit:fn=>fn},Lampa:{Listener:{send(){}}}};
 ctx.Lampa.Storage=ctx.Storage;
 vm.createContext(ctx);
 // An older native category list lacks scheduled; exercise the SAME get/full/read
 // functions, rather than mocking get() to always return [] for unknown names.
 vm.runInContext(legacy?upstream.replace(", 'scheduled'",''):upstream,ctx);
 assert.throws(()=>ctx.NativeFavorite.get({type:'wath'}),/forEach/,'native pre-read failure reproduced');
 const get=ctx.NativeFavorite.get;
 ctx.NativeFavorite.get=params=>{reads++;return get(params);};
 ctx.Lampa.Favorite=ctx.NativeFavorite;
 vm.runInContext(source.slice(source.indexOf('  function nativeFavorite('),source.indexOf('  var watchDisplayCards=')),ctx);
 assert.equal(ctx.nativeFavorite('wath').length,0);
 assert.equal(reads,0,'do not call native get before app-ready');
 assert.equal(writes,0);
 ctx.NativeFavorite.read(true);ctx.window.appready=true;
 const before=JSON.stringify(values);
 assert.equal(ctx.nativeFavorite('wath')[0].id,1);
 assert.equal(ctx.nativeFavorite('viewed')[0].id,2);
 assert.equal(ctx.nativeFavorite('scheduled').length,0);
 if(legacy)assert.throws(()=>get({type:'scheduled'}),/forEach/,'unsupported category reproduces exact screenshot failure after startup');
 assert.equal(ctx.nativeFavorite('unsupported').length,0);
 assert.equal(writes,0,'the adapter never writes or resets history');
 assert.equal(JSON.stringify(values),before,'native supported categories and stored cards remain intact');
 // A restored profile can have fewer categories than the previous local one.
 values.favorite={card:[{id:3,title:'Restored'}],wath:[3]};
 ctx.NativeFavorite.read(true);
 assert.equal(ctx.nativeFavorite('wath')[0].id,3);
 assert.equal(ctx.nativeFavorite('viewed').length,0);
 assert.equal(ctx.nativeFavorite('scheduled').length,0);
 assert.equal(writes,0);
}
console.log('Real Favorite: pre-read and unsupported-category forEach reproduced; app-ready, older category map, restored profile and untouched history passed');
