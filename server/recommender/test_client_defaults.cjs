const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync('client-defaults.js','utf8');
function run(android){
 const values={};
 const context={window:null,Lampa:{Storage:{get:(k,d)=>k in values?values[k]:d,set:(k,v)=>values[k]=v},Platform:{is:p=>android && p==='android'}}};
 context.window=context;vm.createContext(context);
 // Lampa's native Android defaults are external torrent handler and player.
 const native={source:'tmdb',internal_torrclient:!android,player:android?'android':'inner',player_torrent:android?'android':'inner'};
 const field=k=>k in values?values[k]:native[k];
 assert.equal(field('source'),'tmdb');
 if(android)assert.equal(field('internal_torrclient'),false);
 vm.runInContext(code,context);
 assert.equal(field('source'),'cub');
 if(android){
  assert.equal(field('internal_torrclient'),true);
  assert.equal(field('player'),'android');
  assert.equal(field('player_torrent'),'android');
  assert.equal(values.torrserver_url,'http://127.0.0.1:8090');
 }else assert(!('player' in values),'Windows MPV preferences were changed');
 values.player_torrent='inner';values.source='cub';vm.runInContext(code,context);
 assert.equal(field('source'),'cub');
 assert.equal(field('player_torrent'),'inner');
}
run(true);run(false);console.log('Fresh Android: CUB + remote TorrServer + Android chooser; Windows untouched: passed');
