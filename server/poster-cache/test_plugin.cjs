const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let observer;
const nodes = [];
let requests = 0;
let failed = false;
let failTmdb = false;
const addresses=[];
const intervals=[];
const settings={};
let storageListener;
const watched={};
let seasonIndex={};
const timers=[];
function makeCard(data, src) {
    const attrs = {src};
    const image = {classList: {contains: s => s === 'card__img'},
        getAttribute: key => attrs[key], setAttribute: (k,v) => {attrs[k]=v;}, removeAttribute: k => {delete attrs[k];},
        get src() {return attrs.src;}, set src(value) {attrs.src = value;}, closest: () => card};
    const card = {nodeType: 1, card_data: data, classList: {contains: s => s === 'card'},
        querySelector: () => image, querySelectorAll: () => []};
    nodes.push(image);
    return {card,image};
}
const good = makeCard({id:85552,kinopoisk_id:'1178445',name:'Эйфория',poster_path:'/native.jpg'}, 'https://image.tmdb.org/x.jpg');
const unknown = makeCard({id:999,name:'Unknown'}, 'https://image.tmdb.org/unknown.jpg');
const doc = {body:{nodeType:1,querySelectorAll:()=>[good.card,unknown.card]},
    documentElement:{contains: node=>nodes.includes(node)},querySelectorAll:()=>[],addEventListener:(name,fn)=>{listeners[name]=fn;}};
const listeners = {};
const context = {window:{}, document:doc, Date, setTimeout:fn=>timers.push(fn), setInterval:fn=>intervals.push(fn),
    Lampa:{TMDB:{image:path=>'native:'+path},Listener:{follow:(key,fn)=>{listeners[key]=fn;}},Storage:{get:key=>key==='online_watched_last'?watched:settings[key],set:(k,v)=>settings[k]=v,listener:{follow:(key,fn)=>storageListener=fn}},Utils:{hash:value=>value}},
    Image: class {set src(value){requests++;addresses.push(value); if(failed || (failTmdb && value.includes('/tmdb/image/')))this.onerror();else this.onload();}},
    XMLHttpRequest: class {open(){} send(){this.status=200;this.responseText=JSON.stringify({paths:{},ids:{},imdb:{},seasons:seasonIndex});this.onload();}},
    MutationObserver:class {constructor(fn){observer=fn;} observe(){}}};
context.window.Lampa = context.Lampa;
vm.runInNewContext(fs.readFileSync('posters.js','utf8').replace('__POSTER_BASE__','http://server:9121'),context);
assert.equal(good.image.src,'http://server:9121/tmdb/image/t/p/w500/native.jpg');
assert.equal(unknown.image.src,'https://image.tmdb.org/unknown.jpg');
assert.equal(requests,1);
good.image.src='https://image.tmdb.org/native-retry.jpg';
observer([{type:'attributes',target:good.image}]);
assert.equal(good.image.src,'http://server:9121/tmdb/image/t/p/w500/native.jpg');
assert.equal(requests,1);
failed=true;
const unavailable=makeCard({kinopoisk_id:'555'},'original.jpg');
observer([{type:'childList',addedNodes:[unavailable.card]}]);
assert.equal(unavailable.image.src,'original.jpg');
console.log('Plugin: known ID replaced; unknown/failure retained; native retry handled; download reused.');

failed=false;
watched.Euphoria={season:2};
const seasonal=makeCard({kinopoisk_id:'42',name:'Эйфория',original_name:'Euphoria'},'original.jpg');
observer([{type:'childList',addedNodes:[seasonal.card]}]);
assert.equal(seasonal.image.src,'http://server:9121/poster/kp/42.jpg?v=3&season=2');
watched.Euphoria.season=3;
observer([{type:'attributes',target:seasonal.image}]);
assert.equal(seasonal.image.src,'http://server:9121/poster/kp/42.jpg?v=3&season=3');
console.log('Seasonal posters: watched season changes URL and does not reuse another season.');

