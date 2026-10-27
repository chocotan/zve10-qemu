#!/usr/bin/env python3
"""Exercise firmware-preparation boundaries using small local fixtures."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/prepare-firmware.py'
spec = importlib.util.spec_from_file_location('prepare_firmware', SCRIPT)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class FirmwarePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zve10-firmware-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_wrong_update_is_rejected_before_extraction(self):
        package = self.root / 'wrong.dmg'
        package.write_bytes(b'a different firmware')
        with mock.patch.object(prepare, 'run') as run, self.assertRaisesRegex(SystemExit, 'expected 2.03'):
            prepare.extract_dmg(package, self.root / 'update')
        run.assert_not_called()

    def test_extraction_checks_inner_dat(self):
        package = self.root / 'update.dmg'
        package.write_bytes(b'fixture update')
        destination = self.root / 'update'
        destination.mkdir()
        dat = destination / 'FirmwareData_ZVE10V203.dat'
        dat.write_bytes(b'fixture DAT')
        with mock.patch.object(prepare, 'DMG_SHA256', hashlib.sha256(package.read_bytes()).hexdigest()), \
             mock.patch.object(prepare, 'FIRMWARE_DAT_SHA256', hashlib.sha256(dat.read_bytes()).hexdigest()), \
             mock.patch.object(prepare, 'run') as run:
            self.assertEqual(prepare.extract_dmg(package, destination), dat)
            dat.write_bytes(b'truncated DAT')
            with self.assertRaisesRegex(SystemExit, 'expected firmware image'):
                prepare.extract_dmg(package, destination)
            self.assertEqual(run.call_count, 2)

    def test_unpack_returns_parent_of_partition_directory(self):
        tool = self.root / 'fwtool.py'
        tool.write_text('# fixture\n')
        output = self.root / 'unpacked'
        firmware_root = output / 'firmware.tar_unpacked'
        (firmware_root / '0700_part_image').mkdir(parents=True)
        with mock.patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             mock.patch.object(prepare, 'run'):
            self.assertEqual(prepare.unpack_firmware('input.dat', tool, 'python3', output), firmware_root)

    def test_debugfs_failure_is_reported(self):
        image = self.root / 'partition'
        image.write_bytes(b'fixture')
        failed = subprocess.CompletedProcess([], 1, '', 'invalid filesystem')
        with mock.patch.object(prepare.subprocess, 'run', return_value=failed), \
             self.assertRaisesRegex(SystemExit, 'invalid filesystem'):
            prepare.extract_partition(image, 'ext2', self.root / 'rootfs')

    def test_missing_dependency_explains_interpreter_choice(self):
        tool = self.root / 'fwtool.py'
        tool.write_text('# fixture\n')
        with mock.patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)), \
             self.assertRaisesRegex(SystemExit, 'fwtool-python'):
            prepare.unpack_firmware('input.dat', tool, 'python3', self.root / 'output')


if __name__ == '__main__':
    unittest.main()
