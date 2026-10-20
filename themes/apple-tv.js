(function () {
    'use strict';
    if (window.HomeCinemaAppleTheme) return;
    var css = __HOMECINEMA_APPLE_CSS__;
    var key = 'homecinema_appearance';
    var styleId = 'homecinema-apple-style';
    var attempts = 0;
    var registered = false;

    function apply(enabled) {
        if (!document.body) return;
        var style = document.getElementById(styleId);
        if (enabled) {
            if (!style) {
                style = document.createElement('style');
                style.id = styleId;
                style.textContent = css;
                document.head.appendChild(style);
            }
            document.body.classList.add('homecinema-apple');
        } else {
            document.body.classList.remove('homecinema-apple');
            if (style && style.parentNode) style.parentNode.removeChild(style);
        }
    }

    function setEnabled(enabled) {
        if (!window.Lampa || !Lampa.Storage) return;
        Lampa.Storage.set(key, enabled ? 'apple' : 'original');
        apply(!!enabled);
    }

    window.HomeCinemaAppleTheme = {setEnabled: setEnabled, version: 1};
    function start() {
        if (!window.Lampa || !Lampa.Storage || !document.body) {
            if (++attempts < 300) setTimeout(start, 100);
            return;
        }
        apply(Lampa.Storage.get(key, 'apple') === 'apple');
        if (!registered && Lampa.SettingsApi && Lampa.SettingsApi.addParam) {
            Lampa.SettingsApi.addParam({
                component: 'interface',
                param: {name: key, type: 'select', values: {apple: 'Apple TV', original: 'Стандартный вид'}, default: 'apple'},
                field: {name: 'Оформление HomeCinema', description: 'Тёмный графит, спокойные панели и белый фокус. Переключается без перезапуска.'},
                onChange: function (value) {setEnabled(value === 'apple');}
            });
            registered = true;
        } else if (!registered && ++attempts < 300) setTimeout(start, 100);
    }
    start();
})();
