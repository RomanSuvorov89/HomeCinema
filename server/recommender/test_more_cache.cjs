const fs=require('fs'),vm=require('vm'),assert=require('assert');
const s=fs.readFileSync('kinopoisk.js','utf8');
const reportCode=s.slice(s.indexOf('  var reviewSnapshotFlight='),s.indexOf('  function reviewForCard('));
const pageCode=s.slice(s.indexOf('  function installCatalogPageCache('),s.indexOf('  function installAiHome('));
(async()=>{
 const store={roman_review_snapshot_v4:{revision:'r1',items:[{kp_id:1,title:'Cached',card:{id:10}}]}};
 let release,net=0,calls=0,networkDone;
 const ctx={Promise,JSON,Object,Array,Date,encodeURIComponent,
 reviewRequest(path){net++;assert(path.includes('revision=r1'));return new Promise(r=>release=r);},
 Lampa:{Storage:{get:(k,d)=>store[k]||d,set:(k,v)=>store[k]=JSON.parse(JSON.stringify(v))},Api:{sources:{cub:{list(params,done){calls++;networkDone=done;}}}}}};
 vm.createContext(ctx);vm.runInContext(reportCode+pageCode,ctx);
 const report=await ctx.cachedReviewReport();assert.equal(report.items[0].title,'Cached');assert.equal(net,1);
 release({revision:'r2',items:[{kp_id:1,title:'Changed',card:{id:10}}]});await new Promise(r=>setImmediate(r));
 assert.equal(store.roman_review_snapshot_v4.items[0].title,'Changed');
 ctx.installCatalogPageCache();const api=ctx.Lampa.Api.sources.cub;
 api.list({url:'top/fire/movie',page:2},x=>assert.equal(x.results[0].id,20));
 networkDone({results:[{id:20}],page:2});assert.equal(calls,1);
 let shown=false;api.list({url:'top/fire/movie',page:2},x=>{shown=true;assert.equal(x.results[0].id,20);});
 assert(shown);assert.equal(calls,1,'same launch must not reload page');
 const circular={url:'top/fire/movie',page:2};circular.activity={component:{object:circular}};
 shown=false;api.list(circular,()=>shown=true);assert(shown);assert.equal(calls,1,'runtime cycle must not affect the request cache key');
 // A fresh launch renders persisted pages before the stalled background response.
 ctx.Lampa.Api.sources.cub.list=function(params,done){calls++;networkDone=done;};
 vm.runInContext(pageCode,ctx);ctx.installCatalogPageCache();shown=false;
 ctx.Lampa.Api.sources.cub.list({url:'top/fire/movie',page:2},()=>shown=true);
 assert(shown);assert.equal(calls,2);networkDone({results:[{id:21}],page:2});
 assert.equal(Object.values(store.roman_catalog_pages_v2)[0].data.results[0].id,21);
 console.log('More: immediate persisted report/pages, background revision changes, no repeated page requests: passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
