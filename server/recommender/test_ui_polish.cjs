const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('kinopoisk.js','utf8');
let overlay=false,top=false,active,back=0,previous=0,closed=0,click;
let screens=[{component:'main'},{component:'full'}],replaced=[];
const registrations={};
const context={window:{},document:{querySelector:()=>overlay?{}:null,body:{classList:{contains:()=>false}},addEventListener:(type,fn,capture)=>{assert.equal(type,'click');assert.equal(capture,true);click=fn;}},
 Lampa:{Controller:{windowTop:()=>top,enabled:()=>active,toggle:name=>{active={controller:{back(){}}};},back:()=>back++},
 Activity:{all:()=>screens,active:()=>screens[screens.length-1],replace:(params,clear)=>{replaced.push({params,clear});screens=[params];},backward:()=>{if(screens.length>1)previous++;}},
 Storage:{field:()=> 'tmdb'},Lang:{translate:()=> 'Главная'},
 Select:{close:()=>closed++},Modal:{close:()=>closed++},Component:{add:(name,ctor)=>registrations[name]=ctor}}};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  function homeBack()'),source.indexOf('  function factsComponent('))+'\nfunction factsComponent(){}',context);
context.installHomeUiPolish();
assert(registrations.ai_facts && registrations.facts);
function press(target='.head__backward') {let prevented=0,stopped=0;click({target:{closest:s=>s===target?{}:null},button:0,preventDefault(){prevented++;},stopImmediatePropagation(){stopped++;}});return[prevented,stopped];}
active={name:'stale',controller:{}};
assert.deepEqual(press(),[1,1]);assert.equal(previous,1);assert.equal(back,0);
overlay=true;top={name:'modal'};press();assert.equal(back,1);assert.equal(previous,1,'close modal without navigating underneath');
top=false;active={controller:{}};press();assert.equal(closed,1,'legacy modal with lost focus closes');
assert.deepEqual(press('.unrelated'),[0,0]);
overlay=false;screens=[{component:'full',card:{id:42},method:'tv',season:2}];
press();
assert.equal(replaced.length,1,'single restored card returns home instead of native no-op');
assert.equal(replaced[0].params.component,'main');assert.equal(replaced[0].params.source,'tmdb');
assert.equal(replaced[0].clear,true,'clear card, method and season from replaced root');
assert.equal(previous,1,'do not call native backward at root');
press();assert.equal(replaced.length,1,'back on home must not recreate home');
screens=[{component:'ai_facts'}];overlay=true;top={name:'modal'};
press();assert.equal(replaced.length,1,'root fallback must not navigate beneath modal');
overlay=false;top=false;screens=[{component:'main'},{component:'full'}];
assert(source.includes('.full-start__rate.button--roman-kp-rating') && source.includes('min-height:1.5em') && source.includes('white-space:nowrap'));
console.log('UI: header back with stale focus, restored root, home no-op, overlay closure, one action per click, rating sizing and facts route passed');
// Exercise the custom facts component lifecycle with the same public Lampa APIs.
class Q {
 constructor(nodes){this.nodes=nodes||[];this.length=this.nodes.length;this.nodes.forEach((n,i)=>this[i]=n);}
 append(value){this.nodes[0].children.push(...value.nodes);return this;}
 appendTo(q){q.append(this);return this;}
 text(value){if(value===undefined)return this.nodes.map(n=>n.text||'').join('');this.nodes.forEach(n=>n.text=value);return this;}
 empty(){this.nodes.forEach(n=>n.children=[]);return this;}
 find(){const out=[];function walk(n){n.children.forEach(c=>{if(c.selector)out.push(c);walk(c);});}this.nodes.forEach(walk);return new Q(out);}
 eq(i){return new Q(this.nodes[i]?[this.nodes[i]]:[]);}
 index(node){return this.nodes.indexOf(node);}
 on(name,fn){this.nodes.forEach(n=>n.events[name]=fn);return this;}
 trigger(name){this.nodes.forEach(n=>n.events[name]&&n.events[name].call(n));return this;}
 hide(){return this;}
 toggle(){return this;}
 remove(){this.nodes.forEach(n=>n.removed=true);}
}
const $=value=>new Q([{selector:/\bselector\b/.test(value),children:[],events:{},markup:value}]);
let request,controller,scrollDestroyed=0;
Object.assign(context,{$,reviewForCard:()=>({}),reviewBase:'http://catalog/p/profile',XMLHttpRequest:class{
 open(method,url){request=url;}send(){this.status=200;this.responseText=JSON.stringify({items:[{text:'Факт <b>не HTML</b> о съёмках.'}],source_url:'https://www.kinopoisk.ru/series/42/didyouknow/'});this.onload();}abort(){}
}});
context.Lampa.InteractionCategory=function(){};
context.Lampa.Scroll=function(){const node=$('<div>');this.append=value=>node.append(value);this.height=()=>{};this.render=()=>node;this.update=()=>{};this.destroy=()=>scrollDestroyed++;};
context.Lampa.Controller.add=(name,value)=>controller=value;
context.Lampa.Controller.toggle=()=>controller&&controller.toggle();
context.Lampa.Controller.collectionSet=()=>{};context.Lampa.Controller.collectionFocus=()=>{};
let activity={loader(){},toggle(){}};context.Lampa.Activity.active=()=>({activity});
vm.runInContext(source.slice(source.indexOf('  function factsComponent('),source.indexOf('  function start() {')),context);
const comp=context.factsComponent({card:{kinopoisk_id:42,name:'Сериал'}});comp.activity=activity;comp.create();
assert.equal(request,'http://catalog/p/profile/facts/kp/42.json?type=tv');
assert(comp.render().find().nodes.some(n=>n.children.some(c=>c.text==='Факт <b>не HTML</b> о съёмках.')),'facts are inserted as text, never trusted HTML');
controller.back();assert.equal(previous,2);comp.destroy();assert.equal(scrollDestroyed,1);
console.log('Facts component: profile URL, native lifecycle, text rendering, controller back and cleanup passed');
