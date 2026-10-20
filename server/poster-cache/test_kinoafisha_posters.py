import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from kinoafisha_posters import BASE, Page, KinoafishaPosters, image_url

ROOT = BASE + '/series/example/'
MAIN = '<h1>Пример (2020 - &hellip;)</h1><p>Год выпуска 2020</p><meta property="og:image" content="//static.kinoafisha.info/main.jpg"><a href="/series/example/seasons/s2/">2</a>'
SEASON = '<h1>Пример: 2 сезон</h1><div class="seasonPoster"><img data-src="//static.kinoafisha.info/season.jpg"></div>'

class PostersTest(unittest.TestCase):
    def test_season_then_main_and_verified_identity(self):
        pages={ROOT:MAIN,ROOT+'seasons/s2/':SEASON}
        with tempfile.TemporaryDirectory() as folder:
            provider=KinoafishaPosters(Path(folder),fetch=pages.__getitem__)
            with patch.object(provider,'media',return_value=({'title':'Пример','original_title':'Example','release_year':2020},ROOT)):
                self.assertEqual(provider.sources('1',2),[
                    ('kinoafisha-season','https://static.kinoafisha.info/season.jpg'),
                    ('kinoafisha-main','https://static.kinoafisha.info/main.jpg')])
                self.assertEqual(provider.sources('1',3),[('kinoafisha-main','https://static.kinoafisha.info/main.jpg')])

    def test_wrong_year_never_uses_poster(self):
        provider=KinoafishaPosters('/not-present',fetch=lambda _:MAIN)
        with patch.object(provider,'media',return_value=({'title':'Пример','original_title':'Example','release_year':2021},ROOT)):
            with self.assertRaisesRegex(ValueError,'identity'):
                provider.sources('1',2)

    def test_broken_season_falls_back_to_main(self):
        provider=KinoafishaPosters('/not-present',fetch=lambda url:MAIN if url==ROOT else '<h1>Нет изображения</h1>')
        with patch.object(provider,'media',return_value=({'title':'Пример','original_title':'Example','release_year':2020},ROOT)):
            self.assertEqual(provider.sources('1',2),[('kinoafisha-main','https://static.kinoafisha.info/main.jpg')])

    def test_unrelated_images_and_untrusted_hosts_are_not_posters(self):
        self.assertIsNone(Page('<img src="https://static.kinoafisha.info/advert.jpg">').poster())
        for url in ('http://static.kinoafisha.info/a.jpg','https://kinoafisha.info.evil.org/a.jpg','file:///tmp/a.jpg'):
            self.assertIsNone(image_url(url))
        self.assertEqual(Page(SEASON).poster(),'https://static.kinoafisha.info/season.jpg')

if __name__=='__main__':unittest.main()
