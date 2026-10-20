const fs=require('fs'),vm=require('vm'),assert=require('assert');
const s=fs.readFileSync('kinopoisk.js','utf8');
const code=s.slice(s.indexOf('  function installTailLoading('),s.indexOf('  function reviewComponent('));
let spinner=0,blocking=0,cards=0,complete;
const root={find(){return {first(){return {length:0};}};},append(){spinner++;}};
function Native(){this.render=()=>root;this.build=data=>{cards+=data.results.length;};this.loading=value=>{if(value)blocking++;};this.destroy=()=>{};this.nextPageReuest=(params,done)=>complete=done;}
const ctx={Object,Array,document:{getElementById(){return false;},createElement(){return {};},head:{appendChild(){}}},Lampa:{InteractionCategory:Native},$:()=>({remove(){spinner--;}})};
vm.createContext(ctx);vm.runInContext(code,ctx);ctx.installTailLoading();ctx.installTailLoading();
const comp=new ctx.Lampa.InteractionCategory({});comp.loading(true);assert.equal(blocking,1,'first load remains native');
comp.build({results:[{id:1}]});comp.loading(true);assert.equal(blocking,1);assert.equal(cards,1);assert.equal(spinner,1);
comp.nextPageReuest({page:2},data=>comp.build(data));assert.equal(spinner,1);assert.equal(cards,1,'existing cards remain');
complete({results:[{id:2}]});assert.equal(spinner,0);assert.equal(cards,2);
// Assignment after construction (custom AI component) must also be decorated.
comp.nextPageReuest=(params,done)=>complete=done;
comp.nextPageReuest({page:3},()=>{});assert.equal(spinner,1);complete({results:[]});assert.equal(spinner,0);
comp.nextPageReuest({page:4},()=>{});comp.destroy();assert.equal(spinner,0);
console.log('Tail loader: cards preserved, first/native loading, async pages, late method assignment and cleanup: passed');
