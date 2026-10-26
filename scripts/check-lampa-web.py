"""Check the actual UI, not only the independent /version endpoint."""
import re
import sys
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


def check(base, expected_file=None):
    expected = None
    if expected_file:
        match = re.search(r'/\* homecinema-build:([a-f0-9]{64}) \*/', Path(expected_file).read_text())
        if not match:
            raise ValueError('Generated client has no build marker')
        expected = match.group(0).encode()
    opener = build_opener(ProxyHandler({}))
    for path in ('/', '/lampa-main/app.min.js', '/lampa-main/css/app.css', '/lampainit.js'):
        with opener.open(base.rstrip('/') + path, timeout=5) as response:
            body = response.read()
        if not body:
            raise ValueError('Empty UI response: ' + path)
        if path == '/lampainit.js' and expected and expected not in body:
            raise ValueError('Lampac serves a previous or different client build; update is incomplete')
        if path == '/' and (b'<html' not in body.lower() or b'/lampainit.js' not in body):
            raise ValueError('Root response is not the configured Lampa UI')
    print('Lampa HTML, scripts and styles are reachable')


if __name__ == '__main__':
    check(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
