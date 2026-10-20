#!/usr/bin/env python3
"""Render central plugins from configured public LAN addresses; no runtime databases."""
import importlib.util
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent

def load(name):
    spec = importlib.util.spec_from_file_location(name, PROJECT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def public_url(key):
    value = os.environ[key].rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.query or parsed.fragment or parsed.username or any(c in value for c in "'\"\\\r\n"):
        raise ValueError('Invalid public URL: ' + key)
    return value

def render():
    lampac = public_url('PUBLIC_LAMPAC_URL')
    torrserver = public_url('PUBLIC_TORRSERVER_URL')
    recommender = public_url('PUBLIC_RECOMMENDER_URL')
    posters = public_url('PUBLIC_POSTER_URL')
    token = os.environ['LAMPAC_SYNC_ID']
    if not re.fullmatch(r'[A-Za-z0-9._-]+', token):
        raise ValueError('Invalid LAMPAC_SYNC_ID')
    source = ROOT / 'data/lampac/lampainit.upstream.js'
    target = source.with_name('lampainit.js')
    text = source.read_text(encoding='utf-8')
    anchor = 'var plugins_add = {initiale};'
    if text.count(anchor) != 1 or not re.search(r'function\s+start\s*\(\s*\)\s*\{', text):
        raise ValueError('Unsupported upstream Lampac initialization: no files changed')
    rec = ROOT / 'recommender'
    rendered = {}
    for name in ('client-defaults.js', 'kinopoisk.js', 'client-bootstrap.js'):
        rendered[name] = (rec / (name + '.template')).read_text().replace('__RECOMMENDER_PUBLIC_URL__', recommender).replace('__TORRSERVER_PUBLIC_URL__', torrserver)
    payload = []
    for name in ('client-defaults.js', 'kinopoisk.js', 'track-memory.js'):
        body = rendered.get(name) or (rec / name).read_text()
        payload.append("try {\n" + body + "\n} catch(e) {report('" + name + "',e.stack || e.message);}")
        if name == 'kinopoisk.js':
            payload.append('window.romanEmbedded054 = !!window.romanKinopoiskStarted;')
    bootstrap = rendered['client-bootstrap.js'].replace('/* ROMAN_EMBEDDED_PAYLOAD */', '\n'.join(payload))
    sync_url = lampac + '/sync/js/' + token
    block = anchor + r'''
    /* home-cinema-stack:plugins */
    plugins_add = plugins_add.filter(function (p) {
        return !/\/(?:ts|sisi|sync|bookmark|timecode)(?:\.js|\/js\/)/.test(p.url || '');
    });
    plugins_add.push({name:'Family Sync',url:''' + json.dumps(sync_url) + ''',status:1});
    plugins_add.push({name:'Кинопоиск (локальный)',url:''' + json.dumps(recommender + '/kinopoisk.js') + ''',status:1});
'''
    if os.environ.get('ENABLE_COMMUNITY_PLUGINS', '0') == '1':
        for title, url in [('Подборки','https://lampaplugins.github.io/store/p.js'),('Категории','https://lampame.github.io/main/newcategory.js'),('Рейтинги','https://nb557.github.io/plugins/rating.js'),('Статус сериалов','https://levende.github.io/lampa-plugins/tv-status-color.js')]:
            block += '    plugins_add.push(' + json.dumps(dict(name=title,url=url,status=1),ensure_ascii=False) + ');\n'
    text = text.replace(anchor, block, 1)
    # Clean persisted duplicate families before upstream chooses plugins to load.
    family = r'''/* roman-family-sync */
(function(){
 var attempts=0, url=__SYNC_URL__;
 function configure(){
  if(!window.Lampa || !Lampa.Plugins){if(++attempts<300)setTimeout(configure,100);return;}
  var changed=false;
  if(typeof Lampa.Plugins.remove==='function')Lampa.Plugins.get().slice().forEach(function(p){
   if(/\/(sync|bookmark|timecode)(\.js|\/js\/)/.test(p.url || '') && (p.url!==url || !p.status)){
    Lampa.Plugins.remove(p.url); changed=true;
   }
  });
  if(changed)Lampa.Plugins.save();
 }
 configure();
})();
'''.replace('__SYNC_URL__',json.dumps(sync_url))
    watch = load('fix-family-watch')
    prefetch = load('fix-lampa-prefetch')
    watch_js = watch.SCRIPT.replace('__HOST__',json.dumps(lampac)).replace('__TOKEN__',json.dumps(token))
    poster_js = (ROOT / 'poster-cache/posters.js').read_text().replace("'__POSTER_BASE__'", json.dumps(posters))
    prefix = family + watch.BEGIN + '\n' + watch_js + '\n' + watch.END + '\n' + prefetch.BEGIN + '\n' + prefetch.SCRIPT + '\n' + prefetch.END + '\n/* roman-poster-cache:start */\n' + poster_js + '\n/* roman-poster-cache:end */\n/* roman-bootstrap-start */\n' + bootstrap + '\n/* roman-bootstrap-end */\n'
    if os.environ.get('APPLE_TV_THEME', '1') == '1':
        prefix = load('set-apple-theme').bundle(PROJECT) + prefix
    result = prefix + text + '\n' + (ROOT / 'templates/mpv-bridge.js').read_text() + '\n'
    for name, body in rendered.items():
        (rec / name).write_text(body,encoding='utf-8')
    if target.exists() and target.read_text() != result:
        shutil.copy2(target,target.with_name('lampainit.js.before-render-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
    # Preserve inode for an existing Docker file bind mount.
    target.write_text(result,encoding='utf-8')
    print('Rendered central client: catalog, sync, posters, prefetch, bridge')

if __name__ == '__main__':
    render()
