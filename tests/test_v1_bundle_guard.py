"""Exact source ZIP, firmware identity, and rejection before V1 I/O."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from ports import amoled_v1_launch as launcher, amoled_v1_runtime as runtime
from ports import package_amoled_v1_app as pack, v1_bundle_guard as guard
from ports.verify_amoled_v1_bundle import verify_archive


def sha(data):
    return hashlib.sha256(data).hexdigest()


class BundleGuardTest(unittest.TestCase):
    def test_pack_real_application_and_verify_every_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.zip'
            pack.package_app(Path(__file__).resolve().parents[1], path)
            with zipfile.ZipFile(path) as z:
                self.assertEqual(sha(z.read(guard.INDEX)), verify_archive(path))
                changed = {name: z.read(name) for name in z.namelist()}
            changed['v1_game_app.py'] += b'\n# different checkout\n'
            path.unlink()
            path.write_bytes(pack._archive(changed))
            with self.assertRaisesRegex(guard.BundleMismatch, 'differs'):
                verify_archive(path)
            changed.pop('v1_game_app.py')
            path.write_bytes(pack._archive(changed))
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                verify_archive(path)

    def test_actual_launcher_refuses_mismatch_before_hardware_and_save(self):
        app = b'pass\n'
        index = (sha(app) + '  v1_game_app.py\n').encode()
        files = {guard.INDEX: index, 'v1_game_app.py': app}
        def open_file(path, mode):
            if path not in files:
                raise FileNotFoundError(path)
            if mode != 'rb':
                self.fail('only read-only V1 preflight permitted')
            return io.BytesIO(files[path])

        method = lambda *args: None
        pip = SimpleNamespace(ABI_VERSION=1, APP_INDEX_SHA256=sha(index),
                              **{name: method for name in guard.REQUIRED_PIP})
        display = type('AMOLED', (), dict.fromkeys(
            ('reset', 'init', 'brightness', 'fill', 'refresh'), method))
        panel = type('QSPIPanel', (), dict.fromkeys(('tx_param', 'tx_color'), method))
        with patch.dict(sys.modules, {'pip_native': pip,
                                      'amoled': SimpleNamespace(AMOLED=display, QSPIPanel=panel)}):
            with patch.object(guard, 'verify_files', wraps=lambda digest:
                              verify_impl(digest, open_file)):
                with patch('os.stat'), patch.object(runtime, 'create_profile') as create:
                    for key, replacement, reason in (
                        ('APP_INDEX_SHA256', '0' * 64, 'index does not match'),
                        ('ABI_VERSION', 2, 'Pip native API'),
                        ('reset', None, 'Pip native API'),
                    ):
                        with patch.object(pip, key, replacement), self.assertRaisesRegex(
                                guard.BundleMismatch, reason):
                            launcher.run(enabled=True, confirmed_v1=True)
                    files['v1_game_app.py'] = b'changed'
                    with self.assertRaisesRegex(guard.BundleMismatch, 'differs'):
                        launcher.run(enabled=True, confirmed_v1=True)
                    del files['v1_game_app.py']
                    with self.assertRaisesRegex(guard.BundleMismatch, 'missing'):
                        launcher.run(enabled=True, confirmed_v1=True)
                    create.assert_not_called()

    def test_cleanup_on_normal_return_and_original_interrupt(self):
        use = SimpleNamespace()
        for error in (None, KeyboardInterrupt()):
            with self.subTest(error=error), patch('os.stat'), patch(
                    'ports.v1_bundle_guard.verify_runtime'), patch.object(
                    runtime, 'create_profile', return_value=use), patch.object(
                    launcher, '_launch', side_effect=error, return_value='returned'), patch.object(
                    use, 'close', create=True) as close:
                if error is None:
                    self.assertEqual(launcher.run(enabled=True, confirmed_v1=True), 'returned')
                else:
                    close.side_effect = OSError('cleanup')
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        launcher.run(enabled=True, confirmed_v1=True)
                    self.assertIs(caught.exception, error)
                close.assert_called_once_with()

    def test_pinned_index_still_rejects_unsafe_or_duplicate_paths(self):
        for path in ('../secret.py', 'BOOT.py', 'x//y', '/file', 'x\\file'):
            index = (sha(b'x') + '  ' + path + '\n').encode()
            with self.subTest(path=path), self.assertRaisesRegex(
                    guard.BundleMismatch, 'Invalid path'):
                guard.verify_files(sha(index), lambda *_: io.BytesIO(index))
        line = sha(b'x') + '  v1_game_app.py\n'
        index = (line + line.upper().replace(sha(b'x').upper(), sha(b'x'))).encode()
        with self.assertRaisesRegex(guard.BundleMismatch, 'Invalid path'):
            guard.verify_files(sha(index), lambda path, _: io.BytesIO(
                index if path == guard.INDEX else b'x'))


verify_impl = guard.verify_files
