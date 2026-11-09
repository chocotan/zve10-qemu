#!/usr/bin/env python3
import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from menu_title import append_title
from original_assets import string, lookup


class TitleBankTests(unittest.TestCase):
    def source(self):
        # Independent resource parser below also consumes this synthetic old bank.
        return (b'uxc\x07' + bytes(4) + bytes([8, 0, 0x27, 0]) +
                struct.pack('<I', (1 << 13) | 2) + struct.pack('<HH', 0, 2) +
                struct.pack('<I', 0x1e04e000) + b'One\0' +
                struct.pack('<I', 0x1e04e001) + b'Two\0')

    def test_old_records_unchanged_and_new_title_parses(self):
        old = self.source()
        new = append_title(old, 0x0204e002, 'New Menu')
        self.assertEqual(string(new, 0x0204e002), 'New Menu')
        for resource in (0x0204e000, 0x0204e001):
            self.assertEqual(string(new, resource), string(old, resource))
            a, b = lookup(old, 8, resource & 0x1fff), lookup(new, 8, resource & 0x1fff)
            self.assertEqual(old[a:a+8], new[b:b+8])
        self.assertEqual(string(old, 0x0204e000), 'One')

    def test_overwrite_and_foreign_namespace_are_refused(self):
        for resource in (0x0204e001, 0x02050002):
            with self.assertRaises(ValueError): append_title(self.source(), resource, 'X')

    def test_unknown_layout_and_invalid_title_are_refused(self):
        for data in (b'', self.source()[:12], b'bad!' + self.source()[4:]):
            with self.assertRaises(ValueError): append_title(data, 0x0204e002, 'X')
        for text in ('', 'a\0b', 'x' * 257):
            with self.assertRaises(ValueError): append_title(self.source(), 0x0204e002, text)


if __name__ == '__main__':
    unittest.main()
