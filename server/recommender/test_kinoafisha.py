import unittest
from kinoafisha import Page,load,series_url


def episode(season,number,day):
    return '''<div class="newSeriesList_item"><div class="newSeriesList_inner">
      <div class="newSeriesList_titlesBox"><span class="newSeriesList_title">Episode</span></div>
      <div class="newSeriesList_main"><div class="newSeriesList_numbersBox">
      <span class="newSeriesList_season">Сезон %s</span><span class="newSeriesList_series">Серия %s</span>
      </div></div><span class="newSeriesList_date">%s</span>
      <button data-param='{"type":"series"}'><svg><use></use></svg></button></div></div>'''%(season,number,day)


class KinoafishaTest(unittest.TestCase):
    media={'title':'Тест','original_title':'Test Show','release_year':2020}
    root='https://www.kinoafisha.info/series/test-show/'
    header='<h1>Тест (2020 - …)</h1><div>Год выпуска <b>2020</b></div>'

    def test_actual_row_structure_and_unrelated_dates(self):
        html='<script>Сезон 5 Серия 1 1 января 2027</script>'+episode(4,10,'7 октября 2026')
        html+='<div>Сезон 7 Серия 8 12 октября 2026 — реклама</div>'+episode(5,1,'31 февраля 2027')
        self.assertEqual(Page(html).episodes,[{'season':4,'episode':10,'date':'2026-10-07'}])

    def test_search_identity_seasons_and_cached_mapping(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if '/search/' in url:return '<a href="/series/test-show/"><img alt="Тест">2020</a>'
            if url==self.root:return self.header+'<a href="seasons/s4/">4</a><a href="seasons/s5/">5</a>'
            if '/s4/' in url:return episode(4,1,'5 августа 2026')+episode(4,10,'7 октября 2026')
            return episode(5,1,'Дата неизвестна')
        rows,url=load(self.media,fetch=fetch)
        self.assertEqual(url,self.root);self.assertEqual(len(rows),2)
        self.assertEqual(rows[-1]['date'],'2026-10-07')
        calls.clear();self.assertEqual(load(self.media,url,fetch)[0],rows)
        self.assertFalse(any('/search/' in u for u in calls))

    def test_wrong_year_and_ambiguous_matches_are_rejected(self):
        def ambiguous(url):
            if '/search/' in url:return '<a href="/series/test-show/">Тест</a><a href="/series/other/">Тест</a>'
            return self.header+episode(4,1,'5 августа 2026')
        with self.assertRaisesRegex(ValueError,'ambiguous'):load(self.media,fetch=ambiguous)
        def wrong_year(url):
            if '/search/' in url:return '<a href="/series/test-show/">Тест</a>'
            return '<h1>Тест (2021)</h1>'+episode(4,1,'5 августа 2026')
        with self.assertRaisesRegex(ValueError,'missing'):load(self.media,fetch=wrong_year)

    def test_cached_redirect_identity_and_foreign_urls(self):
        with self.assertRaisesRegex(ValueError,'no longer matches'):
            load(self.media,self.root,lambda url:'<h1>Другой сериал (2020)</h1>')
        self.assertIsNone(series_url('https://example.com/series/test/'))
        self.assertIsNone(series_url('/series/calendar/'))
        self.assertIsNone(series_url('/series/test-show/seasons/s4/'))

if __name__=='__main__':unittest.main()
