const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert/strict');
const root=path.join(__dirname,'..'),css=fs.readFileSync(path.join(root,'themes/apple-tv.css'),'utf8');
const code=fs.readFileSync(path.join(root,'themes/apple-tv.js'),'utf8').replace('__HOMECINEMA_APPLE_CSS__',JSON.stringify(css));
const values={unrelated_setting:'preserve'},nodes={},classes=new Set(),registered=[];
const ctx={window:null,document:{body:{classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)}},
 getElementById:id=>nodes[id],createElement:()=>({}),head:{appendChild(node){nodes[node.id]=node;node.parentNode={removeChild:n=>delete nodes[n.id]};}}},
 setTimeout(){throw Error('Unexpected polling after API is ready');},
 Lampa:{Storage:{get:(k,d)=>k in values?values[k]:d,set:(k,v)=>values[k]=v},SettingsApi:{addParam:arg=>registered.push(arg)}}};
ctx.window=ctx;vm.createContext(ctx);vm.runInContext(code,ctx);
assert(classes.has('homecinema-apple'));assert.equal(Object.keys(nodes).length,1);assert.equal(registered.length,1);
assert.equal(registered[0].component,'interface');
registered[0].onChange('original');assert(!classes.has('homecinema-apple'));assert.equal(Object.keys(nodes).length,0);
registered[0].onChange('apple');assert(classes.has('homecinema-apple'));assert.equal(Object.keys(nodes).length,1);
vm.runInContext(code,ctx);assert.equal(registered.length,1);assert.equal(Object.keys(nodes).length,1);
ctx.HomeCinemaAppleTheme.setEnabled(false);assert(!classes.has('homecinema-apple'));
assert.equal(values.unrelated_setting,'preserve');assert.equal(Object.keys(values).length,2);
// A saved choice survives a page reload and does not re-enable the theme.
delete ctx.HomeCinemaAppleTheme;vm.runInContext(code,ctx);assert(!classes.has('homecinema-apple'));
console.log('Apple appearance: default, settings toggle, offline disable, reload preference and idempotence passed');
