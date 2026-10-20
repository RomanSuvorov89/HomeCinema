#!/usr/bin/env python3
"""Install/remove only the Apple appearance block, preserving the mounted file inode."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

BEGIN='/* homecinema-apple:start */'
END='/* homecinema-apple:end */'


def bundle(root):
    js=(root/'themes/apple-tv.js').read_text(encoding='utf-8')
    if js.count('__HOMECINEMA_APPLE_CSS__')!=1:raise ValueError('Invalid theme template')
    css=(root/'themes/apple-tv.css').read_text(encoding='utf-8')
    return BEGIN+'\n'+js.replace('__HOMECINEMA_APPLE_CSS__',json.dumps(css,ensure_ascii=False))+'\n'+END+'\n'


def update(path, block=None):
    original=path.read_text(encoding='utf-8-sig')
    clean=re.sub(re.escape(BEGIN)+r'.*?'+re.escape(END)+r'\n?','',original,flags=re.S)
    updated=(block or '')+clean
    if updated==original:
        print('Оформление уже актуально' if block else 'Тема уже отключена')
        return
    backup=path.with_name(path.name+'.before-apple-theme-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path,backup)
    with path.open('w',encoding='utf-8') as stream:
        stream.write(updated);stream.flush();os.fsync(stream.fileno())
    print('Резервная копия:',backup)
    print('Тема Apple TV установлена' if block else 'Тема удалена; остальные плагины сохранены')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path',type=Path,required=True)
    parser.add_argument('--ref')
    parser.add_argument('--source-root',type=Path)
    parser.add_argument('--remove',action='store_true')
    args=parser.parse_args()
    if args.remove:
        update(args.path)
    elif args.source_root:
        update(args.path,bundle(args.source_root))
    else:
        if not args.ref or not re.fullmatch('[a-f0-9]{40}',args.ref):parser.error('--ref requires a full commit SHA')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'themes').mkdir()
            for name in ('apple-tv.js','apple-tv.css'):
                subprocess.run(['curl','-fsSL','--connect-timeout','5','--max-time','30',
                    'https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/'+args.ref+'/themes/'+name,
                    '-o',str(root/'themes'/name)],check=True)
            update(args.path,bundle(root))

if __name__=='__main__':main()
