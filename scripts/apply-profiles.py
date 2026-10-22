#!/usr/bin/env python3
"""Prepare an existing installation; central JS is installed only after container checks."""
import argparse
import ast
from datetime import datetime
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile


def definition(text, name):
    node=next(n for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==name)
    return node, '\n'.join(text.splitlines()[node.lineno-1:node.end_lineno])+'\n'


def apply(target, lampainit, ref):
    if not re.fullmatch('[a-f0-9]{40}',ref):raise ValueError('Expected full commit SHA')
    for name in ('kp_sync.py','kinopoisk.js','client-bootstrap.js','install.py','Dockerfile'):
        if not (target/name).is_file():raise ValueError('Missing '+name)
    if not lampainit.is_file():raise ValueError('Missing central JS')
    original=(target/'kp_sync.py').read_text()
    client=(target/'kinopoisk.js').read_text()
    match=re.search(r"var DATA_URL\s*=\s*['\"]([^'\"]+)/data.json['\"]",client)
    if not match:raise ValueError('Cannot determine existing recommender URL')
    base=match[1]
    if not re.fullmatch(r'https?://[^\s\x22\x27\\]+',base):raise ValueError('Invalid existing URL')
    names=['kp_sync.py','profiles.py','profiles-client.js.template','kinopoisk.js.template',
           'client-bootstrap.js.template','install.py','test_profiles.py','facts.py','cloud_disk.py','connections.py','requirements-cloud.txt','test_cloud_disk.py']
    with tempfile.TemporaryDirectory() as temp:
        work=Path(temp)
        for name in names:
            subprocess.run(['curl','-fsSL','--connect-timeout','5','--max-time','30',
                'https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/'+ref+'/server/recommender/'+name,
                '-o',str(work/name)],check=True)
        patched=original
        for name in ('card_ratings','Handler','establish_session','sync','persist_database','refresh_file','refresh_loop'):
            old,_=definition(patched,name)
            _,new=definition((work/'kp_sync.py').read_text(),name)
            lines=patched.splitlines(keepends=True)
            patched=''.join(lines[:old.lineno-1])+new+''.join(lines[old.end_lineno:])
        # New helpers are inserted once; keep installation-specific settings intact.
        if 'def import_connected_profile(' not in patched:
            _,helper=definition((work/'kp_sync.py').read_text(),'import_connected_profile')
            patched=patched.replace('def refresh_file():',helper+'\ndef refresh_file():',1)
        if '# homecinema-cloud-worker' not in patched:
            anchor='        ThreadingHTTPServer(("0.0.0.0", 9120), Handler).serve_forever()'
            if anchor not in patched:raise ValueError('Unsupported server startup')
            patched=patched.replace(anchor,'''        # homecinema-cloud-worker
        from cloud_disk import manager
        from profiles import ensure
        connection = open_database()
        try:
            ensure(connection, PROFILE_ID, PROFILE_DISPLAY_NAME)
        finally:
            connection.close()
        manager(direct_connection, PROFILE_ID, DATA_FILE.parent / 'cloud')
'''+anchor,1)
        changes={target/'kp_sync.py':patched}
        for name in names[1:]:
            destination=name.removesuffix('.template')
            changes[target/destination]=(work/name).read_text().replace('__RECOMMENDER_PUBLIC_URL__',base)
        docker=(target/'Dockerfile').read_text()
        for name in ('profiles.py','profiles-client.js','test_profiles.py','facts.py','cloud_disk.py','connections.py','requirements-cloud.txt','test_cloud_disk.py'):
            if not re.search(r'^COPY\s+[^\n]*\b'+re.escape(name)+r'\b',docker,re.M):
                anchor='WORKDIR /app'
                if anchor not in docker:raise ValueError('Unsupported Dockerfile')
                docker=docker.replace(anchor,anchor+'\nCOPY '+name+' /app/'+name,1)
        if 'pip install --no-cache-dir -r /app/requirements-cloud.txt' not in docker:
            docker += '\nRUN pip install --no-cache-dir -r /app/requirements-cloud.txt\n'
        changes[target/'Dockerfile']=docker
        # Keep configured DNS service names; initial defaults must not erase a restored address.
        defaults_path=target/'client-defaults.js'
        if defaults_path.is_file():
            defaults=defaults_path.read_text()
            defaults=re.sub(r"(?m)^(\s*)storage\.set\('torrserver_(url|use_link)',",
                lambda match:match[1]+"if (!storage.get('torrserver_"+match[2]+"', '')) storage.set('torrserver_"+match[2]+"',",defaults)
            changes[defaults_path]=defaults
        ignore=target/'.dockerignore'
        ignore_text=ignore.read_text() if ignore.is_file() else ''
        for pattern in ('data/','__pycache__/','*.before-*','.env'):
            if pattern not in ignore_text.splitlines():ignore_text+='\n'+pattern+'\n'
        changes[ignore]=ignore_text
        for path,text in changes.items():
            if path.suffix=='.py':ast.parse(text)
            if '__RECOMMENDER_PUBLIC_URL__' in text:raise ValueError('Unrendered URL')
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup=target/'data'/'backups'/('before-profiles-'+stamp)
        backup.mkdir(parents=True,mode=0o700)
        for folder in (target/'data',lampainit.parent.parent/'database'):
            if not folder.is_dir():continue
            for path in folder.iterdir():
                if path.is_file() and path.suffix.lower() in ('.sql','.sqlite3','.sqlite','.db'):
                    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10) as source:
                        with sqlite3.connect(backup/(folder.name+'-'+path.name)) as destination:
                            source.backup(destination)
        for path in [*changes,lampainit]:
            if path.is_file():shutil.copy2(path,backup/path.name)
        for path,text in changes.items():path.write_text(text)
        print('Исходники подготовлены. Центральный JS пока не изменён.')
        print('Резервные копии баз и исходников:',backup)
        return backup


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('target',type=Path);p.add_argument('lampainit',type=Path);p.add_argument('ref')
    args=p.parse_args();apply(args.target.resolve(),args.lampainit.resolve(),args.ref)
