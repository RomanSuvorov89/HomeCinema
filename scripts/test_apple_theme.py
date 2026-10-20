import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('apple_theme',ROOT/'scripts/set-apple-theme.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ThemeTest(unittest.TestCase):
    def test_background_and_badges(self):
        css=(ROOT/'themes/apple-tv.css').read_text()
        self.assertIn('.background canvas { visibility: hidden !important; }', css)
        self.assertNotIn('display: none', css)
        badge=css.split('.homecinema-apple .roman-card-rating {')[1].split('}')[0]
        self.assertNotIn('background:', badge)
        self.assertNotIn('color:', badge)

    def test_install_and_remove_preserve_every_other_block_and_inode(self):
        original='/* family-sync */\n/* posters */\n/* home actions */\nfunction start() {var plugins_add = {initiale};}\n'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'lampainit.js';path.write_text(original);inode=path.stat().st_ino
            block=module.bundle(ROOT)
            module.update(path,block)
            self.assertTrue(path.read_text().endswith(original))
            self.assertEqual(path.read_text().count(module.BEGIN),1)
            self.assertNotIn('__HOMECINEMA_APPLE_CSS__',path.read_text())
            module.update(path,block)
            self.assertEqual(len(list(path.parent.glob('*.before-apple-theme-*'))),1)
            module.update(path)
            self.assertEqual(path.read_text(),original)
            self.assertEqual(path.stat().st_ino,inode)

if __name__=='__main__':unittest.main()
