const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('kinopoisk.js','utf8');
const values={},favorites={},events={},registry={},styles=[],cards=[];
let active={component:'main',title:'Главная - CUB'},writes=0,header='';
class Element{
 constructor(cls=''){this.className=cls;this.children=[];this.textContent='';this.classList={
 add:c=>{if(!this.className.split(' ').includes(c))this.className+=' '+c;},
 remove:c=>this.className=this.className.split(' ').filter(x=>x!==c).join(' '),
 toggle:(c,on)=>on?this.classList.add(c):this.classList.remove(c)};}
 appendChild(child){child.parent=this;this.children.push(child);}
 querySelector(selector){const name=selector.slice(1);for(const c of this.children){if(c.className.split(' ').includes(name))return c;const found=c.querySelector(selector);if(found)return found;}return null;}
 remove(){this.parent.children=this.parent.children.filter(x=>x!==this);}
}
const renderedFilters=[];
const nativeSelectedFilter=vm.runInNewContext(
 fs.readFileSync('tests/fixtures/lampa-torrents-selected-filter.js','utf8')+';nativeSelectedFilter;',{
 Arrays:{isArray:Array.isArray},filter_translate:{quality:'Качество',season:'Сезон'},
 filter_items:{quality:['Все','1080p'],season:['Все','1','2']},
 filter:{chosen:(type,labels)=>renderedFilters.push(Array.from(labels))}
 });
