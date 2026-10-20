const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let observer;
const nodes = [];
let requests = 0;
let failed = false;
let storageListener;
const watched={};
let seasonIndex={};
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
const good = makeCard({id:85552,kinopoisk_id:'1178445',name:'Эйфория'}, 'https://image.tmdb.org/x.jpg');
const unknown = makeCard({id:999,name:'Unknown'}, 'https://image.tmdb.org/unknown.jpg');
const doc = {body:{nodeType:1,querySelectorAll:()=>[good.card,unknown.card]},
    documentElement:{contains: node=>nodes.includes(node)},querySelectorAll:()=>[]};
const listeners = {};
const context = {window:{}, document:doc, Date, setTimeout:()=>{}, setInterval:()=>{},
    Lampa:{Listener:{follow:(key,fn)=>{listeners[key]=fn;}},Storage:{get:()=>watched,listener:{follow:(key,fn)=>storageListener=fn}},Utils:{hash:value=>value}},
    Image: class {set src(value){requests++; if(failed)this.onerror();else this.onload();}},
    XMLHttpRequest: class {open(){} send(){this.status=200;this.responseText=JSON.stringify({paths:{},ids:{},imdb:{},seasons:seasonIndex});this.onload();}},
    MutationObserver:class {constructor(fn){observer=fn;} observe(){}}};
context.window.Lampa = context.Lampa;
vm.runInNewContext(fs.readFileSync('posters.js','utf8').replace('__POSTER_BASE__','http://server:9121'),context);
assert.equal(good.image.src,'http://server:9121/poster/kp/1178445.jpg?v=3&season=0');
assert.equal(unknown.image.src,'https://image.tmdb.org/unknown.jpg');
assert.equal(requests,1);
good.image.src='https://image.tmdb.org/native-retry.jpg';
observer([{type:'attributes',target:good.image}]);
assert.equal(good.image.src,'http://server:9121/poster/kp/1178445.jpg?v=3&season=0');
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