listeners.full({type:'complite',data:{movie:{kinopoisk_id:'42',name:'Эйфория',original_name:'Euphoria'}}});
function previewImage(src,season) {
 const attrs={src};
 const node={naturalWidth:0,matches:s=>s.includes('season-episode'),
  getAttribute:k=>attrs[k],setAttribute:(k,v)=>attrs[k]=v,removeAttribute:k=>delete attrs[k],
  get src(){return attrs.src;},set src(v){attrs.src=v;},
  closest:()=>({textContent:'Сезон - '+season,querySelectorAll:()=>[]})};
 nodes.push(node);return node;
}
const episode=previewImage('./img/img_broken.svg',2);
listeners.error({target:episode});
assert.equal(episode.src,'http://server:9121/poster/kp/42.jpg?v=3&season=2','torrent episode uses its own season');
assert.equal(episode.getAttribute('data-homecinema-preview'),'season-poster','fallback is identified, not a claimed episode frame');
const working=previewImage('https://reachable/real-frame.jpg',2);working.naturalWidth=640;
observer([{type:'attributes',target:working}]);
assert.equal(working.src,'https://reachable/real-frame.jpg','working episode frames stay unchanged');
const unrelated=previewImage('https://example.test/missing.jpg',1);unrelated.matches=()=>false;
listeners.error({target:unrelated});assert.equal(unrelated.src,'https://example.test/missing.jpg');
console.log('Episode previews: season-specific labelled fallback, working frames and unrelated images preserved.');

const stalled=previewImage('https://blocked/episode.jpg',2);
observer([{type:'attributes',target:stalled}]);
for(const fn of timers.splice(0))fn();
assert.equal(stalled.src,'https://blocked/episode.jpg','pending images are not replaced before a real error');
listeners.error({target:stalled});
assert.equal(stalled.src,'http://server:9121/poster/kp/42.jpg?v=3&season=2');
assert.equal(working.src,'https://reachable/real-frame.jpg','delayed check retains an already loaded frame');

assert.equal(context.Lampa.TMDB.image('t/p/w300/hash.jpg'),'http://server:9121/tmdb/image/t/p/w300/hash.jpg');
assert.equal(settings.proxy_tmdb,true);
assert.equal(settings.proxy_tmdb_auto,true);
assert.equal(context.Lampa.TMDB.image('invalid'),'native:invalid');
context.Lampa.TMDB.image=path=>'late:'+path;
intervals[0]();
assert.equal(context.Lampa.TMDB.image('t/p/w300/new.jpg'),'http://server:9121/tmdb/image/t/p/w300/new.jpg','late Lampac plugin is wrapped');
const noKp=makeCard({id:100,poster_path:'/without-kp.jpg'},'old.jpg');
observer([{type:'childList',addedNodes:[noKp.card]}]);
assert.equal(noKp.image.src,'http://server:9121/tmdb/image/t/p/w500/without-kp.jpg','TMDB cache does not require a KP ID');
failTmdb=true;
const fallback=makeCard({kinopoisk_id:'99',poster_path:'/missing.jpg'},'old.jpg');
const before=addresses.length;
observer([{type:'childList',addedNodes:[fallback.card]}]);
assert.equal(fallback.image.src,'http://server:9121/poster/kp/99.jpg?v=3&season=0');
assert.deepEqual(addresses.slice(before),['http://server:9121/tmdb/image/t/p/w500/missing.jpg','http://server:9121/poster/kp/99.jpg?v=3&season=0'],'fallback only after TMDB failure');
failTmdb=false;
const nativeFrame=previewImage('http://lampac/tmdb/img/t/p/w300/frame.jpg?uid=private',2);
nativeFrame.setAttribute('data-src',nativeFrame.src);
observer([{type:'attributes',target:nativeFrame}]);
assert.equal(nativeFrame.src,'http://server:9121/tmdb/image/t/p/w300/frame.jpg');
assert.equal(nativeFrame.getAttribute('data-src'),nativeFrame.src,'lazy renderer keeps the cached frame');
console.log('TMDB first: proxy defaults, late plugin, posters without KP, exact frames and ordered fallback passed.');

const fromSrc=makeCard({kinopoisk_id:'123'},'https://image.tmdb.org/t/p/w300/from-src.jpg');
observer([{type:'childList',addedNodes:[fromSrc.card]}]);
assert.equal(fromSrc.image.src,'http://server:9121/tmdb/image/t/p/w300/from-src.jpg','available native TMDB image wins even without poster_path');

assert.equal(context.Lampa.TMDB.image('t/p/w300//hash.jpg'),'http://server:9121/tmdb/image/t/p/w300/hash.jpg','double path separators from catalog are normalized');
