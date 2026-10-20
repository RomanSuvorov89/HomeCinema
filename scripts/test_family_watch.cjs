const {execFileSync}=require('child_process'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const code=execFileSync('python3',['-c',"import runpy,sys; print(runpy.run_path(sys.argv[1])['SCRIPT'])",path.join(__dirname,'fix-family-watch.py')],{encoding:'utf8'}).replace('__HOST__',JSON.stringify('http://cinema.test:19118')).replace('__TOKEN__',JSON.stringify('test-family'));
const values={lampac_profile_id:'family',online_watched_last:{series:{season:2,episode:2}},online_view:{x:1}},timers=new Map(),requests=[];
let listener,id=0;
const context={window:null,console,JSON,setTimeout:fn=>{timers.set(++id,fn);return id;},clearTimeout:n=>timers.delete(n),
 Lampa:{Storage:{get:(k,d)=>k in values?values[k]:d,set:(k,v)=>values[k]=v,listener:{follow:(event,fn)=>listener=fn}}},
 XMLHttpRequest:function(){this.open=(method,url)=>{this.method=method;this.url=url;};this.send=data=>{this.body=JSON.parse(data);requests.push(this);};}};
context.window=context;vm.runInNewContext(code,context);
const flush=()=>{const [key,fn]=timers.entries().next().value;timers.delete(key);fn();};
assert.equal(requests.length,0,'startup must not publish old progress');
listener({name:'favorite'});assert.equal(timers.size,0);
listener({name:'online_watched_last'});listener({name:'online_watched_last'});assert.equal(timers.size,1);flush();
assert.equal(requests.length,1);assert(requests[0].url.includes('pathfile=family'));assert(requests[0].url.includes('token=test-family'));assert.equal(requests[0].body.online_watched_last.series.episode,2);
values.online_watched_last.series.episode=3;listener({name:'online_watched_last'});flush();assert.equal(requests.length,1,'serialize requests');
requests[0].status=200;requests[0].responseText=JSON.stringify({success:true,fileInfo:{changeTime:100}});requests[0].onload();assert.equal(values.lampac_sync_view,100);flush();assert.equal(requests.length,2);assert.equal(requests[1].body.online_watched_last.series.episode,3);
values.lampac_profile_id='other';requests[1].status=200;requests[1].responseText=JSON.stringify({success:true,fileInfo:{changeTime:200}});requests[1].onload();assert.equal(values.lampac_sync_view,100,'old profile response must not stamp new profile');
console.log('Family Watch: no startup export, debounce, latest episode, serialized requests and profile guard passed');
