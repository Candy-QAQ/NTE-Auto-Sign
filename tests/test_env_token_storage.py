import contextlib
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nte


class EnvironmentTokenStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache_path = os.path.join(self.directory.name, 'cache.json')
        self.source = {
            'refreshToken': 'fake-initial',
            'uid': '1',
            'deviceId': 'device1',
            'roleIds': ['role1'],
        }
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch.multiple(
            nte,
            token_env=json.dumps(self.source),
            token_cache_name=self.cache_path,
            token_save_name=os.path.join(self.directory.name, 'TOKEN.txt'),
            select_accounts_env=None,
        ))
        self.enterContext(patch.object(nte, 'app_signin', return_value=(True, 'ok')))
        self.enterContext(patch.object(nte, 'game_signin', return_value=(True, 'ok')))
        self.refresh = self.enterContext(patch.object(
            nte, 'refresh_access_token', side_effect=self.rotate_token
        ))
        self.received_tokens = []

    def rotate_token(self, account):
        self.received_tokens.append(account['refreshToken'])
        account['refreshToken'] += '-next'
        return 'fake-access'

    def test_second_run_uses_rotated_token_and_fresh_process_reads_cache(self):
        self.assertTrue(nte.start())
        self.assertTrue(nte.start())
        self.assertEqual(self.received_tokens, ['fake-initial', 'fake-initial-next'])
        self.assertFalse(os.path.exists(nte.token_save_name))
        code = (
            'import sys;sys.path.insert(0,sys.argv[1]);import nte;'
            'nte.token_env=sys.argv[2];nte.token_cache_name=sys.argv[3];'
            'assert nte.read_from_env()[0]["refreshToken"]=="fake-initial-next-next"'
        )
        child = subprocess.run(
            [sys.executable, '-c', code, os.path.dirname(nte.__file__),
             nte.token_env, self.cache_path],
            capture_output=True, timeout=10,
        )
        self.assertEqual(child.returncode, 0, child.stderr.decode(errors='replace'))

    def test_refresh_persisted_before_community_failure(self):
        def fail_community(*args):
            self.assertEqual(nte.read_from_env()[0]['refreshToken'], 'fake-initial-next')
            raise RuntimeError('simulated failure')

        with patch.object(nte, 'app_signin', side_effect=fail_community), \
                self.assertLogs(level='ERROR'):
            self.assertFalse(nte.start())
        self.assertTrue(nte.start())
        self.assertEqual(self.received_tokens[-1], 'fake-initial-next')

    def test_qinglong_entry_uses_cache_across_runs(self):
        with patch.dict(os.environ, {'NTE_TOKEN': nte.token_env}), \
                patch.object(nte, 'config_logger'):
            entry = runpy.run_path(os.path.join(os.path.dirname(nte.__file__), 'qinglong.py'))
            self.assertTrue(entry['main']())
            self.assertTrue(entry['main']())
        self.assertEqual(self.received_tokens, ['fake-initial', 'fake-initial-next'])

    def test_cloud_only_account_keeps_working(self):
        source = json.dumps({'cloudToken': 'fake-cloud', 'cloudUserId': '1'})
        with patch.object(nte, 'token_env', source), \
                patch.object(nte, 'cloud_claim_daily_duration', return_value=(True, 'ok')):
            self.assertTrue(nte.start())
            self.assertTrue(nte.start())
            self.assertEqual(nte.read_from_env()[0]['cloudToken'], 'fake-cloud')
        self.refresh.assert_not_called()

    def test_legacy_raw_token_retains_generated_device_id(self):
        with patch.object(nte, 'token_env', 'fake-legacy'):
            accounts = nte.read_from_env()
            device_id = accounts[0]['deviceId']
            accounts[0]['refreshToken'] = 'fake-legacy-next'
            nte.save_env_accounts(accounts)
            restored = nte.read_from_env()[0]
            self.assertEqual(restored['deviceId'], device_id)
            self.assertEqual(restored['refreshToken'], 'fake-legacy-next')

    def test_config_reorder_addition_removal_and_relogin(self):
        self.assertTrue(nte.start())
        other = dict(self.source, refreshToken='fake-other', uid='2', deviceId='device2')
        reformatted = json.dumps(dict(reversed(list(self.source.items()))), separators=(',', ':'))
        with patch.object(nte, 'token_env', json.dumps(other) + '\n' + reformatted):
            self.assertTrue(nte.start())
        self.assertEqual(self.received_tokens[-2:], ['fake-other', 'fake-initial-next'])
        self.assertTrue(nte.start())
        self.assertEqual(self.received_tokens[-1], 'fake-initial-next-next')
        with patch.object(nte, 'token_env', json.dumps(dict(self.source, refreshToken='fake-relogin'))):
            self.assertTrue(nte.start())
        self.assertEqual(self.received_tokens[-1], 'fake-relogin')

    def test_duplicate_configuration_rotates_only_once(self):
        with patch.object(nte, 'token_env', nte.token_env + '\n' + nte.token_env):
            self.assertTrue(nte.start())
        self.refresh.assert_called_once()

    def test_atomic_write_failure_preserves_previous_cache(self):
        self.assertTrue(nte.start())
        accounts = nte.read_from_env()
        accounts[0]['refreshToken'] = 'fake-not-saved'
        with patch.object(nte.os, 'replace', side_effect=PermissionError('test')):
            with self.assertRaises(PermissionError):
                nte.save_env_accounts(accounts)
        self.assertEqual(nte.read_from_env()[0]['refreshToken'], 'fake-initial-next')

    def test_unwritable_cache_stops_before_refresh(self):
        with patch.object(nte, 'save_env_accounts', side_effect=PermissionError('test')):
            self.assertFalse(nte.start())
        self.refresh.assert_not_called()

    def test_busy_cache_stops_before_refresh(self):
        with nte.account_file_lock(self.cache_path):
            self.assertFalse(nte.start())
        self.refresh.assert_not_called()

    def test_malformed_cache_stops_before_refresh(self):
        nte._atomic_write_text(self.cache_path, '{')
        with self.assertLogs(level='ERROR'):
            self.assertFalse(nte.start())
        self.refresh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
