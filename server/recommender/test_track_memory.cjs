const fs=require('fs'),vm=require('vm'),assert=require('assert');
const events={};
const listener={follow(name,fn){events[name]=fn;}};
const ctx={window:{},console,Promise,setTimeout,clearTimeout,setInterval(){},
 Lampa:{Listener:listener,Player:{listener},PlayerVideo:{listener},Activity:{active(){return {};}}}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('track-memory.js','utf8'),ctx);
const p=ctx.window.RomanTrackMemory;
const forced={id:1,lang:'ru',title:'Forced',forced:true};
const full={id:2,lang:'ru-RU',title:'Дорожка 2'};
assert.equal(p.choose([forced,full],'sub').id,2);
assert.equal(p.choose([forced],'sub'),null);
const preferred={id:9,lang:'rus',title:'LostFilm AC3 5.1'};
const other={id:1,lang:'ru',title:'Дубляж'};
assert.equal(p.choose([preferred,other],'audio').id,1);
const saved=p.descriptor(preferred);
assert.equal(p.choose([{id:3,lang:'ru-RU',title:'LostFilm AAC 2.0'},other],'audio',saved).id,3);
assert.equal(p.choose([other],'audio',saved).id,1);
assert.equal(saved.title,'lostfilm');
assert.equal(p.choose([full],'sub',{off:true}),null);
assert.equal(p.choose([{id:4,lang:'en'}],'audio'),undefined);
assert.equal(p.seriesKey({media_type:'tv',kinopoisk_id:123}),'kp:tv:123');
assert.equal(p.seriesKey({media_type:'movie',kinopoisk_id:123}),'');
console.log('Track policy: semantic match, missing track fallback, Russian full, manual off passed');
async function integration() {
  const writes=[];
  ctx.window.RomanTracksApi='http://test';
  ctx.fetch=(url,options)=>Promise.resolve({ok:true,json:()=>Promise.resolve(options.method==='POST' ?
    (writes.push(JSON.parse(options.body)),{ok:true}) : {preferences:{audio:saved}})});
  const c=p.begin({movie:{kinopoisk_id:123,media_type:'tv'}});
  await c.ready;
  let selection;
  const apply=x=>{selection=x;return Promise.resolve();};
  const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
  p.mpv({duration:100,tracks:[{...other,type:'audio'},{...full,type:'sub'}],aid:1,sid:2},apply);
  await tick();assert.equal(selection.aid,1);assert.equal(selection.sid,2);assert.equal(writes.length,0);
  p.mpv({duration:100,tracks:[{...other,type:'audio'},{...full,type:'sub'}],aid:1,sid:2},apply);
  await tick();assert.equal(writes.length,0);assert.equal(c.prefs.audio.title,'lostfilm');
  p.mpv({duration:100,tracks:[{...other,type:'audio'},{...preferred,type:'audio'},{...full,type:'sub'}],aid:9,sid:false},apply);
  await tick();assert.equal(writes.length,2);assert.equal(writes[0].descriptor.title,'lostfilm');
  assert.equal(writes[1].descriptor.off,true);
  assert.equal(writes[0].series_key,'kp:tv:123');
  console.log('MPV integration: fallback is not saved, manual changes are saved per series');
}
integration().catch(e=>{console.error(e);process.exitCode=1;});
