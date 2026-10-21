(function () {
    'use strict';
    if (window.romanPosterCacheV1) return;
    window.romanPosterCacheV1 = true;
    var base = '__POSTER_BASE__';
    var index = {paths: {}, ids: {}, imdb: {}};
    var loads = {};
    var ready = false;
    var refreshing = false;
    var seriesLoads = {};
    var posterSelector='img.full--poster, .full-start__poster img, .explorer-card__head-img > img';
    var backgroundSelector='img.full-start__background';


    function kpId(card) {
        if (!card) return '';
        var id = card.kinopoisk_id || card.kp_id;
        if (!id && /^(kp|kinopoisk)$/.test(card.source || '')) id = card.id;
        if (/^[1-9][0-9]{0,9}$/.test(String(id || ''))) return String(id);
        var kind = card.media_type || (card.name || card.first_air_date ? 'tv' : 'movie');
        var source = card.source || 'tmdb';
        if (/^(tmdb|cub)$/.test(source)) id = index.ids[kind + ':' + (card.tmdb_id || card.id)];
        if (!id && card.imdb_id) id = index.imdb[card.imdb_id];
        if (!id && card.poster_path) id = index.paths[String(card.poster_path).replace(/^\/+/, '')];
        return id || '';
    }

    function posterKey(data) {
        var id = kpId(data);
        if (!id) return '';
        var season = Number(data.season_number || 0);
        var kind = data.media_type || (data.name || data.first_air_date ? 'tv' : 'movie');
        if (kind === 'tv') {
            if (!season && Lampa.Storage && Lampa.Utils && Lampa.Utils.hash) {
                var watched = Lampa.Storage.get('online_watched_last', {});
                var title = data.original_name || data.original_title || data.name || data.title || '';
                var last = watched[Lampa.Utils.hash(title)];
                if (last) season = Number(last.season || 0);
            }
            if (!season) season = Number((index.seasons || {})[id] || 0);
        }
        if (!isFinite(season) || season < 0 || season > 999 || Math.floor(season) !== season) season = 0;
        return id + '~' + season;
    }

    function url(key) {
        var parts = key.split('~');
        return base + '/poster/kp/' + parts[0] + '.jpg?v=3&season=' + (parts[1] || '0');
    }

    function load(id, callback) {
        var state = loads[id];
        if (state && state.ok) return callback(url(id));
        if (state && state.pending) { state.callbacks.push(callback); return; }
        if (state && state.failedAt && Date.now() - state.failedAt < 60000) return;
        state = loads[id] = {pending: true, callbacks: [callback]};
        var image = new Image();
        state.image = image;
        image.onload = function () {
            state.pending = false;
            state.ok = true;
            var callbacks = state.callbacks;
            state.callbacks = [];
            callbacks.forEach(function (fn) { fn(url(id)); });
            state.image = null;
        };
        image.onerror = function () {
            state.pending = false;
            state.failedAt = Date.now();
            state.callbacks = [];
            state.image = null;
        };
        image.src = url(id);
    }

    function replaceImage(image, id, root) {
        if (!image || !id) return;
        var target = url(id);
        image.setAttribute('data-roman-poster-id', id);
        load(id, function (local) {
            if (!document.documentElement.contains(image)) return;
            if (image.getAttribute('data-roman-poster-id') !== id) return;
            if (image.getAttribute('src') !== local) {
                image.removeAttribute('srcset');
                image.src = local;
            }
            // Lampa adds this text overlay after repeated failed image loads.
            if (root) {
                Array.prototype.forEach.call(root.querySelectorAll('.card__img-broken'), function (node) {
                    if (node.parentNode) node.parentNode.removeChild(node);
                });
            }
        });
    }

    function card(element) {
        if (!element || !element.card_data) return;
        var data = element.card_data;
        if (data.season_number && !kpId(data) && fullCard) {
            data = Object.assign({}, fullCard, {season_number:data.season_number});
        }
        var id = posterKey(data);
        if (!id) return;
        var image = element.querySelector('img.card__img');
        // Keep the existing renderer's lazy-loading behavior.
        if (image && !/img_load\.svg/.test(image.getAttribute('src') || '')) replaceImage(image, id, element);
    }

    function scan(root) {
        if (!root || root.nodeType !== 1) return;
        if (root.classList && root.classList.contains('card')) card(root);
        Array.prototype.forEach.call(root.querySelectorAll('.card'), card);
        previews(root);
        full();
        torrentRows(root);
        if (root.matches && root.matches(backgroundSelector)) background(root);
        Array.prototype.forEach.call(root.querySelectorAll(backgroundSelector),background);
    }

    var fullCard = null;
    function full() {
        var id = posterKey(activeCard());
        if (!id) return;
        Array.prototype.forEach.call(document.querySelectorAll(posterSelector), function (image) {
            replaceImage(image, id);
        });
    }

    var previewSelector='.full-episode__img img, .season-episode__img img, .season-info__poster img, img.torrent-serial__img';
    function activeCard() {
        var activity=Lampa.Activity && Lampa.Activity.active ? Lampa.Activity.active() : null;
        var data=activity && (activity.card || activity.movie);
        return kpId(data) ? data : fullCard;
    }
    function background(image) {
        if (!image || !image.matches || !image.matches(backgroundSelector)) return;
        // A broken SVG enlarged behind the description is not a backdrop.
        var src=image.getAttribute('src') || '';
        if (/img_(?:broken|load)\.svg/.test(src)) image.style.visibility='hidden';
        else if (image.style.visibility==='hidden') image.style.visibility='';
    }

    function preview(image, failed) {
        if (!image || !image.matches || !image.matches(previewSelector)) return;
        var data=activeCard();
        if (!data || !kpId(data)) return;
        var container=image.closest('.season-episode, .full-episode, .season-info, .torrent-serial');
        if (container && container.homecinemaEpisode) data=container.homecinemaEpisode.movie;
        var season=container && (container.textContent || '').match(/(?:сезон|season)\s*[-:]?\s*(\d+)/i);
        if (container && container.homecinemaEpisode) season=[null,container.homecinemaEpisode.season];
        var key=posterKey(season ? Object.assign({},data,{season_number:Number(season[1])}) : data);
        var src=image.getAttribute('src') || image.getAttribute('data-src') || '';
        if (src.indexOf(base+'/poster/')===0) return;
        if (failed || !src || /img_(?:broken|load)\.svg/.test(src)) {
            // This is a labelled fallback, never presented as a frame of this episode.
            load(key,function (local) {
                if (!document.documentElement.contains(image)) return;
                var current=image.getAttribute('src') || image.getAttribute('data-src') || '';
                if (current!==src && !/img_(?:broken|load)\.svg/.test(current)) return;
                if (image.naturalWidth>0 && !/img_(?:broken|load)\.svg/.test(current)) return;
                image.setAttribute('data-homecinema-preview','season-poster');
                image.setAttribute('title','Постер сезона — кадр серии недоступен');
                // Native torrent lazy rendering restores data-src on every visible event.
                image.setAttribute('data-src',local);
                replaceImage(image,key,container);
            });
        } else if (image.homecinemaPreviewSource!==src) {
            image.homecinemaPreviewSource=src;
            setTimeout(function () {
                if (document.documentElement.contains(image) && image.getAttribute('src')===src && !image.naturalWidth) preview(image,true);
            },7000);
        }
    }
    function previews(root) {
        if (root.matches && root.matches(previewSelector)) preview(root,false);
        Array.prototype.forEach.call(root.querySelectorAll(previewSelector),function (image) {preview(image,false);});
    }

    function series(movie,callback) {
        var id=kpId(movie);
        if (!id) return callback([]);
        var cached=seriesLoads[id];
        if (cached && cached.pending) {cached.calls.push(callback);return;}
        if (cached && Date.now()-cached.time<60000) return callback(cached.rows);
        cached=seriesLoads[id]={pending:true,calls:[callback]};
        var xhr=new XMLHttpRequest();
        xhr.open('GET',base+'/series/kp/'+id+'.json',true);xhr.timeout=5000;
        function done(rows) {
            if (!cached.pending) return;
            cached.pending=false;cached.time=Date.now();cached.rows=rows;
            var calls=cached.calls;cached.calls=[];
            calls.forEach(function (fn) {fn(rows);});
        }
        xhr.onload=function () {
            try {var data=JSON.parse(xhr.responseText);done(xhr.status===200 && Array.isArray(data.episodes) ? data.episodes : []);}
            catch (_) {done([]);}
        };
        xhr.onerror=xhr.ontimeout=function () {done([]);};xhr.send();
    }
    function torrentRow(row) {
        if (!row || !row.querySelector) return;
        var info=row.homecinemaEpisode, movie=info ? info.movie : activeCard();
        var line=row.querySelector('.torrent-serial__line');
        if (!line || !movie || !kpId(movie)) return;
        var number=row.querySelector('.torrent-serial__episode');
        var match=(line.textContent || '').match(/(?:сезон|season)\s*[-:]?\s*(\d+)/i);
        var season=Number(info ? info.season : match && match[1]);
        var episode=Number(info ? info.episode : number && number.textContent);
        if (!(season>=0 && episode>0)) return;
        var identity=kpId(movie)+':'+season+':'+episode;
        row.homecinemaEpisodeKey=identity;
        series(movie,function (rows) {
            if (!document.documentElement.contains(row) || row.homecinemaEpisodeKey!==identity) return;
            var entry=rows.filter(function (e) {return e.season===season && e.episode===episode;})[0];
            if (!entry) return;
            var spans=line.querySelectorAll('span'), target=spans[spans.length-1];
            if (!target || !/--|—|дата неизвестна/i.test(target.textContent || '')) return;
            var parts=entry.date.split('-'), label=parts[2]+'.'+parts[1]+'.'+parts[0];
            var next=(target.textContent || '').replace(/--|—|дата неизвестна/i,label);
            target.textContent=next;
            target.setAttribute('title','Дата выхода из сохранённого расписания');
        });
    }
    function torrentRows(root) {
        if (root.matches && root.matches('.torrent-serial')) torrentRow(root);
        Array.prototype.forEach.call(root.querySelectorAll('.torrent-serial'),torrentRow);
    }

    function refresh() {
        if (refreshing) return;
        refreshing = true;
        var xhr = new XMLHttpRequest();
        xhr.open('GET', base + '/index.json', true);
        xhr.timeout = 7000;
        function finish() { refreshing = false; }
        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var next = JSON.parse(xhr.responseText);
                    if (next.paths && next.ids && next.imdb) {
                        index = next;
                        scan(document.body);
                        full();
                    }
                } catch (_) {}
            }
            finish();
        };
        xhr.onerror = finish;
        xhr.ontimeout = finish;
        xhr.send();
    }

    function start() {
        if (ready) return;
        if (!window.Lampa || !Lampa.Listener || !document.body) return setTimeout(start, 200);
        ready = true;
        Lampa.Listener.follow('full', function (event) {
            if (event.type === 'complite' && event.data && event.data.movie) {
                fullCard = event.data.movie;
                full();
                previews(document.body);
            }
        });
        Lampa.Listener.follow('torrent_file',function (event) {
            if (event.params && event.params.movie) fullCard=event.params.movie;
            if (event.type==='render' && event.params && event.params.movie && event.item && event.item[0] && event.element) {
                var row=event.item[0];
                row.homecinemaEpisode={movie:event.params.movie,season:event.element.season,episode:event.element.episode};
                // render is emitted before the modal is attached to the document.
                setTimeout(function () {torrentRow(row);previews(row);full();},0);
            }
        });
        document.addEventListener('error',function (event) {preview(event.target,true);background(event.target);},true);
        var observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                if (mutation.type === 'attributes') {
                    var image = mutation.target;
                    if (image.classList && image.classList.contains('card__img')) {
                        var parent = image.closest ? image.closest('.card') : image.parentNode.parentNode;
                        card(parent);
                    } else if (image.classList && image.classList.contains('full--poster')) full();
                    if (image.matches && image.matches(posterSelector)) full();
                    background(image);
                    preview(image,false);
                } else {
                    Array.prototype.forEach.call(mutation.addedNodes || [], function (node) {
                        scan(node);
                    });
                }
            });
        });
        observer.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['src','data-src']});
        scan(document.body);
        Array.prototype.forEach.call(document.querySelectorAll(backgroundSelector),background);
        refresh();
        if (Lampa.Storage && Lampa.Storage.listener) Lampa.Storage.listener.follow('change', function (event) {
            if (event.name === 'online_watched_last') {scan(document.body);full();}
        });
        setInterval(refresh, 60000);
    }
    start();
})();
