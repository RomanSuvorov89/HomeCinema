const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const bootstrap = fs.readFileSync(path.join(root, 'server/recommender/client-bootstrap.js.template'), 'utf8');
const settings = bootstrap.split('/* homecinema-card-metadata:start */')[1].split('/* homecinema-card-metadata:end */')[0];
const upstream = fs.readFileSync(path.join(root, 'server/recommender/tests/fixtures/lampa-card-metadata.js'), 'utf8');

function scenario(configure, source, child = false, id = 154598, remoteBlocked = false, fallbackFails = false) {
    const requests = [], results = [], errors = [], timers = [];
    const context = {
        window: {lampa_settings: {account_use:false, disable_features:{discuss:true},
            lgbt:{preserved:true}, other:'preserved'}},
        Storage: {field: () => 'ru'}, Lang: {selected: () => false},
        permit: {child_small:child, child}, day:1440, day$1:1440,
        object$2: {cub_domain:'catalog.test'},
        Api: {sources:{cub:{reactionsGet:(params,done)=>queueMicrotask(()=>done({result:[]}))}}},
        TMDB$1: {key:()=> 'public-fixture'},
        TMDB: {videos:(params,done)=>queueMicrotask(()=>done({results:[]}))},
        videos:(params,done)=>queueMicrotask(()=>done({results:[]})),
        queueMicrotask, setTimeout:(fn)=>{timers.push(fn);return timers.length;}, clearTimeout:()=>{}
    };
    function get(url, params, done) {
        requests.push(url);
        queueMicrotask(() => {
            if (url.includes('/season/')) done({episodes:[{episode_number:1,season_number:1}]});
            else if (url.includes('append_to_response=')) done({id, name:'Нулевой пациент',
                first_air_date:'2022-05-19',overview:'Описание сериала',number_of_seasons:1,
                keywords:{results:[]},external_ids:{imdb_id:'fixture'}});
            else done({results:[]});
        });
    }
    context.get$7 = function (url,params,done,error) {
        if (remoteBlocked && url.includes('append_to_response=')) {
            requests.push('CUB blocked'); queueMicrotask(()=>done({blocked:true}));
        } else get(url,params,done,error);
    };
    context.get$c = function (url,params,done,error) {
        if (fallbackFails && url.includes('append_to_response=')) return queueMicrotask(error);
        get(url,params,done,error);
    };
    context.TMDB.get = get;
    context.reactionsGet = context.Api.sources.cub.reactionsGet;
    context.Lampa = {Network:{silent:(url,done)=>{
        requests.push(url);
        // Reproduce the actual service response reaching the client before
        // the full card opens. No metadata request should happen before the fix.
        done([{cat:'tv',id}]);
    }}};
    context.window.Lampa = context.Lampa;
    vm.createContext(context);
    vm.runInContext(upstream, context);
    context.Arrays = {extend:context.extend};
    context.Utils$1 = {dcma:context.dcma, protocol:()=> 'https://', countSeasons:()=>1,
        addSource:(data)=>data};
    context.Lampa.Utils = context.Utils$1;
    context.Api.sources.cub.full = context.full$1;
    context.Api.sources.tmdb = {full:context.full$3};
    context.source = params=>context.Api.sources[params.source || source];
    context.Api.full = context.full;
    context.Lampa.Api = context.Api;
    // The central client runs before or after ServiceDMCA.init().
    if (configure) {context.Lampa.Utils = context.Utils$1; vm.runInContext(settings, context);}
    context.Arrays.extend(context.window.lampa_settings, {
        disable_features:{dmca:false,lgbt:false,discuss:false},dcma:false
    });
    context.init$5();
    if (configure) context.window.lampa_settings.dcma = [{cat:'tv',id}]; // late in-flight response
    context.Api.full({method:'tv',id,source,card:{kinopoisk_id:'4642708'}},
        data=>results.push(data), error=>errors.push(error));
    return {context,requests,results,errors,timers};
}

(async () => {
    for (const source of ['cub','tmdb']) {
        const before = scenario(false,source);
        assert.equal(before.errors.length,1);
        assert.equal(before.requests.length,1);
        assert(before.requests[0].endsWith('/blocked'));
        assert.equal(before.results.length,0,'upstream refuses metadata before issuing its first card request');

        for (const child of [false,true]) {
            const after = scenario(true,source,child);
            await new Promise(resolve=>setImmediate(resolve));
            assert.equal(after.errors.length,0);
            assert.equal(after.results.length,1);
            assert.equal(after.results[0].movie.name,'Нулевой пациент');
            assert.equal(after.results[0].movie.id,154598,'card identity is unchanged');
            assert.equal(after.results[0].movie.source,source);
            assert.equal(after.results[0].episodes.episodes.length,1);
            assert(!after.requests.some(url=>url.endsWith('/blocked')));
            assert.equal(after.requests.some(url=>url.includes('/credits')), !child,
                'native child-profile behavior remains active');
            assert.equal(after.context.window.lampa_settings.disable_features.discuss,true);
            assert.equal(after.context.window.lampa_settings.lgbt.preserved,true);
            assert.equal(after.context.window.lampa_settings.other,'preserved');
        }
    }
    const blocked = scenario(true,'cub',false,154598,true);
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(blocked.errors.length,0);
    assert.equal(blocked.results.length,1);
    assert.equal(blocked.results[0].movie.id,154598);
    assert.equal(blocked.results[0].movie.source,'tmdb','CUB blocked response switches to native TMDB loader');
    assert.equal(blocked.results[0].movie.kinopoisk_id,'4642708');
    assert.equal(blocked.requests.filter(url=>url==='CUB blocked').length,1);
    const offline = scenario(true,'cub',false,154598,true,true);
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(offline.results.length,0);
    offline.timers.forEach(fn=>fn());
    offline.timers.forEach(fn=>fn());
    assert.equal(offline.errors.length,1,'failed metadata fallback returns the native error once');
    blocked.timers.forEach(fn=>fn());
    assert.equal(blocked.errors.length,0,'late timeout cannot replace successful data');
    const repeated = scenario(true,'cub',false,42);
    vm.runInContext(settings,repeated.context);
    assert.equal(repeated.context.window.lampa_settings.disable_features.dmca,true);
    const once = repeated.context.Lampa.Utils.dcma;
    vm.runInContext(settings,repeated.context);
    assert.equal(repeated.context.Lampa.Utils.dcma,once,'idempotent installation');
    const delayed = {window:{}}; vm.createContext(delayed);
    vm.runInContext(settings,delayed);
    delayed.window.Lampa = delayed.Lampa = {Utils:{dcma:()=>true}};
    delayed.localMetadataCards();
    assert.equal(delayed.Lampa.Utils.dcma('tv',154598),false,'installs when the API becomes available later');
    console.log('Native CUB/TMDB card loaders: original blocked early-return reproduced; metadata and episodes restored; native child settings and card IDs preserved.');
})().catch(error=>{console.error(error);process.exitCode=1;});
