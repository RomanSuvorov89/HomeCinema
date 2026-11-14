const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('kinopoisk.js.template','utf8');
const code=source.slice(source.indexOf('/* homecinema-ai-rules:start */'),source.indexOf('/* homecinema-ai-rules:end */'));
let store={},menu,writes=0,pushed;
const ctx={window:{},Date,Math,Number,Promise,JSON,Array,Object,isFinite,
 Lampa:{Storage:{get:(k,d)=>store[k]||d,set:(k,v)=>{store[k]=v;writes++;},field:()=> 'cub'},
 Controller:{enabled:()=>({name:'content'}),toggle(){}},Noty:{show(){}},Select:{show:m=>menu=m},
 Activity:{push:p=>pushed=p},Input:{edit(){throw Error('unexpected input');}}}};
vm.createContext(ctx);vm.runInContext(code,ctx);const api=ctx.window.HomeCinemaAiRules;
const items=Array.from({length:24},(_,i)=>({kp_id:i+1,title:'Title '+i,countries:i<12?['Россия']:['США'],genres:i%2?['Комедия']:['Драма'],media_type:i%3?'tv':'movie',release_year:2024,final_score:30-i,predicted_rating:8.5,kp_rating:8}));
const original=JSON.stringify(items);
function rule(action,amount=0.7,strict=false){return {name:'RU',enabled:true,conditions:[{field:'countries',values:['Россия']}],action,amount,window:10,strict};}
const ids=result=>Array.from(result.items,i=>i.kp_id);
assert.deepEqual(ids(api.apply(items,[])),items.map(i=>i.kp_id));
assert.equal(api.apply(items,[rule('exclude')]).items.length,12);
assert.equal(api.apply(items,[{...rule('exclude'),enabled:false}]).items.length,24);
const demoted=api.apply(items,[rule('multiply',0.1)]);
assert.equal(demoted.items[0].countries[0],'США');
assert.equal(api.apply(items,[rule('multiply',0.5),rule('multiply',0.5)]).items[0].countries[0],'США');
assert.equal(JSON.stringify(items),original,'input scores and forecasts never change');
const strict=api.apply(items,[rule('quota',2,true)]);
for(let i=0;i<strict.items.length;i++)assert(strict.items.slice(Math.max(0,i-9),i+1).filter(x=>x.countries[0]==='Россия').length<=2);
assert(strict.omitted>0);
const soft=api.apply(items,[rule('quota',2,false)]);
assert.equal(soft.items.length,24);assert(soft.details.some(d=>d.relaxed));
assert.equal(api.apply(items,[rule('quota',0,true)]).items.length,12);
assert.equal(api.apply(items,[{...rule('quota',0,true),window:1}]).items.length,12);
assert.equal(api.apply(items,[rule('exclude'),rule('multiply',5)]).items.length,12);
assert.equal(api.matches({countries:['США','Россия']},{conditions:[{field:'countries',values:['Россия'],first:true}]}),false);
assert.equal(api.matches({countries:['США','Россия']},{conditions:[{field:'countries',values:['Россия']}]}),true);
assert.equal(api.matches({}, {conditions:[{field:'countries',values:['Россия'],not:true}]}),false,'unknown metadata does not match NOT');
assert.equal(api.matches(items[0],{conditions:[{field:'countries',values:['Россия','США']},{field:'media_type',values:['tv']}]}),false,'different fields are AND');
assert.equal(api.apply(items,[rule('multiply',NaN),rule('quota',12)]).items.length,24,'invalid rules ignored');
const cards=items.map(i=>({id:i.kp_id,roman_review:i}));store.homecinema_ai_rules_v1=[rule('exclude')];
assert.equal(api.cards(cards).length,12);assert.equal(api.cards(cards)[0],cards[12],'original card identity preserved');
store={};assert.equal(api.cards(cards).length,24,'new profile has no inherited rules');
api.setProvider(()=>Promise.resolve({items}));
(async()=>{
 api.open();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(writes,0);
 menu.onSelect(menu.items.find(i=>i.action==='template'));
 menu.onBack();
 menu.onSelect(menu.items.find(i=>i.action==='preview'));
 assert(menu.title.includes('затронуто'));assert.equal(writes,0,'preview never persists a draft');
 menu.onBack();menu.onSelect(menu.items.find(i=>i.action==='save'));
 assert.equal(writes,1);assert.equal(store.homecinema_ai_rules_v1[0].amount,2);assert.equal(pushed.component,'main');
 const saved=JSON.stringify(store);
 api.open();await new Promise(resolve=>setImmediate(resolve));
 menu.onSelect(menu.items.find(i=>i.rule));
 menu.onSelect(menu.items.find(i=>i.action==='copy'));
 menu.onBack();menu.onSelect(menu.items.find(i=>i.action==='cancel'));
 assert.equal(JSON.stringify(store),saved,'cancel discards copied draft');
 console.log('AI rules: AND/OR/NOT, unknown metadata, composition, hard/soft sliding quotas, immutable ratings, profile isolation, draft preview/save/cancel and copy passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
