"""Check the actual UI, not only the independent /version endpoint."""
import sys
from urllib.request import ProxyHandler, build_opener


def check(base):
    opener = build_opener(ProxyHandler({}))
    for path in ('/', '/lampa-main/app.min.js', '/lampa-main/css/app.css', '/lampainit.js'):
        with opener.open(base.rstrip('/') + path, timeout=5) as response:
            body = response.read()
        if not body:
            raise ValueError('Empty UI response: ' + path)
        if path == '/' and (b'<html' not in body.lower() or b'/lampainit.js' not in body):
            raise ValueError('Root response is not the configured Lampa UI')
    print('Lampa HTML, scripts and styles are reachable')


if __name__ == '__main__':
    check(sys.argv[1])
