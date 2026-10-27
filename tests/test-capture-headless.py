#!/usr/bin/env python3
"""Check immutable native-frame export boundaries without booting or inventing captures."""
import copy
import importlib.util
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[1] / 'scripts/capture-menu.py'
spec = importlib.util.spec_from_file_location('capture_headless', source)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.pages = []
        offset, physical = 0, 0x10000010
        while offset < capture.SPAN:
            length = min(4096 - (physical & 4095), capture.SPAN - offset)
            self.pages.append(dict(frame=1, index=len(self.pages), physical=physical,
                                   capture_offset=offset, length=length))
            offset += length
            physical += length
        self.meta = dict(frame=1, source_physical=0x22bb2000, width=640, height=480,
                         format=1, bpp=2, stride=1280, byte_length=capture.SPAN,
                         segments=len(self.pages),fingerprint_fnv1a64='0123456789abcdef')
        self.ready = dict(frame=1, segments=len(self.pages))

    def test_normal_ram_pages_and_exact_span(self):
        result = capture.validate_segments(self.meta, list(reversed(self.pages)), self.ready)
        self.assertEqual(result, self.pages)
        self.assertEqual(sum(p['length'] for p in result), capture.SPAN)
        self.assertEqual(len(result), 151)

    def test_reject_malformed_publication(self):
        for mutation in ('missing', 'duplicate', 'offset', 'cross_page', 'outside_ram',
                         'layout', 'wrong_frame', 'boolean_completion', 'boolean_address', 'checksum'):
            with self.subTest(mutation=mutation):
                meta, pages, ready = copy.deepcopy((self.meta, self.pages, self.ready))
                if mutation == 'missing': pages.pop()
                elif mutation == 'duplicate': pages[1]['index'] = 0
                elif mutation == 'offset': pages[1]['capture_offset'] += 1
                elif mutation == 'cross_page': pages[0]['physical'] = 0x10000fff
                elif mutation == 'outside_ram': pages[-1]['physical'] = 0x40000000
                elif mutation == 'layout': meta['stride'] += 1
                elif mutation == 'wrong_frame': ready['frame'] += 1
                elif mutation == 'boolean_completion': ready['frame'] = True
                elif mutation == 'boolean_address': meta['source_physical'] = True
                elif mutation == 'checksum': meta['fingerprint_fnv1a64'] = 'not-a-checksum'
                with self.assertRaises(ValueError):
                    capture.validate_segments(meta, pages, ready)

    def test_native_fingerprint_vectors(self):
        for value, expected in ((b'', 'cbf29ce484222325'), (b'a', 'af63dc4c8601ec8c'),
                                (b'foobar', '85944171f73967e8')):
            self.assertEqual(capture.fingerprint(value), expected)

    def test_rgba_and_alpha_are_preserved(self):
        raw = bytearray(capture.SPAN)
        raw[:2] = bytes.fromhex('0ff0')
        raw[-2:] = bytes.fromhex('3412')
        image = capture.decode_image(raw)
        self.assertEqual(image.mode, 'RGBA')
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(image.getpixel((1, 0)), (0, 0, 0, 0))
        self.assertEqual(image.getpixel((639, 479)), (17, 34, 51, 68))

    def test_no_uniform_or_truncated_frame(self):
        for raw in (bytes(capture.SPAN), bytes(capture.SPAN - 1)):
            with self.assertRaises(ValueError): capture.decode_image(raw)


if __name__ == '__main__':
    unittest.main()
