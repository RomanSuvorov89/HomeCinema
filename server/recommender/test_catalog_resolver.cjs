const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('kinopoisk.js','utf8');
const code=source.slice(source.indexOf('  function itemYear('),source.indexOf('  function component('));
async function test() {
 const store={},requests=[],reports=[];
 const items=Array.from({length:12},(_,i)=>({kp_id:i+1,title:'Сериал & '+i,year:2020+i%3,media_type:i%2?'tv':'movie'}));
 const ctx={setTimeout,clearTimeout,encodeURIComponent,console,day:1440,source:'cub',window:{romanClientReport:(...a)=>reports.push(a)},
 Permit:{child_small:false},Storage:{get:()=>({})},Manifest:{cub_domain:'cub.test'},
 Utils:{protocol:()=> 'https://',addUrlComponent:(u,p)=>u+(u.includes('?')?'&':'?')+p,addSource:(d,s)=>({...d,source:s})},
 network:{silent(url,done){requests.push(url);const u=new URL(url);const item=items.find(i=>i.title===u.searchParams.get('query'));assert(item,'query must be encoded exactly once');
 setTimeout(()=>done({results:[{id:1000+item.kp_id,title:item.title,release_date:item.year+'-01-01'}]}),item.kp_id%3);}},
 Lampa:{Api:{sources:{}},Storage:{get:(k,d)=>store[k]?JSON.parse(JSON.stringify(store[k])):d,set:(k,v)=>store[k]=JSON.parse(JSON.stringify(v))}}};
 vm.createContext(ctx);
 vm.runInContext(fs.readFileSync('tests/fixtures/lampa-cub-list-upstream.js','utf8')+'\nLampa.Api.sources.cub=publicCub;',ctx);
 assert.equal(ctx.Lampa.Api.sources.cub.get,undefined);
 vm.runInContext(code,ctx);
 const result=await new Promise(resolve=>ctx.resolveAll(items,resolve));
 assert.equal(result.length,12);assert.equal(requests.length,12);assert.equal(reports.length,0);
 assert.equal(Object.keys(store.roman_kinopoisk_cards_v2).length,12,'parallel cache entries preserved');
 const cached=await new Promise(resolve=>ctx.resolveAll(items,resolve));
 assert.equal(cached.length,12);assert.equal(requests.length,12,'warm browser uses cache');
 ctx.Lampa.Api.sources.cub.list=()=>{throw new Error('network setup failed');};
 assert.equal(await new Promise(resolve=>ctx.resolveItem({kp_id:99,title:'Missing'},resolve)),null);
 ctx.Lampa.Api.sources.cub={};
 assert.equal(await new Promise(resolve=>ctx.resolveItem({kp_id:100,title:'Missing'},resolve)),null);
 console.log('CUB public list: 12 uncached cards, encoded Cyrillic, cold TV / warm browser, parallel cache and failures passed');
}
test().catch(e=>{console.error(e);process.exitCode=1;});
