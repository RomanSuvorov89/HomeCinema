"""Install the pinned Lampa UI before starting Lampac; no personal data involved."""
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import zipfile

DEFAULT_REF = '0f50f0c4cb3f602ecaff84925dca07f96bbd38a8'


def reference(source):
    match = re.search(r'\btree\s*=\s*"([a-f0-9]{40})"', source)
    return match[1] if match else DEFAULT_REF


def install(archive, target, ref):
    if not re.fullmatch(r'[a-f0-9]{40}', ref):
        raise ValueError('Invalid Lampa commit')
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        stage = Path(temporary) / 'ui'
        stage.mkdir()
        prefix = 'lampa-' + ref
        with zipfile.ZipFile(archive) as bundle:
            if sum(i.file_size for i in bundle.infolist()) > 128 * 1024 * 1024:
                raise ValueError('Lampa archive is too large')
            for info in bundle.infolist():
                path = PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != prefix:
                    raise ValueError('Unexpected Lampa archive path')
                if info.is_dir() or len(path.parts) == 1:
                    continue
                output = stage.joinpath(*path.parts[1:])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(bundle.read(info))
        for filename in ('index.html', 'app.min.js', 'css/app.css'):
            if not (stage / filename).is_file() or not (stage / filename).stat().st_size:
                raise ValueError('Incomplete Lampa archive: ' + filename)
        index = stage / 'index.html'
        html = index.read_text()
        if '</body>' not in html:
            raise ValueError('Invalid Lampa HTML')
        if '/lampainit.js' not in html:
            html = html.replace('</body>', '<script src="/lampainit.js"></script></body>')
        index.write_text(html)
        (stage / 'tree').write_text(ref)
        (stage / 'personal.lampa').touch()
        (stage / 'plugins').mkdir(exist_ok=True)
        (stage / 'plugins/modification.js').touch()
        if not (stage / 'plugins_black_list.json').exists():
            (stage / 'plugins_black_list.json').write_text('[]')
        # umask 077 is correct for secrets, but UI files must be readable in Lampac.
        for item in [stage, *stage.rglob('*')]:
            item.chmod(0o755 if item.is_dir() else 0o644)
        backup = target.with_name(target.name + '.before-install')
        if backup.exists():
            raise ValueError('Previous web backup exists: ' + str(backup))
        if target.exists():
            target.rename(backup)
        try:
            stage.rename(target)
        except BaseException:
            if backup.exists():
                backup.rename(target)
            raise
        if backup.exists():
            shutil.rmtree(backup)


def prepare(target, source=''):
    ref = reference(source)
    target = Path(target)
    if all((target / name).is_file() and (target / name).stat().st_size for name in ('index.html', 'app.min.js', 'css/app.css', 'tree')):
        if (target / 'tree').read_text().strip() == ref and '/lampainit.js' in (target / 'index.html').read_text():
            print('Lampa web files already prepared: ' + ref)
            return
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / 'lampa.zip'
        subprocess.run(['curl', '-fSL', '--connect-timeout', '5', '--max-time', '90',
                        '--retry', '2', '-o', str(archive),
                        'https://codeload.github.com/yumata/lampa/zip/' + ref], check=True)
        install(archive, target, ref)
    print('Lampa web files prepared: ' + ref)


if __name__ == '__main__':
    import sys
    prepare(sys.argv[1], Path(sys.argv[2]).read_text() if len(sys.argv) > 2 and Path(sys.argv[2]).is_file() else '')
