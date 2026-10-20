#!/usr/bin/env python3
"""Install viewport-based prefetch in the mounted Lampa initialization file."""
import argparse
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

BEGIN = '/* roman-prefetch:start */'
END = '/* roman-prefetch:end */'

SCRIPT = r"""
(function () {
    'use strict';
    if (window.romanPrefetchV1) return;
    window.romanPrefetchV1 = {version: 1, last: null};
    var diagnostic = window.romanPrefetchV1;

    function node(value) {
        if (!value) return null;
        return value.nodeType ? value : value[0] || null;
    }

    function nearEnd(bottom, viewportBottom, viewportHeight) {
        return bottom <= viewportBottom + Math.max(300, viewportHeight * 0.9);
    }

    function wrapRequest(comp, name, state, eventMode) {
        var original = comp[name];
        if (!state.wrappedMethods) state.wrappedMethods = {};
        if (typeof original !== 'function' || state.wrappedMethods[name] === original) return;
        function wrapped() {
            var args = Array.prototype.slice.call(arguments);
            if (eventMode && args[0] !== 'next') return original.apply(this, args);
            var offset = eventMode ? 1 : (state.main ? 0 : 1);
            if (typeof args[offset] !== 'function') return original.apply(this, args);
            var success = args[offset], failure = args[offset + 1];
            var done = false;
            state.pending++;
            state.requests++;
            function finish() { if (!done) { done = true; state.pending--; } }
            args[offset] = function (data) {
                finish();
                var rows = Array.isArray(data) ? data : data && data.results;
                if (data && !Array.isArray(data) && (data.nomore === true ||
                    (Number(data.total_pages) > 0 && Number(data.page) >= Number(data.total_pages)))) state.ended = true;
                if (Array.isArray(rows) && !rows.length) state.retryAt = Date.now() + 15000;
                try { return success.apply(this, arguments); }
                finally { state.lastDone = Date.now(); }
            };
            args[offset + 1] = function () {
                finish();
                state.retryAt = Date.now() + 15000;
                if (typeof failure === 'function') return failure.apply(this, arguments);
            };
            try { return original.apply(this, args); }
            catch (error) { finish(); state.retryAt = Date.now() + 15000; throw error; }
        }
        wrapped.romanPrefetchWrapped = true;
        comp[name] = wrapped;
        // The existing tail loader uses setters that wrap assigned methods again.
        state.wrappedMethods[name] = comp[name];
    }

    function inspect(active) {
        if (!active || !active.activity) return null;
        if (/^(full|torrents|player|settings|mytorrents)$/.test(active.component || '')) return null;
        var comp = active.activity.component;
        if (!comp || comp.destroyed || typeof comp.render !== 'function') return null;
        var main = active.component === 'main';
        var category = !main && (typeof comp.nextPageReuest === 'function' ||
            active.component === 'category_full' || /^roman_(recommendation_review|home_shelf|kinopoisk)$/.test(active.component || ''));
        if (!main && !category) return null;
        var state = comp.romanPrefetchState;
        if (!state) state = comp.romanPrefetchState = {
            main: main, pending: 0, ended: false, retryAt: 0, lastAttempt: 0,
            lastDone: 0, requests: 0, lastCount: 0
        };
        // Late assignments by custom components are decorated on the next tick.
        if (typeof comp.emit === 'function' && comp.scroll && Array.isArray(comp.items)) {
            wrapRequest(comp, 'emit', state, true);
        } else if (main) wrapRequest(comp, 'next', state, false);
        else wrapRequest(comp, 'nextPageReuest', state, false);
        return {comp: comp, state: state, active: active};
    }

    function tick() {
        if (document.hidden || !window.Lampa || !Lampa.Activity) return;
        if (Lampa.Controller && Lampa.Controller.enabled) {
            var control = Lampa.Controller.enabled();
            if (control && control.name && control.name !== 'content' && control.name !== 'items_line') return;
        }
        var current = inspect(Lampa.Activity.active());
        if (!current) return;
        var comp = current.comp, state = current.state;
        var root = node(comp.render(true));
        if (!root || !document.documentElement.contains(root)) return;
        var scroll = root.classList && root.classList.contains('scroll') ? root : root.querySelector('.scroll') || root;
        var body = scroll.querySelector('.scroll__body') || scroll;
        var rect = scroll.getBoundingClientRect();
        var top = Math.max(0, rect.top), bottom = Math.min(window.innerHeight, rect.bottom);
        if (bottom <= top || !nearEnd(body.getBoundingClientRect().bottom, bottom, bottom - top)) return;
        var count = root.querySelectorAll('.card').length;
        if (!count) return;
        var now = Date.now();
        if (now - state.lastAttempt < 600) return;
        state.lastAttempt = now;

        // Some versions hold fetched rows until a scroll animation ends.
        if (typeof comp.emit === 'function' && Array.isArray(comp.loaded) && comp.loaded.length) {
            comp.emit('pushLoaded');
            if (Lampa.Layer && Lampa.Layer.visible) Lampa.Layer.visible(root);
            return;
        }
        if (state.ended || state.pending || comp.next_wait || state.retryAt > now) return;
        diagnostic.last = {component: current.active.component, cards: count, requests: state.requests};
        try {
            if (state.main && typeof comp.loadNext === 'function') comp.loadNext();
            else if (typeof comp.emit === 'function' && comp.scroll && Array.isArray(comp.items)) comp.emit('loadNext');
            else if (!state.main && typeof comp.next === 'function') comp.next();
        } catch (error) {
            state.retryAt = now + 15000;
            console.warn('Lampa prefetch:', error.message);
        }
    }

    diagnostic.check = tick;
    var waits = 0;
    function start() {
        if (!window.Lampa || !Lampa.Activity || !Lampa.Listener) {
            if (++waits < 300) setTimeout(start, 200);
            return;
        }
        Lampa.Listener.follow('activity', function (event) {
            if (event && (event.type === 'init' || event.type === 'create' || event.type === 'start' || event.type === 'archive')) {
                inspect(event.object);
                setTimeout(tick, 100);
            }
        });
        // Handles both remote/transform scrolling and normal browser scrolling.
        setInterval(tick, 350);
        tick();
    }
    start();
})();
"""


def update(path, remove=False):
    original = path.read_text(encoding='utf-8-sig')
    clean = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', '', original, flags=re.S)
    if not remove and 'Lampa' not in original:
        raise ValueError('Не найден код Lampa; файл не изменён')
    updated = clean if remove else BEGIN + '\n' + SCRIPT + '\n' + END + '\n' + clean
    if updated == original:
        print('Уже установлено' if not remove else 'Уже удалено')
        return
    backup = path.with_name(path.name + '.before-prefetch-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path, backup)
    with path.open('w', encoding='utf-8') as stream:
        stream.write(updated)
        stream.flush()
        os.fsync(stream.fileno())
    print('Резервная копия:', backup)
    print('Предзагрузка ' + ('удалена' if remove else 'установлена'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', type=Path, required=True)
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    update(args.path, args.remove)
