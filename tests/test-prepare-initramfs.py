#!/usr/bin/env python3
"""Check preparation without redistributing firmware or requiring root."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/prepare-initramfs.py'
spec = importlib.util.spec_from_file_location('prepare_initramfs', SCRIPT)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


@unittest.skipUnless(shutil.which('cpio') and shutil.which('find'), 'requires cpio and find')
class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zve10-prepare-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.patch = mock.patch.object(prepare, 'WORK', self.work)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_pack_has_files_symlinks_and_empty_directories(self):
        tree = self.work / 'tree'
        tree.mkdir()
        (tree / 'file with spaces').write_bytes(b'original pixels\0\xff')
        (tree / 'empty').mkdir()
        (tree / 'link').symlink_to('file with spaces')
        archive = self.work / 'camera.cpio'
        self.assertGreater(prepare.pack(tree, archive), 512)
        destination = self.work / 'unpacked'
        destination.mkdir()
        with archive.open('rb') as data:
            subprocess.run(['cpio', '-id', '--quiet', '--no-absolute-filenames'],
                           cwd=destination, stdin=data, check=True)
        self.assertEqual((destination / 'file with spaces').read_bytes(), b'original pixels\0\xff')
        self.assertEqual((destination / 'link').readlink(), Path('file with spaces'))
        self.assertTrue((destination / 'empty').is_dir())

    def test_failed_pack_keeps_previous_archive(self):
        tree = self.work / 'tree'
        tree.mkdir()
        archive = self.work / 'camera.cpio'
        archive.write_bytes(b'previous working archive')
        with mock.patch.object(prepare.subprocess, 'check_output', return_value=b'.\0'), \
             mock.patch.object(prepare.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'cpio')):
            with self.assertRaises(subprocess.CalledProcessError):
                prepare.pack(tree, archive)
        self.assertEqual(archive.read_bytes(), b'previous working archive')
        self.assertFalse(archive.with_suffix('.cpio.part').exists())

    def test_ui_assembly_keeps_guest_paths_and_removes_preload(self):
        for name in ('rootfs/etc', 'rootfs/usr/lib', 'usr/lib', 'usr/kmod', 'setting', 'tmp/images', 'boot/sabin'):
            (self.work / name).mkdir(parents=True, exist_ok=True)
        (self.work / 'rootfs/etc/ld.so.preload').write_text('/old/probe.so')
        (self.work / 'usr/lib/original.so').write_bytes(b'firmware library')
        (self.work / 'tmp/images/font.ltt').write_bytes(b'firmware font')
        (self.work / 'setting/Backup.bin').write_bytes(b'original settings')
        (self.work / 'boot/av-cam.bin').write_bytes(b'firmware blob')
        (self.work / 'boot/initrd.img').write_bytes(b'boot-only')
        (self.work / 'boot/vmlinux.bin').write_bytes(b'boot-only')
        (self.work / 'boot/sabin/data.bin').write_bytes(b'original data')
        module = self.work / 'modules/dma330-stub/dma330_stub.ko'
        module.parent.mkdir(parents=True)
        module.write_bytes(b'compiled module')
        init = self.work / 'init-script'
        init.write_text('#!/bin/sh\n')
        with mock.patch.object(prepare, 'create_device_nodes') as nodes:
            tree = prepare.build_ui(init)
        nodes.assert_called_once_with(tree)
        self.assertFalse((tree / 'etc/ld.so.preload').exists())
        self.assertEqual((tree / 'usr/lib/original.so').read_bytes(), b'firmware library')
        self.assertEqual((tree / 'tmp/images/font.ltt').read_bytes(), b'firmware font')
        self.assertEqual((tree / 'setting/Backup.bak').read_bytes(), b'original settings')
        self.assertEqual((tree / 'system/sabin/data.bin').read_bytes(), b'original data')
        self.assertFalse((tree / 'system/initrd.img').exists())
        self.assertFalse((tree / 'system/vmlinux.bin').exists())
        self.assertTrue((tree / 'init').stat().st_mode & 0o111)
        self.assertEqual((tree / 'usr/kmod/dma330_stub.ko').read_bytes(), b'compiled module')

    def test_existing_prepared_tree_is_not_erased(self):
        for name in ('rootfs', 'usr', 'boot', 'setting', 'tmp', 'initramfs-ui'):
            (self.work / name).mkdir()
        (self.work / 'setting/Backup.bin').write_bytes(b'settings')
        saved = self.work / 'initramfs-ui/user-file'
        saved.write_bytes(b'keep me')
        with mock.patch.object(sys, 'argv', ['prepare-initramfs.py']), self.assertRaisesRegex(SystemExit, 'already exists'):
            prepare.main()
        self.assertEqual(saved.read_bytes(), b'keep me')

    @unittest.skipUnless(shutil.which('fakeroot'), 'requires fakeroot')
    def test_saved_fakeroot_preserves_device_nodes_when_repacking(self):
        tree = self.work / 'tree'
        tree.mkdir()
        state = self.work / 'fakeroot.state'
        code = (
            'import importlib.util,sys; from pathlib import Path; '
            's=importlib.util.spec_from_file_location("prep",sys.argv[1]); '
            'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
            'm.create_device_nodes(Path(sys.argv[2]))'
        )
        subprocess.run(['fakeroot', '-s', str(state), sys.executable, '-c', code,
                        str(SCRIPT), str(tree)], check=True)
        # Start a separate fakeroot process, as the UI launcher does after preparation.
        listing = subprocess.check_output(['find', '.', '-print0'], cwd=tree)
        archive = self.work / 'ui.cpio'
        with archive.open('wb') as out:
            subprocess.run(['fakeroot', '-i', str(state), '--', 'cpio', '--null', '-o',
                            '-H', 'newc', '--quiet', '--owner=0:0'],
                           cwd=tree, input=listing, stdout=out, check=True)
        with archive.open('rb') as data:
            entries = subprocess.check_output(['cpio', '-itv', '--quiet'], stdin=data).decode()
        for name in ('console', 'null', 'kmsg', 'ttyAM0', 'ttyAMA0'):
            line = next(line for line in entries.splitlines() if line.endswith(f'dev/{name}'))
            self.assertTrue(line.startswith('c'), line)
        self.assertIn('5,', next(line for line in entries.splitlines() if line.endswith('dev/console')))


if __name__ == '__main__':
    unittest.main()
