#!/usr/bin/env python3
"""Guard checks for the A7C2 resource importer.

The real bundle is a local, unpublished handoff artifact: point A7C2_RESOURCE_ZIP
at it to run that case. Everything else uses synthetic ZIPs and temp directories.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('menu_resources', ROOT / 'scripts/menu_resources.py')
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)
PREFIX = resources.ARCHIVE_PREFIX
ZIP_ENV = 'A7C2_RESOURCE_ZIP'


def build(path, members):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        with zipfile.ZipFile(path, 'w') as archive:
            for member in members:
                if isinstance(member, zipfile.ZipInfo):
                    archive.writestr(member, b'x' * member.file_size)
                else:
                    archive.writestr(*member)


def zero_archive(path, sizes):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, size in sizes.items():
            info = zipfile.ZipInfo(PREFIX + name)
            with archive.open(info, 'w') as member:
                for _ in range(size // (1 << 20)):
                    member.write(bytes(1 << 20))
                member.write(bytes(size % (1 << 20)))


def symlink_member(path, name):
    info = zipfile.ZipInfo(PREFIX + name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    info.file_size = 0
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(info, b'')


def encrypted(path):
    data = bytearray(path.read_bytes())
    for signature, offset in ((b'PK\x03\x04', 6), (b'PK\x01\x02', 8)):
        start = data.index(signature)
        data[start + offset] |= 1
    path.write_bytes(data)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zve10-resources-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'bundle.zip'
        self.destination = self.root / 'out'

    def reject(self, message):
        with self.assertRaises(ValueError) as caught:
            resources.prepare_resources(self.bundle, self.destination)
        self.assertIn(message, str(caught.exception))
        self.assertFalse(self.destination.exists())
        self.assertEqual([path.name for path in self.root.iterdir()], ['bundle.zip'])

    def test_unsafe_member_names(self):
        for name in ('a7c2-root/../escape', 'a7c2-root\\usr\\lib\\appFw.so', '/etc/passwd',
                     'C:/windows', 'a7c2-root/usr/lib/app\x01Fw.so', './sony-lz77.c',
                     'a7c2-root//sony-lz77.c'):
            with self.subTest(name=name):
                build(self.bundle, [(PREFIX + name, b'x')])
                self.reject('Unsafe archive member')

    def test_members_outside_whitelist(self):
        for name in ('a7c2-root/usr/lib/extra.so', 'notes.txt', 'a7c2-root',
                     'other-root/sony-lz77.c'):
            with self.subTest(name=name):
                build(self.bundle, [(PREFIX + name, b'x')])
                self.reject('outside the whitelist')

    def test_pinned_size_and_duplicates(self):
        build(self.bundle, [(PREFIX + 'sony-lz77.h', b'x' * 232)])
        self.reject('size differs')
        build(self.bundle, [(PREFIX + 'sony-lz77.h', b'x' * 231)] * 2)
        self.reject('Duplicate archive member')
        build(self.bundle, [(PREFIX + 'README.md', b'x')] * 33)
        self.reject('Too many archive entries')

    def test_missing_members(self):
        build(self.bundle, [(PREFIX + 'sony-lz77.h', b'x' * 231)])
        self.reject('Missing archive members')

    def test_symlink_and_encrypted_members(self):
        symlink_member(self.bundle, 'sony-lz77.h')
        self.reject('Not a regular archive member')
        build(self.bundle, [(PREFIX + 'sony-lz77.h', b'x' * 231)])
        encrypted(self.bundle)
        self.reject('Encrypted archive member')

    def test_wrong_content_rejected_and_staging_removed(self):
        sizes = {'a7c2-root/' + name: size for name, (size, _) in resources.RESOURCES.items()}
        sizes.update({name: size for name, (size, _) in resources.DECODERS.items()})
        zero_archive(self.bundle, sizes)
        self.reject('Unverified archive member')

    def test_existing_destination_is_untouched(self):
        self.destination.mkdir()
        sentinel = self.destination / 'keep.txt'
        sentinel.write_text('untouched')
        with self.assertRaises(ValueError) as caught:
            resources.prepare_resources(self.root / 'absent.zip', self.destination)
        self.assertIn('Destination must not exist', str(caught.exception))
        self.assertEqual(sentinel.read_text(), 'untouched')
        self.assertEqual(sorted(path.name for path in self.destination.iterdir()), ['keep.txt'])
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['out'])

    def test_validate_root_rejects_symlinks_and_hashes(self):
        tree = self.root / 'a7c2-root'
        for name, (size, _) in resources.RESOURCES.items():
            path = tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('wb') as handle:
                handle.truncate(size)
        for name, (size, _) in resources.DECODERS.items():
            (self.root / name).write_bytes(bytes(size))
        with self.assertRaises(ValueError) as caught:
            resources.validate_root(tree)
        self.assertIn('Unverified pinned file', str(caught.exception))
        (tree / 'extra').symlink_to(next(iter(resources.RESOURCES)))
        with self.assertRaises(ValueError):
            resources.validate_root(tree)


@unittest.skipUnless(os.environ.get(ZIP_ENV), f'set {ZIP_ENV} to the pinned resource ZIP')
class RealBundleTests(unittest.TestCase):
    def test_import_is_exact_and_never_overwrites(self):
        bundle = Path(os.environ[ZIP_ENV])
        with tempfile.TemporaryDirectory(prefix='zve10-resources-real-') as temp:
            destination = Path(temp) / 'out'
            root = resources.prepare_resources(bundle, destination)
            self.assertEqual(root, destination / 'a7c2-root')
            resources.validate_root(root)
            for name, (size, digest) in resources.RESOURCES.items():
                path = root / name
                self.assertEqual(path.stat().st_size, size, name)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, name)
            for name in resources.DECODERS:
                self.assertTrue((destination / name).is_file(), name)
            self.assertTrue((destination / 'README.md').is_file())
            with self.assertRaises(ValueError):
                resources.prepare_resources(bundle, destination)
            resources.validate_root(root)


if __name__ == '__main__':
    unittest.main()
