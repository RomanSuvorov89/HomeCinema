import tempfile
import unittest
from pathlib import Path
from install import install

class InstallTest(unittest.TestCase):
    def test_existing_plugins_preserved_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'lampainit.js'
            target.write_text('function start() {\nvar plugins_add = {initiale};\n/* roman-kinopoisk-local */\nplugins_add.push({url:"http://127.0.0.1:9120/kinopoisk.js"});\n/* Family Sync and MPV stay here */\n}')
            install(target)
            first = target.read_text()
            self.assertLess(first.index('internal_torrclient'), first.index('var plugins_add'))
            self.assertIn('Family Sync and MPV stay here', first)
            install(target)
            self.assertEqual(first, target.read_text())
            self.assertEqual(len(list(Path(directory).glob('*.before-tv-*'))), 1)
    def test_invalid_file_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'lampainit.js'
            target.write_text('function unrelated() {}')
            with self.assertRaises(ValueError): install(target)
            self.assertEqual(target.read_text(), 'function unrelated() {}')

if __name__ == '__main__': unittest.main()
