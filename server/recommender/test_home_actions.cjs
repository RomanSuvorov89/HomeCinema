const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('kinopoisk.js','utf8'),values={},requests=[],appended=[];
let menu,buttonHandler,closeCount=0;
const item={kp_id:42,title:'Hidden series'},host={length:1,append:x=>appended.push(x)};
function $(text){
 if(text==='.button--roman-review')return {remove(){}};
 if(text==='.full-start-new__buttons')return host;
 return {on:(name,fn)=>{buttonHandler=fn;}};
}
const ctx={console,$,Promise,Object,Array,document:{querySelectorAll:()=>[]},
 reviewForCard:()=>item,markReview(){},reviewLabels:{want:'Хочу посмотреть',not_interested:'Не интересно',seen:'Уже смотрел'},
 reviewRequest:(url,body)=>{requests.push({url,body});return Promise.resolve({status:body.status==='clear'?null:body.status});},
 Lampa:{Storage:{get:(k,d)=>values[k]||d,set:(k,v)=>values[k]=v},Noty:{show(){}},Controller:{toggle(){}},Select:{show:x=>menu=x,close(){closeCount++;menu.onBack();}}}};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  var homeFeedbackRevision'),source.indexOf('  function filterReviewItems')),ctx);
vm.runInContext(source.slice(source.indexOf('  function addReviewActions'),source.indexOf('  // Scope the replacement')),ctx);
ctx.addReviewActions({type:'complite',data:{movie:{kinopoisk_id:42}}});
assert.equal(appended.length,1,'one compact action replaces multiple text buttons');
buttonHandler();assert.equal(menu.items.length,3);
ctx.Lampa.Select.close();assert.equal(closeCount,1,'native close calls onBack exactly once');
buttonHandler();
(async()=>{
 menu.onSelect(menu.items.find(x=>x.status==='not_interested'));await new Promise(r=>setImmediate(r));
 assert.equal(closeCount,1,'selection must not close a second time');
 assert.equal(requests[0].body.kp_id,42);assert.equal(requests[0].body.status,'not_interested');
 assert.equal(ctx.hiddenHomeCards([{kinopoisk_id:42},{kinopoisk_id:43}]).length,1);
 buttonHandler();assert(menu.items.some(x=>x.status==='clear'),'hidden state can be reversed');
 menu.onSelect(menu.items.find(x=>x.status==='clear'));await new Promise(r=>setImmediate(r));
 assert.equal(ctx.hiddenHomeCards([{kinopoisk_id:42}]).length,1);
 console.log('Home actions: one menu, persisted exclusion, clear restores cards passed');
})().catch(e=>{console.error(e);process.exit(1);});
