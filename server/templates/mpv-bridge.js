/* roman-mpv-bridge:start */
(function romanMpvBridge() {
    'use strict';

    if (window.roman_mpv_bridge_loaded) return;
    window.roman_mpv_bridge_loaded = true;

    var API = 'http://127.0.0.1:19777';
    var pollTimer = null;
    var active = null;
    var lastSavedAt = 0;
    var subtitleListenerReady = false;

    function log() {
        var args = Array.prototype.slice.call(arguments);
        args.unshift('[Roman MPV Bridge]');
        console.log.apply(console, args);
    }

    function notify(message) {
        if (window.Lampa && Lampa.Noty) Lampa.Noty.show(message);
    }

    function isWindowsBrowser() {
        return /Windows/i.test(navigator.userAgent || '') &&
            !(window.Lampa && Lampa.Platform && Lampa.Platform.is('android'));
    }

    function enabled() {
        return isWindowsBrowser() && Lampa.Storage.field('roman_mpv_bridge') !== false;
    }

    function rawTorrentUrl(data) {
        if (!data || !data.torrent_hash || !data.path || data.id === undefined) return '';
        var filename = String(data.path).split('\\').pop().split('/').pop();
        return Lampa.Torserver.url() + '/stream/' + encodeURIComponent(filename) +
            '?link=' + encodeURIComponent(data.torrent_hash) +
            '&index=' + encodeURIComponent(data.id) + '&play';
    }

    function saveTimeline(force) {
        if (!active || !active.data || !active.status) return;
        var timeline = active.data.timeline;
        var time = Number(active.status.time || 0);
        var duration = Number(active.status.duration || 0);
        if (!timeline || typeof timeline.handler !== 'function' || !duration || time < 0) return;

        var now = Date.now();
        if (!force && now - lastSavedAt < 10000) return;
        lastSavedAt = now;

        var percent = Math.max(0, Math.min(100, Math.round(time / duration * 100)));
        timeline.handler(percent, time, duration);

        if (force && typeof active.data.viewed === 'function') {
            active.data.viewed(Math.round(time));
        }
    }

    function stopPolling(saveFinal) {
        if (pollTimer) {
            clearTimeout(pollTimer);
            pollTimer = null;
        }
        if (saveFinal) saveTimeline(true);
        active = null;
    }

    function poll() {
        if (!active) return;
        fetch(API + '/status?id=' + encodeURIComponent(active.id), {
            method: 'GET',
            cache: 'no-store'
        }).then(function (response) {
            if (!response.ok) throw new Error('HTTP ' + response.status);
            return response.json();
        }).then(function (status) {
            if (!active) return;
            active.status = status;
            if (window.RomanTrackMemory) {
                var sessionId = active.id;
                window.RomanTrackMemory.mpv(status, function (selection) {
                    return fetch(API + '/track-selection', {
                        method:'POST', headers:{'Content-Type':'application/json'},
                        body:JSON.stringify({id:sessionId,selection:selection})
                    }).then(function (response) {if(!response.ok) throw new Error('HTTP '+response.status);});
                });
            }
            if (status.state === 'ended' || status.state === 'unknown') {
                saveTimeline(true);
                notify('MPV закрыт, позиция сохранена');
                stopPolling(false);
                return;
            }
            saveTimeline(false);
            pollTimer = setTimeout(poll, 2000);
        }).catch(function (error) {
            log('status error', error);
            pollTimer = setTimeout(poll, 3000);
        });
    }

    function launch(data) {
        var url = rawTorrentUrl(data);
        if (!url) {
            notify('Не удалось построить прямую ссылку TorrServer');
            return;
        }

        stopPolling(true);
        var payload = {
            url: url,
            start: data.timeline ? Number(data.timeline.time || 0) : 0
        };

        fetch(API + '/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function (response) {
            if (!response.ok) throw new Error('HTTP ' + response.status);
            return response.json();
        }).then(function (result) {
            active = {
                id: result.id,
                data: data,
                status: null
            };
            lastSavedAt = 0;
            notify('Запущено в MPV');
            pollTimer = setTimeout(poll, 700);
        }).catch(function (error) {
            log('launch error', error);
            var detail = error && error.message ? String(error.message) : 'неизвестная ошибка';
            notify('MPV Bridge: ' + detail);
        });
    }

    function registerSettings() {
        if (!Lampa.SettingsApi || typeof Lampa.SettingsApi.addParam !== 'function') return;
        Lampa.SettingsApi.addParam({
            component: 'player',
            param: {
                name: 'roman_mpv_bridge',
                type: 'trigger',
                default: true
            },
            field: {
                name: 'Открывать торренты в MPV на Windows',
                description: 'Исходный поток TorrServer, внешняя громкость и синхронизация позиции'
            }
        });
    }

    function subtitleText(track) {
        return [track && track.language, track && track.lang, track && track.label,
            track && track.title, track && track.name]
            .filter(Boolean).join(' ').toLowerCase();
    }

    function isRussianSubtitle(track) {
        var language = String(track && (track.language || track.lang) || '').toLowerCase();
        var text = subtitleText(track);
        return /^(ru|rus)([-_]|$)/.test(language) ||
            /(^|[^a-zа-я])(ru|rus|russian|рус|русск)/i.test(text);
    }

    function isForcedSubtitle(track) {
        var text = subtitleText(track);
        return !!(track && track.forced) ||
            /(forced|форс|надпис|signs?|songs?|песн)/i.test(text);
    }

    function isFullSubtitle(track) {
        return /(full|complete|полные|полный|полная|полностью)/i.test(subtitleText(track));
    }

    function setSubtitleMode(track, mode) {
        if (!track) return;
        try { track.mode = mode; } catch (e) {}
        try { track.selected = mode === 'showing'; } catch (e) {}
    }

    function selectRussianFullSubtitles(tracks) {
        if (window.RomanTrackMemory) return;
        if (!Array.isArray(tracks) || !tracks.length) return;

        var russian = tracks.filter(function (track) {
            return isRussianSubtitle(track) && !isForcedSubtitle(track);
        });

        russian.sort(function (left, right) {
            return Number(isFullSubtitle(right)) - Number(isFullSubtitle(left));
        });

        tracks.forEach(function (track) { setSubtitleMode(track, 'disabled'); });

        if (russian.length) {
            setSubtitleMode(russian[0], 'showing');
            if (Lampa.PlayerVideo && typeof Lampa.PlayerVideo.subsview === 'function') {
                Lampa.PlayerVideo.subsview(true);
            }
            log('subtitle selected', subtitleText(russian[0]));
        }
        else if (Lampa.PlayerVideo && typeof Lampa.PlayerVideo.subsview === 'function') {
            Lampa.PlayerVideo.subsview(false);
            log('russian full subtitles not found');
        }
    }

    function registerSubtitleSelection() {
        if (subtitleListenerReady) return;
        if (!Lampa.PlayerVideo || !Lampa.PlayerVideo.listener) {
            setTimeout(registerSubtitleSelection, 250);
            return;
        }
        subtitleListenerReady = true;
        Lampa.Storage.set('subtitles_start', true);
        Lampa.PlayerVideo.listener.follow('subs', function (event) {
            var tracks = event && Array.isArray(event.subs) ? event.subs : [];
            setTimeout(function () { selectRussianFullSubtitles(tracks); }, 50);
            setTimeout(function () { selectRussianFullSubtitles(tracks); }, 500);
        });
    }

    function start() {
        if (!window.Lampa || !Lampa.Player || !Lampa.Player.listener) {
            setTimeout(start, 100);
            return;
        }

        registerSettings();
        registerSubtitleSelection();
        Lampa.Player.listener.follow('create', function (event) {
            var data = event && event.data;
            if (!enabled() || !data || !data.torrent_hash) return;
            if (!rawTorrentUrl(data)) return;
            event.abort();
            launch(data);
        });
        log('ready');
    }

    start();
})();
/* roman-mpv-bridge:end */
