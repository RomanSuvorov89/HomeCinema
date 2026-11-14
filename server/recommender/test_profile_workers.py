import unittest
from unittest.mock import patch
import kp_sync

class ProfileWorkersTest(unittest.TestCase):
    def test_workers_keep_profile_context_and_wake_existing_worker(self):
        with patch.object(kp_sync,'HOME_CACHE',object()),patch.object(kp_sync,'HOME_WORKERS',{}), \
             patch.object(kp_sync,'home_personal_data',side_effect=lambda p:p), \
             patch('home_cache.start_worker') as start:
            kp_sync.ensure_home_worker('owner')
            kp_sync.ensure_home_worker('other')
            self.assertEqual([c.args[3]() for c in start.call_args_list],['owner','other'])
            kp_sync.ensure_home_worker('other')
            self.assertEqual(start.call_count,2)
            self.assertTrue(start.call_args_list[1].kwargs['wake'].is_set())

    def test_report_paths_reject_escape(self):
        with self.assertRaises(ValueError):kp_sync.profile_report_paths('../other')
