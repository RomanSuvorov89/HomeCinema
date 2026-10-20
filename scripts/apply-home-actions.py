#!/usr/bin/env python3
"""Update the existing client's actions without replacing its server addresses or configuration."""
import argparse
import ast
from datetime import datetime
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit


def apply(target, lampainit, ref):
    if not re.fullmatch('[a-f0-9]{40}',ref):raise ValueError('Expected full commit SHA')
    for name in ('kp_sync.py','review_api.py','kinopoisk.js','install.py','client-defaults.js','client-bootstrap.js','track-memory.js'):
        if not (target/name).is_file():raise ValueError('Missing existing file: '+name)
    if not lampainit.is_file():raise ValueError('Missing mounted lampainit.js')
    original_js=(target/'kinopoisk.js').read_text()
    match=re.search(r"var DATA_URL\s*=\s*['\"]([^'\"]+)/data.json['\"]",original_js)
    if not match:raise ValueError('Cannot determine existing recommender URL')
    base=match.group(1)
    if urlsplit(base).scheme not in ('http','https') or any(c in base for c in "'\"\\\r\n"):
        raise ValueError('Invalid existing recommender URL')
    with tempfile.TemporaryDirectory() as directory:
        work=Path(directory)
        for name in ('kp_sync.py','review_api.py','kinopoisk.js.template'):
            subprocess.run(['curl','-fsSL','--connect-timeout','5','--max-time','30',
                'https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/'+ref+'/server/recommender/'+name,
                '-o',str(work/name)],check=True)
        upstream=(work/'kp_sync.py').read_text()
        function=next(n for n in ast.parse(upstream).body if isinstance(n,ast.FunctionDef) and n.name=='rated_airing_series')
        new_function='\n'.join(upstream.splitlines()[function.lineno-1:function.end_lineno])+'\n'
        current=(target/'kp_sync.py').read_text()
        old=next(n for n in ast.parse(current).body if isinstance(n,ast.FunctionDef) and n.name=='rated_airing_series')
        lines=current.splitlines(keepends=True)
        patched=''.join(lines[:old.lineno-1])+new_function+''.join(lines[old.end_lineno:])
        anchor='''            self.review_response(200, HOME_CACHE.snapshot(PROFILE_ID) if HOME_CACHE else
                {"profile_id":PROFILE_ID,"rows":[],"status":[],"version":1})'''
        replacement='''            from review_api import home_snapshot
            connection=direct_connection()
            try:
                self.review_response(200, home_snapshot(connection, HOME_CACHE, PROFILE_ID))
            finally:
                connection.close()'''
        if anchor in patched:
            if patched.count(anchor)!=1:raise ValueError('Unexpected home.json handler')
            patched=patched.replace(anchor,replacement)
        elif replacement not in patched:raise ValueError('Unsupported home.json handler')
        changes={target/'kp_sync.py':patched,
                 target/'review_api.py':(work/'review_api.py').read_text(),
                 target/'kinopoisk.js':(work/'kinopoisk.js.template').read_text().replace('__RECOMMENDER_PUBLIC_URL__',base)}
        for path,text in changes.items():
            if path.suffix=='.py':ast.parse(text)
        originals={path:path.read_text() for path in changes}
        originals[lampainit]=lampainit.read_text()
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        for path in originals:shutil.copy2(path,path.with_name(path.name+'.before-home-actions-'+stamp))
        try:
            for path,text in changes.items():path.write_text(text)
            subprocess.run(['python3',str(target/'install.py'),str(lampainit)],check=True)
        except Exception:
            # Retain inode for the mounted central script, including on rollback.
            for path,text in originals.items():path.write_text(text)
            raise
        print('Обновлены действия и фильтрация. Адрес сервера:',base)
        print('Резервные копии: *.before-home-actions-'+stamp)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('lampainit',type=Path)
    parser.add_argument('ref')
    args=parser.parse_args()
    apply(args.directory.resolve(),args.lampainit.resolve(),args.ref)
