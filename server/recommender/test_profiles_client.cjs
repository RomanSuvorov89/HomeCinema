const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const code=fs.readFileSync('profiles-client.js.template','utf8').replace('__RECOMMENDER_PUBLIC_URL__','http://server:9120');
const data=new Map(),states=new Map(),requests=[];
const people=[{id:'owner',name:'Main',owner:true,lampac_profile_id:''},{id:'hc_other',name:'Second',owner:false,lampac_profile_id:'hc_other'}];
let reloads=0,offline=false,generation='';
function json(value){return JSON.parse(JSON.stringify(value));}
function page(){
 const nodes={},events={},intervals=[];
 const localStorage={getItem:k=>data.has(k)?data.get(k):null,setItem:(k,v)=>data.set(k,String(v)),removeItem:k=>data.delete(k)};
 // Object.keys(localStorage) must see stored keys, just like a browser Storage object.
 const ls=new Proxy(localStorage,{ownKeys:()=>[...data.keys()],getOwnPropertyDescriptor:()=>({enumerable:true,configurable:true})});
 const reserve={file_view:{legacy:{updated:10,percent:100}}};
 const Storage={get:(key,fallback)=>{let raw=localStorage.getItem(key);if(raw===null && key in reserve)return reserve[key];if(!raw)return fallback===undefined?'':fallback;try{return JSON.parse(raw);}catch{return raw;}},
  set:(key,value)=>localStorage.setItem(key,typeof value==='object'?JSON.stringify(value):String(value)),listener:{follow:(name,fn)=>events.storage=fn}};
 const node=()=>({attrs:{},handlers:{},nativeHandlers:1,children:[],setAttribute(k,v){this.attrs[k]=v;},
  querySelector(){return this.children.find(n=>n.className==='homecinema-bell-count');},appendChild(n){this.children.push(n);},
  addEventListener(name,fn,capture){assert.equal(capture,true);this.handlers[name]=fn;},
  cloneNode(){const copy=node();copy.nativeHandlers=0;return copy;},classList:{add(){},toggle(){}}});
 nodes.profile=node();nodes.bell=node();
 for(const key of ['profile','bell'])nodes[key].parentNode={replaceChild(copy,old){assert.equal(old,nodes[key]);copy.parentNode=this;nodes[key]=copy;}};
 const styles=[];
 const context={window:null,localStorage:ls,JSON,Promise,Math,Date,console,
  setTimeout:fn=>{throw Error('Unexpected wait');},setInterval:fn=>intervals.push(fn),
  document:{body:{},head:{appendChild(n){styles.push(n.textContent);}},hidden:false,createElement:node,querySelector:s=>s.includes('profile')?nodes.profile:nodes.bell,
   addEventListener:(name,fn,capture)=>{events[name]=fn;if(name==='lwsEvent')assert.equal(capture,true);}},
  $:arg=>typeof arg==='string' ? {each(fn){fn.call(arg.includes('profile')?nodes.profile:nodes.bell);}} : {off(){return this;},on(name,fn){arg.handlers[name]=fn;return this;}},
  Lampa:{Storage,Noty:{show(){}},Controller:{toggle(){}},Select:{show:menu=>context.menu=menu},Player:{opened:()=>false},Favorite:{read(){}},Input:{edit:(options,done)=>context.inputDone=done}},
  location:{reload:()=>reloads++},
  XMLHttpRequest:function(){this.open=(method,url)=>{this.method=method;this.url=url;};this.setRequestHeader=()=>{};
   this.send=body=>{
    const url=new URL(this.url),payload=body?JSON.parse(body):null;requests.push({method:this.method,path:url.pathname,payload});
    let result;
    if(offline){this.status=503;result={error:'offline'};}
    else {
     this.status=200;
     if(url.pathname==='/profiles.json'){if(payload && payload.action==='rename'){people.find(p=>p.id===payload.profile_id).name=payload.name;result={ok:true};}else result={owner_id:'owner',profiles:people,generation:generation};}
     else if(url.pathname==='/profile-state.json'){
      const id=payload?payload.profile_id:url.searchParams.get('id');
      let state=states.get(id)||{profile_id:id,revision:0,values:{}};
      if(payload){state={profile_id:id,revision:state.revision+1,values:Object.assign({},state.values,payload.values)};states.set(id,json(state));}
      result=state;
     } else if(url.pathname==='/cloud/device-restore.json') result={values:{torrserver_url:'http://ts.home:8090'}};
     else result={items:[]};
    }
    this.responseText=JSON.stringify(result);this.onload();
   };}};
 context.window=context;
 vm.runInNewContext(code,context);
 return {context,api:context.HomeCinemaProfiles,Storage,events,intervals,nodes};
}
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 data.set('favorite',JSON.stringify({card:[{id:42}],history:[42]}));data.set('homecinema_appearance','apple');
 data.set('interface_sound_level','0');data.set('subtitles_start','false');
 data.set('torrserver_password','device-secret');data.set('roman_card_ratings_v10','old-personal-ratings');
 const first=page();await tick();
 assert.equal(first.api.apiBase(),'http://server:9120/p/owner');
 assert.deepEqual(states.get('owner').values.file_view,{legacy:{updated:10,percent:100}},'IndexedDB-backed history is captured via Lampa.Storage');
 assert.equal(states.get('owner').values.interface_sound_level,0);
 assert.equal(states.get('owner').values.subtitles_start,false);
 assert(!('torrserver_password' in states.get('owner').values),'device secrets never uploaded');
 await first.api.switchTo(people[1]);assert.equal(reloads,1);
 assert.equal(first.Storage.get('lampac_profile_id',''),'', 'old page keeps old identity until reload');
 const second=page();await tick();
 assert.equal(second.Storage.get('lampac_profile_id',''),'hc_other');
 assert.equal(second.Storage.get('torrserver_password',''),'device-secret');
 assert.equal(second.Storage.get('roman_card_ratings_v10',''),'','old personal cache cleared');
 assert.deepEqual(second.Storage.get('favorite',{}),{},'new user must not inherit history');
 assert.deepEqual(second.Storage.get('file_view',{}),{},'old IndexedDB reserve must be shadowed by explicit empty value');
 assert.equal(states.get('hc_other').values.favorite,'','new profile seed never contains owner history');
 let blocked=false;second.events.lwsEvent({detail:{name:'bookmark',data:JSON.stringify({profile_id:''})},stopImmediatePropagation:()=>blocked=true});
 assert(blocked,'unscoped bookmark websocket event cannot cross profiles');
 blocked=false;second.events.lwsEvent({detail:{name:'bookmark',data:JSON.stringify({profile_id:'hc_other'})},stopImmediatePropagation:()=>blocked=true});assert(!blocked);
 const remote=states.get('hc_other');remote.values.homecinema_appearance='original';
 await second.api.save();assert.equal(second.Storage.get('homecinema_appearance'),'original','unchanged local settings pull remote changes');
 offline=true;
 await assert.rejects(second.api.switchTo(people[0]),/offline/);assert.equal(reloads,1,'failed save cancels switching');
 assert.equal(second.Storage.get('lampac_profile_id',''),'hc_other');offline=false;
 await second.api.switchTo(people[0]);assert.equal(reloads,2);
 const third=page();await tick();
 assert.equal(third.Storage.get('lampac_profile_id',''),'');
 assert.equal(third.Storage.get('favorite',{}).history[0],42,'owner history restored');
 assert.equal(third.Storage.get('homecinema_appearance'),'apple','owner theme restored');
 assert.equal(third.nodes.profile.nativeHandlers,0,'native CUB handlers removed independently of jQuery instance');
 third.nodes.profile.handlers['click']({preventDefault(){},stopImmediatePropagation(){}});
 const opened=third.context.menu;
 third.nodes.profile.handlers['hover:enter']();
 assert.equal(third.context.menu,opened,'click followed by synthesized enter opens only one menu');
 assert.equal(third.context.menu.title,'Кто смотрит?');
 third.context.menu.onSelect(third.context.menu.items.find(i=>i.action==='rename'));
 third.context.inputDone('New name');await tick();
 assert.equal(third.nodes.profile.attrs.title,'New name');
 assert.equal(third.Storage.get('lampac_profile_id',''),'','renaming keeps the original sync namespace');
 third.nodes.bell.handlers['hover:enter']();assert.equal(third.context.menu.title,'Уведомления');
 assert.equal(third.nodes.bell.children.length,1,'badge belongs to the bell, polling does not duplicate it');
 assert.equal(third.nodes.bell.children[0].attrs['aria-hidden'],'true');
 generation='restored-epoch';
 states.set('owner',{profile_id:'owner',revision:100,values:{favorite:{card:[{id:999}],history:[999]},homecinema_appearance:'apple',source:'cub'}});
 const restored=page();await tick();
 assert.deepEqual(restored.Storage.get('favorite',{}),{card:[{id:999}],history:[999]},'restored server state wins over old local history before seeding');
 assert.equal(restored.Storage.get('torrserver_url',''),'http://ts.home:8090','DNS service address restored on new epoch');
 assert.equal(data.get('homecinema_cloud_epoch_v1'),JSON.stringify(generation));
 assert.equal(requests.at(-1).payload?.seed,undefined,'restored page does not seed stale snapshot');
 console.log('Profiles client: initial migration, IndexedDB reads, isolation, reload boundary, device secrets, caches, websocket scope, remote settings and failed-switch recovery passed');
})().catch(error=>{console.error(error);process.exit(1);});
