const fs=require('fs'),vm=require('vm'),assert=require('assert');
const template=fs.readFileSync('client-bootstrap.js.template','utf8');
const block=template.split('/* homecinema-local-reactions:start */')[1].split('/* homecinema-local-reactions:end */')[0];
let observer,callbacks=0,errors=0,context;
function image(src){return {nodeType:1,tagName:'IMG',value:src,
 getAttribute(){return this.value;},setAttribute(k,v){this.value=v;},querySelectorAll(){return [];}};}
const original=function(img,src,ok,fail){context=this;img.src=src;img.onload=()=>ok&&ok(img);img.onerror=()=>{img.src='./img/img_broken.svg';fail&&fail(img);};return 'native';};
const existing=image('http://cinema/cub/red/img/reactions/fire.svg');
const body={nodeType:1,tagName:'BODY',querySelectorAll:()=>[existing]};
const ctx={window:null,Lampa:{Utils:{imgLoad:original}},document:{body},MutationObserver:class{
 constructor(callback){observer=callback;}observe(target,options){assert.equal(target,body);assert.deepEqual(options.attributeFilter,['src']);}
}};
ctx.window=ctx;vm.createContext(ctx);vm.runInContext(block+';localReactions();',ctx);
const wrapper=ctx.Lampa.Utils.imgLoad;
const sources=[];
for(const type of ['fire','nice','think','bore','shit']){
 const img={},receiver={};
 assert.equal(wrapper.call(receiver,img,'https://cub.best/img/reactions/'+type+'.svg?x=1',()=>callbacks++,()=>errors++),'native');
 assert.equal(context,receiver);
 assert(img.src.startsWith('data:image/svg+xml;charset=utf-8,'));
 const svg=decodeURIComponent(img.src.split(',')[1]);
 assert(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"'));assert(svg.endsWith('</svg>'));
 assert(!/https?:\/\//.test(svg.replace('http://www.w3.org/2000/svg','')),'icons have no external resources');
 sources.push(img.src);img.onload();
}
assert.equal(new Set(sources).size,5);assert.equal(callbacks,5);assert.equal(errors,0);
assert.equal(existing.value,sources[0]);
const unrelated={};wrapper(unrelated,'https://image.example/poster.jpg',null,()=>errors++);
assert.equal(unrelated.src,'https://image.example/poster.jpg');unrelated.onerror();assert.equal(errors,1);
const unknown={};wrapper(unknown,'https://cub.best/img/reactions/unknown.svg');assert.equal(unknown.src,'https://cub.best/img/reactions/unknown.svg');
const picker=image('http://cinema/cub/red/img/reactions/nice.svg');
observer([{type:'childList',addedNodes:[picker]}]);assert.equal(picker.value,sources[1]);
picker.value='https://cub.best/img/reactions/think.svg';observer([{type:'attributes',target:picker}]);assert.equal(picker.value,sources[2]);
observer([{type:'attributes',target:picker}]);assert.equal(picker.value,sources[2],'inline image does not cause an observer loop');
vm.runInContext('localReactions();',ctx);assert.equal(ctx.Lampa.Utils.imgLoad,wrapper,'initialization is idempotent');
console.log('Local reactions: all five icons, proxied/direct URLs, picker, callbacks and unrelated images passed');
