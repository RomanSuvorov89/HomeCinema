import sqlite3
import unittest
from track_preferences import read, save


class PreferencesTests(unittest.TestCase):
    def test_profiles_kinds_and_fallback_do_not_overwrite(self):
        c = sqlite3.connect(':memory:')
        payload = {'series_key':'kp:tv:123','kind':'audio',
                   'descriptor':{'lang':'ru','title':'lostfilm'}}
        save(c,'roman',payload)
        save(c,'other',dict(payload,descriptor={'lang':'en','title':'original'}))
        save(c,'roman',dict(payload,kind='sub',descriptor={'off':True}))
        result=read(c,'roman','kp:tv:123')['preferences']
        self.assertEqual(result['audio']['title'],'lostfilm')
        self.assertTrue(result['sub']['off'])
        self.assertEqual(read(c,'other','kp:tv:123')['preferences']['audio']['lang'],'en')
        self.assertEqual(read(c,'roman','kp:tv:456')['preferences'],{})
        with self.assertRaises(ValueError):
            save(c,'roman',dict(payload,series_key='movie:123'))
        with self.assertRaises(ValueError):
            save(c,'roman',dict(payload,descriptor={'off':'false'}))
        c.close()


if __name__ == '__main__':
    unittest.main()
