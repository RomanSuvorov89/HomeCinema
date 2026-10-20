const fs=require('fs'), vm=require('vm'), assert=require('assert/strict');
const path=require('path'),{execFileSync}=require('child_process');
const code=execFileSync('python3',['-c',"import runpy,sys; print(runpy.run_path(sys.argv[1])['SCRIPT'])",path.join(__dirname,'fix-lampa-prefetch.py')],{encoding:'utf8'});
function setup(type, modern=false){
 let now=2000,bottom=800,count=3,control=(type==='main'?'items_line':'content'), pending=[],focus=0,events=[];
 const body={getBoundingClientRect:()=>({bottom})};
 const scroll={querySelector:()=>body,getBoundingClientRect:()=>({top:0,bottom:1000})};
 const root={nodeType:1,classList:{contains:()=>false},querySelector:()=>scroll,querySelectorAll:()=>Array(count)};
 const comp={render:()=>root};
 if(modern){comp.items=[{}];comp.scroll={};comp.loaded=[];comp.emit=function(event,success,failure){events.push(event);if(event==='loadNext'){if(this.next_wait)return;this.next_wait=true;this.emit('next',data=>{this.next_wait=false;this.loaded.push(data);},()=>{this.next_wait=false;});}if(event==='next')pending.push({success,failure});if(event==='pushLoaded'){this.loaded.shift();bottom+=1000;count+=6;}};}
 else if(type==='main') {comp.next=(success,failure)=>pending.push({success,failure});comp.loadNext=function(){if(this.next_wait)return;this.next_wait=true;this.next(rows=>{this.next_wait=false;bottom+=1000;count+=rows.length*6;},()=>{this.next_wait=false;});};}
 else{let page=1,busy=false;comp.nextPageReuest=(params,success,failure)=>pending.push({params,success,failure});comp.next=function(){if(busy)return;busy=true;this.nextPageReuest({page:++page},data=>{busy=false;bottom+=1000;count+=data.results.length;},()=>{busy=false;});};}
 if(type==='roman_recommendation_review'){let saved=comp.nextPageReuest;Object.defineProperty(comp,'nextPageReuest',{get:()=>saved,set:fn=>{saved=function(){return fn.apply(this,arguments);};},configurable:true});}
 const active={component:type,activity:{component:comp}};
 const context={window:{innerHeight:1000},document:{hidden:false,documentElement:{contains:()=>true}},Lampa:{Activity:{active:()=>active},Listener:{follow(){}},Controller:{enabled:()=>({name:control}),collectionFocus:()=>{focus++;}},Layer:{visible(){}}},Date:{now:()=>now},console,setInterval:()=>{},setTimeout:()=>{}};context.window.Lampa=context.Lampa;
 vm.runInNewContext(code,context);
 return {pending,comp,context,events,tick:()=>{now+=700;context.window.romanPrefetchV1.check();},setBottom:x=>bottom=x,control:x=>control=x,active,focus:()=>focus};
}
// Home starts the next section without a key press; a slow response is never duplicated.
let h=setup('main');assert.equal(h.pending.length,1);h.tick();h.tick();assert.equal(h.pending.length,1);h.pending.shift().success([{}]);h.tick();assert.equal(h.pending.length,1);h.pending.shift().success([{}]);h.tick();assert.equal(h.pending.length,0,'one-screen reserve stops further downloads');assert.equal(h.focus(),0);
// More/list requests the next page while there is still visible content.
let g=setup('roman_recommendation_review');assert.equal(g.pending[0].params.page,2);for(let i=0;i<20;i++)g.tick();assert.equal(g.comp.romanPrefetchState.pending,1,'descriptor wrappers must not accumulate');g.pending.shift().success({results:Array(12),page:2,total_pages:3});g.setBottom(2500);g.tick();assert.equal(g.pending.length,0);g.setBottom(1500);g.tick();assert.equal(g.pending[0].params.page,3);g.pending.shift().success({results:[{}],page:3,total_pages:3,nomore:true});g.setBottom(700);g.tick();assert.equal(g.pending.length,0,'explicit end prevents requests');
// New Lampa: render buffered data even with no scroll animation.
let m=setup('main',true);assert.equal(m.pending.length,1);m.pending.shift().success([{}]);m.tick();assert.ok(m.events.includes('pushLoaded'));assert.equal(m.comp.loaded.length,0);
// Failure backs off; menus and hidden tabs do not fetch.
let f=setup('main');f.pending.shift().failure();f.tick();assert.equal(f.pending.length,0);f.control('menu');f.setBottom(100);for(let i=0;i<30;i++)f.tick();assert.equal(f.pending.length,0);f.control('content');f.context.document.hidden=true;f.tick();assert.equal(f.pending.length,0);f.context.document.hidden=false;f.tick();assert.equal(f.pending.length,1);
// Non-list screens never call next, including video/torrent screens.
let n=setup('full');assert.equal(n.pending.length,0);n.tick();assert.equal(n.pending.length,0);
console.log('Passed: initial home prefetch, one-screen reserve, pagination, in-flight guard, end-of-list, buffered rows, failure backoff, inactive screens and unchanged focus.');
