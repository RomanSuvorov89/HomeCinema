import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from contextlib import redirect_stderr

import server
from tmdb_metadata import TmdbMetadata


class MetadataTest(unittest.TestCase):
    key = 'a'*32
    payload = {'id':154598,'name':'Нулевой пациент','number_of_episodes':7}

    def download(self,args,**kwargs):
        Path(args[args.index('--output')+1]).write_text(json.dumps(self.payload))
        return type('Result',(),{'returncode':0})()

    def test_real_request_shape_cache_restart_and_no_credentials_on_disk(self):
        from urllib.parse import urlsplit,parse_qs
        with tempfile.TemporaryDirectory() as folder:
            cache=TmdbMetadata(folder)
            with patch('tmdb_metadata.subprocess.run',side_effect=self.download) as run:
                self.assertEqual(cache.get('tv/154598',self.key,'ru','keywords,credits'),self.payload)
                args=run.call_args.args[0]
                self.assertIn('--doh-url',args)
                self.assertEqual(urlsplit(args[-1]).netloc,'api.themoviedb.org')
                self.assertEqual(urlsplit(args[-1]).path,'/3/tv/154598')
                self.assertEqual(parse_qs(urlsplit(args[-1]).query)['append_to_response'],['credits,keywords'])
            with patch.object(TmdbMetadata,'fetch',side_effect=AssertionError('cache missed')):
                self.assertEqual(TmdbMetadata(folder).get('tv/154598',self.key,'ru','credits,keywords'),self.payload)
            for path in Path(folder).rglob('*'):
                if path.is_file(): self.assertNotIn(self.key,path.name+path.read_text())

    def test_invalid_resources_fail_without_network_and_stale_survives_outage(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=TmdbMetadata(folder)
            with patch.object(cache,'fetch',return_value=self.payload) as fetch:
                for resource in ('https://evil.test/x','tv/1/../../secret','account/1','tv/0','tv/1/watch/providers'):
                    with self.assertRaises(ValueError):cache.get(resource,self.key)
                with self.assertRaises(ValueError):cache.get('tv/1',self.key,append='account')
                with self.assertRaises(ValueError):cache.get('tv/1','bad')
                fetch.assert_not_called()
                cache.get('tv/154598',self.key)
            path=next(Path(folder).glob('*.json'));os.utime(path,(0,0))
            with patch.object(cache,'fetch',side_effect=OSError('offline')) as fetch:
                self.assertEqual(cache.get('tv/154598',self.key),self.payload)
                self.assertEqual(cache.get('tv/154598',self.key),self.payload)
                fetch.assert_called_once()

    def test_wrong_card_and_blocked_responses_are_not_cached(self):
        for payload in ({'blocked':True},{'id':42,'name':'Wrong card'}, {'success':False}, []):
            with tempfile.TemporaryDirectory() as folder:
                cache=TmdbMetadata(folder)
                def download(args,**kwargs):
                    Path(args[args.index('--output')+1]).write_text(json.dumps(payload))
                    return type('Result',(),{'returncode':0})()
                with patch('tmdb_metadata.subprocess.run',side_effect=download):
                    with self.assertRaises(OSError):cache.get('tv/154598',self.key)
                self.assertEqual(list(Path(folder).iterdir()),[])

    def test_http_validation_cors_and_logs_hide_query(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=TmdbMetadata(folder)
            with patch.object(server,'TMDB_METADATA',cache),patch.object(cache,'fetch',return_value=self.payload):
                http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
                worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
                base='http://127.0.0.1:'+str(http.server_port)
                logs=io.StringIO()
                try:
                    with redirect_stderr(logs):
                        with urlopen(base+'/tmdb/metadata/tv/154598?api_key='+self.key) as response:
                            self.assertEqual(json.load(response),self.payload)
                            self.assertEqual(response.headers['Access-Control-Allow-Origin'],'*')
                        with self.assertRaises(HTTPError) as error:urlopen(base+'/tmdb/metadata/tv/154598?api_key=bad')
                        self.assertEqual(error.exception.code,400)
                    self.assertNotIn(self.key,logs.getvalue())
                finally:
                    http.shutdown();http.server_close();worker.join()


if __name__=='__main__':unittest.main()