function Native(object){
 this.selectedFilter=nativeSelectedFilter;
 this.cardID=()=>object.movie.id+':tv';
 this.getFilterData=()=>values.torrents_filter_data[this.cardID()]||values.torrents_filter||{};
 this.setFilterData=filter=>{values.torrents_filter_data[this.cardID()]=filter;values.torrents_filter=filter;};
}
registry.torrents=Native;values.torrents_filter_data={};
const ctx={window:{appready:true},document:{body:new Element(),head:{appendChild:s=>styles.push(s)},createElement:()=>new Element(),querySelectorAll:()=>cards},
 reviewForCard:card=>card.review||{},ratingKey:card=>String(card.id),cacheGet:()=>null,data:null,
 Lampa:{Head:{title:value=>header=value},Lang:{translate:()=> 'Главная'},Storage:{get:(k,d)=>values[k]||d,set:(k,v)=>{writes++;values[k]=v;},listener:{follow:(key,fn)=>events.storage=fn}},
 Favorite:{full:()=>favorites,get:({type})=>favorites[type]||[]},Timeline:{watched:card=>card.progress||{}},
 Utils:{hash:x=>x},Activity:{active:()=>active},Listener:{follow:(key,fn)=>events[key]=fn},Component:{get:k=>registry[k],add:(k,v)=>registry[k]=v}}};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  function sameHomeCard('),source.indexOf('  function homeRowKind(')),ctx);
ctx.installHomeNavigation();ctx.installHomeNavigation();assert.equal(styles.length,1);
assert.equal(header,'Главная','keep the title and its flex space, remove only the CUB suffix');
assert(!styles[0].textContent.includes('.head__title{display:none'),'never hide the title layout');
assert(ctx.document.body.className.includes('homecinema-main'));active={component:'full',title:'Сериал - CUB'};header=active.title;events.activity();assert.equal(header,'Сериал - CUB','leave non-home headings unchanged');assert(!ctx.document.body.className.includes('homecinema-main'));
active={component:'main',title:'Главная — CUB'};events.activity();assert.equal(header,'Главная');assert(ctx.document.body.className.includes('homecinema-main'));
assert(styles[0].textContent.includes('.head .full--screen{display:none!important}'));
values.torrents_filter={quality:['1080p'],season:['2'],homecinema_scoped_season:true};
values.torrents_filter_data['1:tv']={quality:['1080p'],season:['2']};
const euphoria=new registry.torrents({movie:{id:1}});
assert.equal(euphoria.getFilterData().season,undefined,'untrusted legacy season migrates once');
euphoria.setFilterData({quality:['1080p'],season:['2']});
assert.doesNotThrow(()=>euphoria.selectedFilter(),'native renderer must not receive the service marker as a filter');
assert.deepEqual(renderedFilters.at(-1),['Качество:1080p','Сезон:2']);
assert.equal(values.torrents_filter_data['1:tv'].homecinema_scoped_season,true,'keep persisted season migration state');
assert(!Object.hasOwn(euphoria.getFilterData(),'homecinema_scoped_season'),'service metadata must not escape the adapter');
const ted=new registry.torrents({movie:{id:2}});
assert.equal(ted.getFilterData().season,undefined,'new series never inherits global season even if global is marked');
assert.equal(ted.getFilterData().quality[0],'1080p');
ted.setFilterData(ted.getFilterData());assert.equal(ted.getFilterData().season,undefined);
assert.doesNotThrow(()=>ted.selectedFilter());assert.deepEqual(renderedFilters.at(-1),['Качество:1080p']);
assert.equal(new registry.torrents({movie:{id:1}}).getFilterData().season[0],'2','own selection survives reopening');
euphoria.setFilterData({});assert.equal(euphoria.getFilterData().season,undefined,'reset is respected');
assert.doesNotThrow(()=>euphoria.selectedFilter());assert.deepEqual(renderedFilters.at(-1),[],'reset must not leave a service flag in the visible filters');
const reopened=new registry.torrents({movie:{id:1}});assert.doesNotThrow(()=>reopened.selectedFilter());
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

// Latest selected is not latest completed. Use the exact last aired episode's timeline.
const NativeDate=Date;
ctx.Date=class extends NativeDate {constructor(...args){super(...(args.length?args:['2026-10-23T12:00:00Z']));}};
const show={id:99,kinopoisk_id:'42',original_name:'Original Show',first_air_date:'2024-01-01',media_type:'tv',source:'cub'};
const releases=[{kp_id:42,tmdb_id:99,original_title:'Original Show',release_year:2024,season:2,episode:8,next_air_date:'2026-10-30'}];
values.roman_home_shelves_releases_v1={items:releases};values.online_watched_last={'Original Show':{season:2,episode:8}};
let progress=12;ctx.Lampa.Timeline.watchedEpisode=(card,season,episode)=>season===2&&episode===8?progress:0;
const beforeCompletion=JSON.stringify(values);writes=0;
assert.equal(ctx.continueHomeCards([show]).length,1,'opening the finale does not complete it');
progress=100;assert.equal(ctx.continueHomeCards([show]).length,0,'completed final aired episode leaves Continue');
values.online_watched_last['Original Show'].episode=3;assert.equal(ctx.continueHomeCards([show]).length,1,'keep an active earlier episode despite a stale completed-finale timeline');
values.online_watched_last['Original Show'].episode=8;
assert.equal(ctx.continueHomeCards([{...show,media_type:'movie',original_name:undefined,first_air_date:undefined}]).length,1,'do not apply series policy to movies');
assert.equal(ctx.continueHomeCards([{id:123,original_name:'Unknown Show',media_type:'tv'}]).length,1,'unknown schedule stays');
assert.equal(ctx.caughtUpSeries({...show,kinopoisk_id:undefined,id:undefined}),true,'exact original title plus year resolves missing catalog mapping');
assert.equal(writes,0);assert.equal(JSON.stringify(values),beforeCompletion,'completion does not rewrite watched data, ratings or schedules');
// Cached/native rows displayed before the server reply also follow fresh schedule facts.
progress=12;const rendered=ctx.continueHomeCards([show])[0];const cardElement=new Element('card');cardElement.card_data=rendered;cards.push(cardElement);
progress=100;ctx.refreshContinueCards();assert(cardElement.className.includes('homecinema-caught-up'));
releases[0].episode=9;ctx.refreshContinueCards();assert(!cardElement.className.includes('homecinema-caught-up'),'new unwatched episode restores visibility');
assert.equal(ctx.continueHomeCards([show]).length,1);
releases[0].episode=8;
ctx.Date=class extends NativeDate {constructor(...args){super(...(args.length?args:['2026-10-30T12:00:00Z']));}};
assert.equal(ctx.caughtUpSeries(show),false,'old cached schedule stops hiding the series when the next release is due');
ctx.Date=NativeDate;
// Older Lampa: use the exact same canonical episode hash as native watchedEpisode.
delete ctx.Lampa.Timeline.watchedEpisode;releases[0].next_air_date=null;let hash;
ctx.Lampa.Timeline.view=value=>{hash=value;return {percent:100};};
assert.equal(ctx.caughtUpSeries(show),true);assert.equal(hash,'28Original Show');
console.log('Home: retained heading/spacing, home-only suffix removal; completed latest aired episode, partial/unknown progress, new releases, late metadata and legacy episode hashes passed');
