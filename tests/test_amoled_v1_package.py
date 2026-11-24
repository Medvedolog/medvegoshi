"""Host-only checks for the experimental AMOLED source archive."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from ports import package_amoled_v1_app as bundle


class PackageAppTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.source = self.root / 'checkout'
        self.output = self.root / 'medvegoshi-v1-app-UNTESTED.zip'
        for origin, _ in bundle.APP_FILES:
            self.write(origin, ('sample checkout: ' + origin + '\n').encode('utf-8'))

    def write(self, name, data):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_exact_allowlist_and_checksums(self):
        for name in (
            'boot.py', 'config.json', 'wifi.json', 'pet_saves/pip.json',
            'firmware.bin', 'sons/piu.raw', 'install.sh', '.git/config',
            'zoo/animals/pip/secrets.txt', 'companion/testes/test_fake.py',
            'ports/pip_native/mod_pip_native.c', 'ports/amoled_v1_smoke.py',
            'zoo/pip/host_save.py', 'zoo/animals/new/manifest.json',
            'zoo/animals/bjorni/source.png', 'zoo/animals/bjorni/extra.json',
            'zoo/animals/ryska/reference.png', 'zoo/animals/ryska/extra.json',
        ):
            self.write(name, b'not for the artifact')
        actual_hash = bundle.package_app(self.source, self.output)
        self.assertEqual(actual_hash, hashlib.sha256(self.output.read_bytes()).hexdigest())
        with zipfile.ZipFile(self.output) as archive:
            names = archive.namelist()
            self.assertEqual(sorted(names), names)
            expected = {name for _, name in bundle.APP_FILES}
            self.assertEqual(set(names), expected | {'SHA256SUMS', 'UNTESTED.txt'})
            self.assertEqual(archive.testzip(), None)
            self.assertIn('UNTESTED ON HARDWARE', archive.read('UNTESTED.txt').decode())
            self.assertNotIn('main.py', names)
            self.assertNotIn('boot.py', names)
            self.assertIn('v1_game_app.py', names)
            self.assertIn('raiox.html', names)
            self.assertIn('LICENSE-Pip-KeyPet.txt', names)
            self.assertEqual({
                'zoo/animals/bjorni/__init__.py', 'zoo/animals/bjorni/face.py',
                'zoo/animals/bjorni/manifest.json',
            }, {name for name in names if name.startswith('zoo/animals/bjorni/')})
            self.assertEqual({
                'zoo/animals/ryska/__init__.py', 'zoo/animals/ryska/face.py',
                'zoo/animals/ryska/manifest.json',
            }, {name for name in names if name.startswith('zoo/animals/ryska/')})
            self.assertNotIn('companion/raiox.html', names)
            for origin, name in bundle.APP_FILES:
                self.assertEqual(archive.read(name), (self.source / origin).read_bytes())
            checksums = archive.read('SHA256SUMS').decode().splitlines()
            self.assertEqual(checksums, [
                hashlib.sha256(archive.read(name)).hexdigest() + '  ' + name
                for name in names if name != 'SHA256SUMS'
            ])

    def test_reproducible_ignoring_timestamps_permissions_and_destination(self):
        expected = bundle.package_app(self.source, self.output)
        os.utime(self.source / 'main.py', (1600000000, 1700000000))
        (self.source / 'main.py').chmod(0o700)
        copy = self.root / 'different-name.zip'
        self.assertEqual(bundle.package_app(self.source, copy), expected)
        self.assertEqual(copy.read_bytes(), self.output.read_bytes())
        with zipfile.ZipFile(copy) as archive:
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.external_attr >> 16, 0o100644)
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

    def test_rejects_existing_output(self):
        self.output.write_bytes(b'leave this alone')
        with self.assertRaises(FileExistsError):
            bundle.package_app(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'leave this alone')

    def test_rejects_wrong_suffix(self):
        bad = self.root / 'main.py'
        with self.assertRaisesRegex(bundle.PackageError, 'zip suffix'):
            bundle.package_app(self.source, bad)
        self.assertFalse(bad.exists())

    def test_missing_source_fails_without_output(self):
        (self.source / 'ports/amoled_v1_launch.py').unlink()
        with self.assertRaisesRegex(bundle.PackageError, 'missing required.*amoled_v1_launch'):
            bundle.package_app(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_oversized_source_fails_without_output(self):
        self.write('main.py', b'x' * (bundle.MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(bundle.PackageError, 'per-file size limit'):
            bundle.package_app(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_oversized_payload_fails_without_output(self):
        with patch.object(bundle, 'MAX_PAYLOAD_BYTES', 45):
            with self.assertRaisesRegex(bundle.PackageError, 'total size limit'):
                bundle.package_app(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_nontext_and_embedded_control_bytes_fail(self):
        for data in (b'\x00', b'\xff'):
            with self.subTest(data=data):
                self.write('main.py', data)
                with self.assertRaises(bundle.PackageError):
                    bundle.package_app(self.source, self.output)
                self.assertFalse(self.output.exists())

    def test_symlink_leaves_directories_and_existing_output_are_refused(self):
        outside = self.root / 'outside.py'
        outside.write_text('do not read', encoding='utf-8')
        origin = self.source / 'main.py'
        origin.unlink()
        try:
            origin.symlink_to(outside)
        except (NotImplementedError, OSError):
            self.skipTest('host does not permit symbolic links')
        with self.assertRaisesRegex(bundle.PackageError, 'regular file'):
            bundle.package_app(self.source, self.output)
        origin.unlink()
        origin.write_text('safe again', encoding='utf-8')
        actual = self.source / 'ports'
        moved = self.root / 'other-ports'
        actual.rename(moved)
        actual.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(bundle.PackageError, 'real directory'):
            bundle.package_app(self.source, self.output)
        self.assertFalse(self.output.exists())
        missing = self.root / 'no_file_here'
        self.output.symlink_to(missing)
        with self.assertRaises(FileExistsError):
            bundle.package_app(self.source, self.output)
        self.assertFalse(missing.exists())

    def test_unsafe_paths_fail_even_if_accidentally_allowlisted(self):
        for source, name in (
            ('../main.py', 'v1_game_app.py'), ('main.py', '/outside.py'),
            ('main.py', 'C:/outside.py'), ('main.py', 'zoo\\outside.py'),
            ('main.py', 'zoo//outside.py'), ('main.py', 'BOOT.py'),
            ('main.py', 'main.py'), ('main.py', 'config.json'),
            ('firmware.bin', 'firmware.py'),
        ):
            with self.subTest(source=source, name=name), patch.object(bundle, 'APP_FILES', ((source, name),)):
                with self.assertRaises(bundle.PackageError):
                    bundle.package_app(self.source, self.output)
                self.assertFalse(self.output.exists())

    def test_case_insensitive_duplicate_is_rejected(self):
        paths = (('main.py', 'v1_game_app.py'), ('main.py', 'V1_GAME_APP.py'))
        with patch.object(bundle, 'APP_FILES', paths):
            with self.assertRaisesRegex(bundle.PackageError, 'duplicate'):
                bundle.package_app(self.source, self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
