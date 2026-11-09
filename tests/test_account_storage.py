import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nte


class AccountStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch.multiple(
            nte,
            token_save_name=os.path.join(self.directory.name, 'TOKEN.txt'),
            token_env=None,
            select_accounts_env=None,
            current_type=None,
        ))
        self.accounts = [
            nte.parse_account_line('{"refreshToken":"fake-old","uid":"1","deviceId":"device1"}'),
            nte.parse_account_line('{"refreshToken":"fake-other","uid":"2","deviceId":"device2"}'),
        ]
        nte.save(self.accounts)

    def test_atomic_replace_failure_preserves_file(self):
        before = nte.read(nte.token_save_name)
        self.accounts[0]['refreshToken'] = 'fake-new'
        with patch.object(nte.os, 'replace', side_effect=PermissionError('test')):
            with self.assertRaises(PermissionError):
                nte.save(self.accounts)
        self.assertEqual(nte.read(nte.token_save_name), before)
        self.assertEqual(os.listdir(self.directory.name), ['TOKEN.txt'])

    def test_selected_account_preserves_other_accounts(self):
        def sign(account, persist=None):
            account['refreshToken'] = 'fake-new'
            persist()
            return True

        with patch.object(nte, 'select_accounts_env', '1'), \
                patch.object(nte, '_select_accounts', side_effect=lambda accounts: accounts[:1]), \
                patch.object(nte, 'do_sign', side_effect=sign):
            self.assertTrue(nte.start())
        saved = nte.read(nte.token_save_name)
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]['refreshToken'], 'fake-new')
        self.assertEqual(saved[1]['refreshToken'], 'fake-other')

    def test_refresh_is_saved_before_community_request(self):
        def refresh(account):
            account['refreshToken'] = 'fake-new'
            return 'fake-access'

        def community(*args):
            self.assertEqual(nte.read(nte.token_save_name)[0]['refreshToken'], 'fake-new')
            raise RuntimeError('simulated interruption after refresh')

        nte.save(self.accounts[:1])
        with patch.object(nte, 'refresh_access_token', side_effect=refresh), \
                patch.object(nte, 'app_signin', side_effect=community), self.assertLogs(level='ERROR'):
            self.assertFalse(nte.start())
        self.assertEqual(nte.read(nte.token_save_name)[0]['refreshToken'], 'fake-new')

    def test_second_process_cannot_lock_same_file(self):
        code = (
            'import sys;sys.path.insert(0,sys.argv[1]);import nte;'
            'nte.token_save_name=sys.argv[2];'
            'nte.account_file_lock().__enter__()'
        )
        with nte.account_file_lock():
            child = subprocess.run(
                [sys.executable, '-c', code, os.path.dirname(nte.__file__), nte.token_save_name],
                capture_output=True,
                timeout=10,
            )
            self.assertNotEqual(child.returncode, 0)
            self.assertIn(b'BlockingIOError', child.stderr)
        with nte.account_file_lock():
            pass

    def test_busy_start_does_not_read_or_refresh_accounts(self):
        with nte.account_file_lock(), patch.object(nte, 'init_token') as initialize:
            self.assertFalse(nte.start())
            initialize.assert_not_called()


if __name__ == '__main__':
    unittest.main()
