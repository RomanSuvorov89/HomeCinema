const fs=require('fs'),vm=require('vm'),assert=require('assert');
const s=fs.readFileSync('kinopoisk.js','utf8');
const code=s.slice(s.indexOf('  function openNowShelf()'),s.indexOf('  function installCatalogPageCache()'));
(async()=>{
 let net=0,pushed,first;
 const cards=Array.from({length:25},(_,i)=>({id:i,media_type:'tv',roman_review:{kp_id:100+i,predicted_rating:6.5}}));
 cards.splice(2,0,{id:99,name:'No forecast'});
 const ctx={Promise,Number,Math,Array,String,reviewItems:{},reviewCards:{},SHELF_COMPONENT:'shelf',
 filterReleaseCards:x=>x,reviewRequest:()=>{net++;throw Error('must use saved shelf');},
 Lampa:{Storage:{get:()=>({now:{row:{results:cards}}})},Activity:{push:x=>pushed=x},
 InteractionCategory:function(){this.build=d=>first=d;this.empty=()=>{};}}};
 vm.createContext(ctx);vm.runInContext(code,ctx);
 ctx.openNowShelf();assert.equal(pushed.url,'roman-home://now');
 const c=ctx.shelfComponent({page:1});c.create();await new Promise(r=>setImmediate(r));
 assert.equal(first.results.length,12);assert.equal(first.total_results,25);assert(!first.results.some(x=>x.id===99));
 let second;c.nextPageReuest({page:2},d=>second=d);await new Promise(r=>setImmediate(r));
 assert.equal(second.results[0].id,12);assert.equal(second.results.length,12);
 let last;c.nextPageReuest({page:3},d=>last=d);await new Promise(r=>setImmediate(r));
 assert.equal(last.results.length,1);assert(last.nomore);assert.equal(net,0);
 console.log('Personal Now More: saved snapshot, prediction eligibility, stable pagination, no CUB request passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
