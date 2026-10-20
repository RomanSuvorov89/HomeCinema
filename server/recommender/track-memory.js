(function () {
  'use strict';
  if (window.RomanTrackMemory) return;
  var context = null, lastMovie = null, browser = {}, generation = 0;
  function text(t) { return String(t.title || t.label || t.name || '').toLowerCase(); }
  function language(t) {
    var lang = String(t.lang || t.language || '').toLowerCase().replace(/_/g,'-');
    if (/^(ru|rus)(-|$)/.test(lang) || /русск|russian/.test(text(t))) return 'ru';
    if (/^(en|eng)(-|$)/.test(lang)) return 'en';
    return lang;
  }
  function descriptor(t) {
    var title = text(t);
    var forced = t.forced === true || t.forced === 1 || /forced|форс|надпис|signs|songs/.test(title);
    var full = /full|complete|полны|полная/.test(title);
    title = title.replace(/\b(?:aac|ac3|eac3|dts|truehd|flac|opus|srt|subrip|ass|rus|ru|russian|eng|en|english)\b/g,' ')
      .replace(/\b\d+(?:\.\d+)?\s*(?:kbps|kb\/s|khz|channels|ch)\b/g,' ')
      .replace(/\b[257]\.[01]\b/g,' ').replace(/русский|русская/g,' ')
      .replace(/дорожка\s*\d+|track\s*\d+/g,' ').replace(/[^a-zа-яё0-9]+/g,' ').replace(/\s+/g,' ').trim();
    return {lang:language(t),title:title,forced:forced,full:full,off:false};
  }
  function choose(tracks, kind, saved) {
    if (saved && saved.off && kind === 'sub') return null;
    if (saved) {
      var matching = tracks.filter(function (t) {
        var d = descriptor(t);
        return d.lang === saved.lang && d.forced === saved.forced && d.title === saved.title;
      });
      if (matching.length === 1) return matching[0];
      // Never reuse an episode-specific index to break an ambiguous match.
    }
    var candidates = tracks.filter(function (t) {
      return language(t) === 'ru' && (kind !== 'sub' || !descriptor(t).forced);
    });
    function score(t) {
      var d = descriptor(t), value = 0;
      if (kind === 'audio' && /дубляж|дублир|\bdub(?:bed)?\b|(?:^|\s)дб(?:$|\s)/.test(text(t))) value += 100;
      if (kind === 'sub' && d.full) value += 100;
      if (/sdh|hearing|слабослыш/.test(text(t))) value -= 5;
      if (t.default === true) value += 1;
      return value;
    }
    candidates.sort(function (a,b) {return score(b)-score(a);});
    if (candidates.length) return candidates[0];
    return kind === 'sub' ? null : undefined; // No Russian audio: keep the player's default.
  }
  function request(path, payload) {
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer;
    var options = {cache:'no-store'};
    if (controller) options.signal = controller.signal;
    if (payload) {options.method='POST';options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(payload);}
    return Promise.race([fetch(window.RomanTracksApi + path,options).then(function (r) {
      if (!r.ok) throw new Error('HTTP '+r.status);return r.json();
    }),new Promise(function (_,reject) {timer=setTimeout(function () {
      if(controller) controller.abort();reject(new Error('timeout'));
    },4000);})]).then(function (r) {clearTimeout(timer);return r;},function (e) {clearTimeout(timer);throw e;});
  }
  function seriesKey(movie) {
    if (!movie || !(movie.media_type === 'tv' || movie.first_air_date || movie.number_of_seasons || movie.seasons)) return '';
    if (movie.kinopoisk_id) return 'kp:tv:'+movie.kinopoisk_id;
    if (movie.id && /^(tmdb|cub)$/.test(movie.source || 'tmdb')) return (movie.source || 'tmdb')+':tv:'+movie.id;
    return '';
  }
  function begin(data) {
    generation++;
    browser = {};
    var active = Lampa.Activity.active() || {};
    var movie = data.movie || data.card || active.movie || active.card || lastMovie;
    var c = {key:seriesKey(movie),prefs:{},baseline:{},applied:{},generation:generation};
    context = c;
    c.ready = c.key ? request('/track-preferences.json?series_key='+encodeURIComponent(c.key)).then(function (r) {
      c.prefs=r.preferences || {};
    }).catch(function (e) {console.warn('[Track memory] read failed',e);}) : Promise.resolve();
    return c;
  }
  function save(c, kind, track) {
    if (!c.key || context !== c) return;
    var d = track ? descriptor(track) : {off:true};
    request('/track-preferences.json',{series_key:c.key,kind:kind,descriptor:d}).then(function () {
      c.prefs[kind]=d;
    }).catch(function (e) {console.warn('[Track memory] save failed',e);Lampa.Noty.show('Не удалось запомнить дорожку на сервере');});
  }
  function mpv(status, setSelection) {
    var c = context;
    if (!c || !status.tracks || !status.duration || c.busy) return;
    c.busy = true;
    c.ready.then(function () {
      if (context !== c) return;
      var changes = {};
      ['audio','sub'].forEach(function (kind) {
        var tracks = status.tracks.filter(function (t) {return t.type === kind;});
        var prop = kind === 'audio' ? 'aid' : 'sid';
        var current = status[prop] === false || status[prop] === 'no' ? 'no' : String(status[prop]);
        if (!c.applied[kind]) {
          var selected = choose(tracks,kind,c.prefs[kind]);
          if (selected !== undefined) changes[prop] = selected === null ? 'no' : selected.id;
          c.baseline[kind] = selected === undefined ? current : String(changes[prop]);
          c.applied[kind] = true;
        } else if (current !== c.baseline[kind]) {
          var track = tracks.filter(function (t) {return String(t.id) === current;})[0];
          if (track || (kind === 'sub' && (current === 'no' || current === 'false'))) {
            save(c,kind,track);c.baseline[kind]=current;
          }
        }
      });
      if (Object.keys(changes).length) return setSelection(changes).catch(function (e) {c.applied={};throw e;});
    }).catch(function (e) {console.warn('[Track memory] selection failed',e);}).then(function () {c.busy=false;});
  }
  function browserTracks(kind, list) {
    var c = context;
    if (!c || !list || !list.length) return;
    var state = browser[kind] = {tracks:Array.prototype.slice.call(list),armed:false};
    c.ready.then(function () {
      setTimeout(function () {
        if (context !== c || browser[kind] !== state) return;
        var selected = choose(state.tracks,kind,c.prefs[kind]);
        if (selected !== undefined) {
          state.tracks.forEach(function (t) {
            if (kind === 'sub') {t.mode=t===selected?'showing':'disabled';t.selected=t===selected;}
            else {t.enabled=t===selected;t.selected=t===selected;}
          });
          if (kind === 'sub') Lampa.PlayerVideo.subsview(!!selected);
        }
        state.last = currentBrowser(state,kind);
        state.armed=true;
      },650);
    });
  }
  function currentBrowser(state,kind) {
    return state.tracks.filter(function (t) {
      return kind === 'sub' ? t.mode === 'showing' || t.selected === true : t.enabled === true || t.selected === true;
    })[0] || null;
  }
  window.RomanTrackMemory = {begin:begin,mpv:mpv,choose:choose,descriptor:descriptor,seriesKey:seriesKey};
  Lampa.Listener.follow('full',function (e) {if(e.type==='complite' && e.data) lastMovie=e.data.movie;});
  Lampa.Player.listener.follow('create',function (e) {begin(e.data || {});});
  if (Lampa.PlayerVideo && Lampa.PlayerVideo.listener) Lampa.PlayerVideo.listener.follow('tracks',function (e) {browserTracks('audio',e.tracks);});
  if (Lampa.PlayerVideo && Lampa.PlayerVideo.listener) Lampa.PlayerVideo.listener.follow('subs',function (e) {browserTracks('sub',e.subs);});
  if (Lampa.PlayerVideo && Lampa.PlayerVideo.listener) Lampa.PlayerVideo.listener.follow('destroy',function () {browser={};});
  setInterval(function () {
    Object.keys(browser).forEach(function (kind) {
      var state=browser[kind];
      if (!state.armed) return;
      var selected=currentBrowser(state,kind);
      if (selected !== state.last) {state.last=selected;save(context,kind,selected);}
    });
  },750);
})();
