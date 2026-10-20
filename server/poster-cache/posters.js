(function () {
    'use strict';
    if (window.romanPosterCacheV1) return;
    window.romanPosterCacheV1 = true;
    var base = '__POSTER_BASE__';
    var index = {paths: {}, ids: {}, imdb: {}};
    var loads = {};
    var ready = false;
    var refreshing = false;

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

    function url(id) { return base + '/poster/kp/' + id + '.jpg?v=2'; }

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
        var id = kpId(element.card_data);
        if (!id) return;
        var image = element.querySelector('img.card__img');
        // Keep the existing renderer's lazy-loading behavior.
        if (image && !/img_load\.svg/.test(image.getAttribute('src') || '')) replaceImage(image, id, element);
    }

    function scan(root) {
        if (!root || root.nodeType !== 1) return;
        if (root.classList && root.classList.contains('card')) card(root);
        Array.prototype.forEach.call(root.querySelectorAll('.card'), card);
    }

    var fullCard = null;
    function full() {
        var id = kpId(fullCard);
        if (!id) return;
        Array.prototype.forEach.call(document.querySelectorAll('img.full--poster, .full-start__poster img'), function (image) {
            replaceImage(image, id);
        });
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
            }
        });
        var observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                if (mutation.type === 'attributes') {
                    var image = mutation.target;
                    if (image.classList && image.classList.contains('card__img')) {
                        var parent = image.closest ? image.closest('.card') : image.parentNode.parentNode;
                        card(parent);
                    } else if (image.classList && image.classList.contains('full--poster')) full();
                } else {
                    Array.prototype.forEach.call(mutation.addedNodes || [], function (node) {
                        scan(node);
                    });
                }
            });
        });
        observer.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['src']});
        scan(document.body);
        refresh();
        setInterval(refresh, 60000);
    }
    start();
})();
