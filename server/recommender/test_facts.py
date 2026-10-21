import json
import os
from pathlib import Path
import tempfile
import unittest
import facts

class FactsTest(unittest.TestCase):
    def test_next_data_only_trivia_and_safe_text_no_related_movie(self):
        page='<script id="__NEXT_DATA__">'+json.dumps({'props':{'facts':{'items':[
            {'text':'Факт <b>о съёмках</b> достаточно длинный.','spoiler':False},
            {'text':'Развязка сюжета — это отмеченный спойлер.','spoiler':True},
            {'text':'Факт о съёмках достаточно длинный.'},
            {'text':'Факт другого фильма не должен попасть в выдачу.','filmId':999}]},
            'recommendations':[{'description':'Описание другого фильма не является фактом.'}]}})+'</script>'
        items=facts.parse_facts(page,'42')
        self.assertEqual(len(items),2)
        self.assertEqual(items[0],{'text':'Факт о съёмках достаточно длинный.','spoiler':False})
        self.assertTrue(items[1]['spoiler'])

    def test_html_trivia_and_identity_guard(self):
        page='<link rel="canonical" href="https://www.kinopoisk.ru/film/42/didyouknow/"><div class="trivia">Подтверждённый <a>факт о съёмках</a> фильма.</div><p>Навигация</p>'
        self.assertEqual(len(facts.parse_facts(page,'42')),1)
        with self.assertRaises(ValueError):facts.parse_facts(page,'43')

    def test_cache_and_stale_on_captcha(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return '<script id="__NEXT_DATA__">'+json.dumps({'facts':[{'text':'Опубликованный факт о производстве сериала.'}]})+'</script>'
        with tempfile.TemporaryDirectory() as root:
            first=facts.get_facts(root,'42','tv',fetch)
            self.assertEqual(calls,['https://www.kinopoisk.ru/series/42/didyouknow/'])
            self.assertEqual(facts.get_facts(root,'42','tv',lambda _:self.fail('network')),first)
            first['checked_at']=0;(Path(root)/'42.json').write_text(json.dumps(first))
            stale=facts.get_facts(root,'42','tv',lambda _:'<html>SmartCaptcha</html>')
            self.assertTrue(stale['stale']);self.assertEqual(stale['items'],first['items'])

    def test_blocked_source_never_invents_facts_and_backs_off(self):
        with tempfile.TemporaryDirectory() as root:
            calls=[]
            def blocked(url):calls.append(url);return '<html>SmartCaptcha</html>'
            result=facts.get_facts(root,'42','movie',blocked)
            self.assertEqual(result['items'],[]);self.assertTrue(result['error'])
            facts.get_facts(root,'42','movie',blocked)
            self.assertEqual(len(calls),1)
            with self.assertRaises(ValueError):facts.get_facts(root,'../42','movie',blocked)
            with self.assertRaises(ValueError):facts.get_facts(root,'42','http://evil.test',blocked)

if __name__=='__main__':unittest.main()
