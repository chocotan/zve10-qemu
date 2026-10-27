#!/usr/bin/env python3
"""Export one privately retained native AP frame; menu content requires visual verification."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import tempfile
import time
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'output'
SPAN = 640 * 480 * 2


def validate_segments(meta, pages, ready):
    expected = {'width': 640, 'height': 480, 'format': 1, 'bpp': 2,
                'stride': 1280, 'byte_length': SPAN}
    if not all(type(meta.get(k)) is int and meta[k] == v for k, v in expected.items()):
        raise ValueError('Unsupported native capture layout')
    fingerprint = meta.get('fingerprint_fnv1a64')
    if (not isinstance(fingerprint, str) or len(fingerprint) != 16 or
            any(c not in '0123456789abcdef' for c in fingerprint)):
        raise ValueError('Missing native frame fingerprint')
    frame, count = meta.get('frame'), meta.get('segments')
    physical = meta.get('source_physical')
    if (type(frame) is not int or frame <= 0 or type(count) is not int or not 1 <= count <= 151 or
            type(physical) is not int or not 0x20000000 <= physical <= 0x28000000 - SPAN or
            type(ready.get('frame')) is not int or type(ready.get('segments')) is not int or
            ready.get('frame') != frame or ready.get('segments') != count or len(pages) != count):
        raise ValueError('Incomplete native capture publication')
    if any(type(p.get(k)) is not int for p in pages
           for k in ('frame', 'index', 'physical', 'capture_offset', 'length')):
        raise ValueError('Noninteger capture segment')
    ordered = sorted(pages, key=lambda p: p['index'])
    offset = 0
    for index, page in enumerate(ordered):
        physical, length = page['physical'], page['length']
        if (page['frame'] != frame or page['index'] != index or page['capture_offset'] != offset or
                not 0 < length <= 4096 or not 0 <= physical <= 0x40000000 - length or
                (physical & 4095) + length > 4096 or offset + length > SPAN):
            raise ValueError('Invalid, duplicated, or noncontiguous capture segment')
        offset += length
    if offset != SPAN:
        raise ValueError('Truncated capture')
    return ordered


def fingerprint(raw):
    value = 0xcbf29ce484222325
    for byte in raw:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return f'{value:016x}'


def decode_image(raw):
    if len(raw) != SPAN:
        raise ValueError('Truncated RGBA4444 frame')
    if raw == raw[:2] * (SPAN // 2):
        raise ValueError('Published nonuniform frame is uniform')
    rgba = bytearray(SPAN * 2)
    for offset in range(0, SPAN, 2):
        word = raw[offset] | raw[offset + 1] << 8
        rgba[offset * 2:offset * 2 + 4] = bytes(((word >> 12) * 17,
            ((word >> 8) & 15) * 17, ((word >> 4) & 15) * 17, (word & 15) * 17))
    return Image.frombytes('RGBA', (640, 480), bytes(rgba))


def capture():
    OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='zve10-headless-') as tmp:
        endpoint = Path(tmp) / 'qmp'
        proc = subprocess.Popen([str(ROOT / 'start-zve10-ui.sh'), '-qmp',
            f'unix:{endpoint},server=on,wait=off'], cwd=ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True)
        selected = selectors.DefaultSelector()
        selected.register(proc.stdout, selectors.EVENT_READ)
        channel = None
        meta, pages, ready, pending = None, [], None, b''
        deadline = time.monotonic() + 120
        try:
            with (OUT / 'ui-headless-capture.log').open('wb') as log:
                while time.monotonic() < deadline and proc.poll() is None and ready is None:
                    for key, _ in selected.select(timeout=0.2):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            continue
                        log.write(chunk)
                        log.flush()
                        pending += chunk
                        if len(pending) > 1024 * 1024:
                            raise RuntimeError('Oversized unterminated guest log line')
                        while b'\n' in pending:
                            line, pending = pending.split(b'\n', 1)
                            if any(mark in line for mark in (b'headless.error.',b'GPE.present.UNSUPPORTED',
                                    b'GPE.clear.UNSUPPORTED',b'GEMINI.cpu.UNSUPPORTED',b'LDEC.cpu.UNSUPPORTED')):
                                raise RuntimeError(line.decode(errors='replace'))
                            for prefix in (b'UI_CAPTURE_META ', b'UI_CAPTURE_PAGE ', b'UI_CAPTURE_READY '):
                                if prefix not in line:
                                    continue
                                value = json.loads(line.split(prefix, 1)[1])
                                if prefix == b'UI_CAPTURE_META ':
                                    if meta is not None:
                                        raise ValueError('Duplicate capture identity')
                                    meta = value
                                elif prefix == b'UI_CAPTURE_PAGE ':
                                    if len(pages) >= 151:
                                        raise ValueError('Too many capture segments')
                                    pages.append(value)
                                else:
                                    ready = value
                                break
            if meta is None or ready is None:
                raise RuntimeError('No completed nonuniform native frame; retained ui-headless-capture.log')
            segments = validate_segments(meta, pages, ready)
            channel = socket.socket(socket.AF_UNIX)
            channel.settimeout(10)
            channel.connect(str(endpoint))
            stream = channel.makefile('rwb')
            if 'QMP' not in json.loads(stream.readline()):
                raise RuntimeError('Missing QMP greeting')

            def call(name, args=None):
                stream.write((json.dumps({'execute': name, 'arguments': args or {}}) + '\n').encode())
                stream.flush()
                while True:
                    line = stream.readline()
                    if not line:
                        raise RuntimeError('QMP closed before command completion')
                    reply = json.loads(line)
                    if 'error' in reply:
                        raise RuntimeError(reply['error'])
                    if 'return' in reply:
                        return reply['return']

            call('qmp_capabilities')
            call('stop')
            raw = bytearray()
            for index, segment in enumerate(segments):
                part = Path(tmp) / f'page-{index}.bin'
                call('pmemsave', {'val': segment['physical'], 'size': segment['length'], 'filename': str(part)})
                data = part.read_bytes()
                if len(data) != segment['length']:
                    raise RuntimeError('Incomplete physical snapshot read')
                raw.extend(data)
            if fingerprint(raw) != meta['fingerprint_fnv1a64']:
                raise RuntimeError('Native snapshot changed after publication; no image exported')
            image = decode_image(raw)
            raw_path = OUT / 'zve10-headless-native.bin'
            png_path = OUT / 'zve10-headless-native.png'
            raw_path.write_bytes(raw)
            image.save(png_path)
            pixel_sha=hashlib.sha256(raw).hexdigest()
            preview_path=OUT / f'zve10-menu-frame{meta["frame"]}-{pixel_sha[:8]}.png'
            preview=Image.new('RGBA',image.size,(0,0,0,255))
            preview.alpha_composite(image)
            preview.convert('RGB').save(preview_path)
            result = dict(meta, segments=segments, committed_native_frame=True,
                committed_menu_frame=False, capture='QMP stop; immutable pinned private snapshot after native completion',
                raw_file=str(raw_path), png=str(png_path), preview_png=str(preview_path), raw_sha256=pixel_sha,
                visible_pixels=sum(bool(value & 15) for value in raw[::2]),
                nonzero_bytes=sum(value != 0 for value in raw))
            (OUT / 'zve10-headless-native.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2))
            call('quit')
            proc.wait(timeout=5)
        finally:
            selected.close()
            if channel:
                channel.close()
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()


if __name__ == '__main__':
    capture()
