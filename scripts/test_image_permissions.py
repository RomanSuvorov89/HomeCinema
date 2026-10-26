"""Reproduce private-source COPY permissions without claiming a Docker build."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ImagePermissionsTest(unittest.TestCase):
    def test_private_sources_become_readable_only_inside_image(self):
        for service in ('recommender', 'poster-cache'):
            with self.subTest(service=service), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                base.chmod(0o755)
                app = base / 'app'
                app.mkdir(mode=0o700)
                private = base / 'private-config'
                private.write_text('private fixture')
                private.chmod(0o600)
                lines = (ROOT / 'server' / service / 'Dockerfile').read_text().splitlines()
                copy_positions = [i for i, line in enumerate(lines) if line.startswith('COPY ')]
                repair = 'RUN chmod -R a+rX /app'
                self.assertGreater(lines.index(repair), max(copy_positions))
                # Model COPY's ownership/mode retention with closed source files.
                for i in copy_positions:
                    for source in shlex.split(lines[i])[1:-1]:
                        target = app / Path(source).name
                        target.write_text('readable application fixture')
                        target.chmod(0o600)
                def drop_uid():
                    os.setgroups([])
                    os.setgid(65534)
                    os.setuid(65534)
                kwargs = {'preexec_fn': drop_uid} if os.geteuid() == 0 else {}
                probe = [sys.executable, '-c',
                         'from pathlib import Path; import sys; '
                         '[p.read_bytes() for p in Path(sys.argv[1]).iterdir()]', str(app)]
                self.assertEqual(app.stat().st_mode & 0o007, 0)
                if kwargs:
                    try:
                        before = subprocess.run(probe, capture_output=True, **kwargs)
                    except subprocess.SubprocessError:
                        # Restricted runtimes can report UID 0 without CAP_SETUID.
                        kwargs = {}
                        print('UID switch unavailable; verifying exact filesystem modes only')
                    else:
                        self.assertNotEqual(before.returncode, 0)
                        self.assertIn(b'PermissionError', before.stderr)
                command = shlex.split(repair.removeprefix('RUN '))
                command[-1] = str(app)
                subprocess.run(command, check=True)
                subprocess.run(probe, check=True, capture_output=True, **kwargs)
                self.assertEqual(private.stat().st_mode & 0o777, 0o600)
                self.assertEqual(app.stat().st_mode & 0o777, 0o755)
                for item in app.iterdir():
                    self.assertEqual(item.stat().st_mode & 0o777, 0o644)

if __name__ == '__main__':
    unittest.main()
