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
           'client-bootstrap.js.template','install.py','test_profiles.py']
    with tempfile.TemporaryDirectory() as temp:
        work=Path(temp)
        for name in names:
            subprocess.run(['curl','-fsSL','--connect-timeout','5','--max-time','30',
                'https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/'+ref+'/server/recommender/'+name,
                '-o',str(work/name)],check=True)
        patched=original
        for name in ('card_ratings','Handler'):
            old,_=definition(patched,name)
            _,new=definition((work/'kp_sync.py').read_text(),name)
            lines=patched.splitlines(keepends=True)
            patched=''.join(lines[:old.lineno-1])+new+''.join(lines[old.end_lineno:])
        changes={target/'kp_sync.py':patched}
        for name in names[1:]:
            destination=name.removesuffix('.template')
            changes[target/destination]=(work/name).read_text().replace('__RECOMMENDER_PUBLIC_URL__',base)
        docker=(target/'Dockerfile').read_text()
        for name in ('profiles.py','profiles-client.js','test_profiles.py'):
            if not re.search(r'^COPY\s+[^\n]*\b'+re.escape(name)+r'\b',docker,re.M):
                anchor='WORKDIR /app'
                if anchor not in docker:raise ValueError('Unsupported Dockerfile')
                docker=docker.replace(anchor,anchor+'\nCOPY '+name+' /app/'+name,1)
        changes[target/'Dockerfile']=docker
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
