const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('profiles-client.js.template','utf8');
let status={configured:false,connected:false},menus=[],modals=[],inputs=[],calls=[],intervals=[],syncs=0,closed=0,legacy=false;
class Q {
 constructor(markup){this.markup=markup;this.children=[];this.attrs={};this.value='';this[0]={focus(){}};}
 attr(k,v){this.attrs[k]=v;return this;}appendTo(q){q.children.push(this);return this;}
 text(v){this.textValue=v;return this;}on(){return this;}val(v){if(v===undefined)return this.value;this.value=v;return this;}
}
const context={Promise,Date,Math,encodeURIComponent,base:'http://catalog.home:9120',busy:false,
 $:s=>new Q(s),device:()=> 'pc',read:(k)=>k==='torrserver_url'?'http://ts.home:8090':'',returnHead(){},
 notify(){},menu(){},sync:()=>{syncs++;return Promise.resolve();},window:{location:{reload(){}}},
 setInterval:fn=>{intervals.push(fn);return intervals.length;},clearInterval(){},
 Lampa:{Input:{edit:(options,done)=>inputs.push({options,done})},Modal:{open:options=>modals.push(options),close:()=>closed++},Select:{show:options=>menus.push(options)}},
 request:(path,payload)=>{calls.push({path,payload});let result={};
  if(path==='/cloud/status.json')result=status;
  if(path==='/cloud/connect.json')result={user_code:'ABC123',verification_url:'https://oauth.yandex.ru/device',expires_in:300,interval:5};
  if(path==='/cloud/poll.json')result={connected:true};
  if(path==='/cloud/versions.json')result={items:[{name:'backup.hcb',size:1024,modified:'2026-10-22'}]};
  if(path==='/cloud/preview.json')result=legacy && !payload.password?{password_required:true}:{ticket:'one-time',profiles:2,ratings:100};
  return Promise.resolve(result);
 }};
vm.createContext(context);vm.runInContext(source.slice(source.indexOf('    var cloudTimer='),source.indexOf('    function menu()')),context);
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 let readyCallback,shown=0,seen=false;
 context.stored=()=>seen;context.persist=()=>{seen=true;};context.Lampa.Listener={follow:(name,fn)=>readyCallback=fn};
 const originalMenu=context.cloudMenu;context.cloudMenu=()=>shown++;
 context.firstRunCloud({needs_setup:true});assert.equal(shown,0,'setup waits for native app readiness');
 readyCallback({type:'ready'});readyCallback({type:'ready'});assert.equal(shown,1,'setup opens once after app ready');
 context.cloudMenu=originalMenu;
 context.cloudMenu();await tick();menus.at(-1).onSelect({action:'connect'});
 assert.equal(inputs.length,1,'only nonsecret ClientID uses native keyboard');
 inputs[0].done('c'.repeat(32));
 const secretModal=modals.at(-1);assert(secretModal.html.markup.includes('type="password"'));
 secretModal.html.value='s'.repeat(32);secretModal.buttons[0].onSelect();await tick();
 assert.equal(inputs.length,1,'secret never reaches logging native Lampa keyboard');
 assert.equal(secretModal.html.value,'','secret field cleared after submit');
 const qr=modals.at(-1);assert.equal(qr.html.children[0].attrs.src,'http://catalog.home:9120/cloud/qr.svg');
 assert.equal(qr.html.children[2].textValue,'ABC123');
 status={configured:true,connected:true,enabled:false};intervals.at(-1)();await tick();
 assert(menus.at(-1).items.some(i=>i.action==='enable'));
 assert(!calls.some(c=>c.path==='/cloud/enable.json'),'connecting alone cannot start cloud writes');
 context.cloudVersions();await tick();menus.at(-1).onSelect({file:'backup.hcb'});
 await tick();
 assert(!calls.find(c=>c.path==='/cloud/preview.json').payload.password,'new copies need only Yandex authorization');
 assert.equal(inputs.length,1);
 const preview=menus.at(-1);assert(preview.title.includes('2 профилей'));preview.onSelect({restore:true});await tick();
 assert.equal(context.busy,true,'old client is stopped before restoration');
 assert.equal(calls.find(c=>c.path==='/cloud/restore.json').payload.ticket,'one-time');
 status={connected:true,configured:true,enabled:true};context.cloudMenu();await tick();menus.at(-1).onSelect({action:'save'});await tick();
 assert(syncs>0,'flush profile before backup');
 assert.equal(calls.find(c=>c.path==='/cloud/device.json').payload.values.torrserver_url,'http://ts.home:8090');
 context.cloudMenu();await tick();menus.at(-1).onSelect({action:'enable'});await tick();
 assert.equal(calls.find(c=>c.path==='/cloud/enable.json').payload.mode,'yandex');
 assert(!('password' in calls.find(c=>c.path==='/cloud/enable.json').payload));
 legacy=true;context.cloudVersions();await tick();menus.at(-1).onSelect({file:'old.hcb'});await tick();
 const password=modals.at(-1);assert(password.title.includes('старой копии'));
 password.html.value='old recovery password';password.buttons[0].onSelect();await tick();
 assert.equal(calls.filter(c=>c.path==='/cloud/preview.json').at(-1).payload.password,'old recovery password');
 console.log('Cloud UI: QR/device code, secrets outside native keyboard, no implicit writes, restore confirmation, profile flush and DNS settings passed');
})().catch(e=>{console.error(e);process.exit(1);});
