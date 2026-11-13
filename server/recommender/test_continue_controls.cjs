const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const text=fs.readFileSync('kinopoisk.js.template','utf8');
let store={},now=1000000,menu,button;
const host={length:1,append(x){button=x;}};
const ctx={Date:class extends Date{static now(){return now;}},window:{appready:true},
 document:{querySelectorAll:()=>[]},
 $:value=>value.startsWith('<')?{on(name,fn){this.enter=fn;return this;}}:value.includes('button--')?{remove(){}}:host,
 Lampa:{Activity:{push(p){assert.equal(p.component,'main');}},Storage:{field:()=> 'cub',get:(k,d)=>store[k]||d,set:(k,v)=>store[k]=v},Controller:{enabled:()=>({name:'content'}),toggle(){}},Select:{show:v=>menu=v},Noty:{show(){}}}};
vm.createContext(ctx);
vm.runInContext(text.slice(text.indexOf('  function continueKey('),text.indexOf('  function lastHomeEpisode(')),ctx);
ctx.caughtUpSeries=()=>true;
const card={id:42,name:'Сериал',original_name:'Show',first_air_date:'2022-01-01',source:'cub'};
assert.equal(ctx.continueHomeCards([card]).length,0);
ctx.saveContinueChoice(card,0);
assert.equal(ctx.continueHomeCards([]).length,1,'manual addition creates a list without native history');
assert.equal(ctx.continueHomeCards([{...card,source:'tmdb'}]).length,1,'CUB/TMDB identity is deduplicated');
ctx.saveContinueChoice(card,7);
assert.equal(ctx.continueHomeCards([card]).length,0);
now+=7*86400000;
assert.equal(ctx.continueHomeCards([]).length,1,'pinned show returns after exact deadline');
ctx.saveContinueChoice(card,-1);now+=1000*86400000;
assert.equal(ctx.continueHomeCards([card]).length,0,'permanent hide survives time');
ctx.saveContinueChoice(card,0);assert.equal(ctx.continueHomeCards([]).length,1);
const firstProfile=store;store={};
assert.equal(ctx.continueHomeCards([]).length,0,'other profile has no manual additions');
ctx.caughtUpSeries=()=>false;
ctx.saveContinueChoice(card,30);now+=30*86400000;
assert.equal(ctx.continueHomeCards([]).length,0,'hiding automatic card does not pin it');
assert.equal(ctx.continueHomeCards([card]).length,1,'automatic card returns to natural policy');
store=firstProfile;
ctx.addContinueActions({type:'complite',data:{movie:card}});assert(button);
button.enter();assert.deepEqual(Array.from(menu.items,x=>x.days),[0,7,30,90,-1]);
menu.onSelect(menu.items[4]);assert(ctx.continueSuppressed(card));
assert(!('online_watched_last' in store));assert(!('favorite' in store),'no fake viewing history');
console.log('Continue controls: manual inclusion, dedup, expiry, permanent hide, restoration, profiles and real menu handler passed');
