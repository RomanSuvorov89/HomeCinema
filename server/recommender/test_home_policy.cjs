const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('kinopoisk.js','utf8');
const values={},favorites={},events={},registry={},styles=[],cards=[];
let active={component:'main'},writes=0;
class Element{
 constructor(cls=''){this.className=cls;this.children=[];this.textContent='';this.classList={
 add:c=>{if(!this.className.split(' ').includes(c))this.className+=' '+c;},
 remove:c=>this.className=this.className.split(' ').filter(x=>x!==c).join(' '),
 toggle:(c,on)=>on?this.classList.add(c):this.classList.remove(c)};}
 appendChild(child){child.parent=this;this.children.push(child);}
 querySelector(selector){const name=selector.slice(1);for(const c of this.children){if(c.className.split(' ').includes(name))return c;const found=c.querySelector(selector);if(found)return found;}return null;}
 remove(){this.parent.children=this.parent.children.filter(x=>x!==this);}
}
function Native(object){
 this.cardID=()=>object.movie.id+':tv';
 this.getFilterData=()=>values.torrents_filter_data[this.cardID()]||values.torrents_filter||{};
 this.setFilterData=filter=>{values.torrents_filter_data[this.cardID()]=filter;values.torrents_filter=filter;};
}
registry.torrents=Native;values.torrents_filter_data={};
const ctx={window:{},document:{body:new Element(),head:{appendChild:s=>styles.push(s)},createElement:()=>new Element(),querySelectorAll:()=>cards},
 reviewForCard:card=>card.review||{},ratingKey:card=>String(card.id),cacheGet:()=>null,data:null,
 Lampa:{Storage:{get:(k,d)=>values[k]||d,set:(k,v)=>{writes++;values[k]=v;},listener:{follow:(key,fn)=>events.storage=fn}},
 Favorite:{get:({type})=>favorites[type]||[]},Timeline:{watched:card=>card.progress||{}},
 Utils:{hash:x=>x},Activity:{active:()=>active},Listener:{follow:(key,fn)=>events[key]=fn},Component:{get:k=>registry[k],add:(k,v)=>registry[k]=v}}};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  function sameHomeCard('),source.indexOf('  function homeRowKind(')),ctx);
ctx.installHomeNavigation();ctx.installHomeNavigation();assert.equal(styles.length,1);
assert(ctx.document.body.className.includes('homecinema-main'));active={component:'full'};events.activity();assert(!ctx.document.body.className.includes('homecinema-main'));
active={component:'main'};events.activity();assert(ctx.document.body.className.includes('homecinema-main'));
assert(styles[0].textContent.includes('.head .full--screen{display:none!important}'));
values.torrents_filter={quality:['1080p'],season:['2'],homecinema_scoped_season:true};
values.torrents_filter_data['1:tv']={quality:['1080p'],season:['2']};
const euphoria=new registry.torrents({movie:{id:1}});
assert.equal(euphoria.getFilterData().season,undefined,'untrusted legacy season migrates once');
euphoria.setFilterData({quality:['1080p'],season:['2']});
const ted=new registry.torrents({movie:{id:2}});
assert.equal(ted.getFilterData().season,undefined,'new series never inherits global season even if global is marked');
assert.equal(ted.getFilterData().quality[0],'1080p');
ted.setFilterData(ted.getFilterData());assert.equal(ted.getFilterData().season,undefined);
assert.equal(new registry.torrents({movie:{id:1}}).getFilterData().season[0],'2','own selection survives reopening');
euphoria.setFilterData({});assert.equal(euphoria.getFilterData().season,undefined,'reset is respected');
// A late native timetable render must not replace the actual S2E3 label with S2E8.
const element=new Element('card');element.card_data={original_name:'Euphoria',media_type:'tv'};const view=new Element('card__view');element.appendChild(view);cards.push(element);
values.online_watched_last={Euphoria:{season:2,episode:3}};const before=JSON.stringify(values);writes=0;
ctx.drawLastHomeEpisode(element);view.appendChild(new Element('card-watched'));ctx.drawLastHomeEpisode(element);
assert.equal(view.querySelector('.homecinema-last-episode').textContent,'Сезон 2 · Серия 3');
assert.equal(view.children.filter(x=>x.className==='homecinema-last-episode').length,1);
assert.equal(writes,0);assert.equal(JSON.stringify(values),before,'drawing never rewrites history or timeline');
values.online_watched_last={Euphoria:{season:2,episode:4}};events.storage({name:'online_watched_last'});
assert.equal(view.querySelector('.homecinema-last-episode').textContent,'Сезон 2 · Серия 4');
values.online_watched_last={};ctx.drawLastHomeEpisode(element);assert.equal(view.querySelector('.homecinema-last-episode'),null);
favorites.wath=[{id:11,kinopoisk_id:11},{id:12,kinopoisk_id:12,progress:{percent:100}},{id:13,kinopoisk_id:13,media_type:'tv',progress:{percent:100}}];
favorites.scheduled=[{id:11,kinopoisk_id:11},{id:14,kinopoisk_id:14},{id:15,kinopoisk_id:15}];
favorites.viewed=[{kinopoisk_id:14}];
const combined=ctx.combinedWatchCards([{id:11,kinopoisk_id:11},{id:16,kinopoisk_id:16,review:{feedback:'seen'}},{id:17,kinopoisk_id:17,review:{my_rating:7}}],{ratings:[{kp_id:15,rating:8}]});
assert.deepEqual(Array.from(combined,c=>c.id),[11,13],'union deduplicates and hides completed films, marked viewed, seen and rated; one episode does not complete a series');
assert.equal(favorites.wath.length,3,'display policy does not delete the original planned/history data');
console.log('Home policy: native season fallback, scoped persistence/reset, header navigation, authoritative last episode without writes, combined planned list and watched exclusions passed');
