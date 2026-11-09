#!/usr/bin/env python3
"""Run the original ZV-E10 menu, with an explicitly optional A7C2 resource menu."""
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from PIL import Image

from menu_build import build, ROOT, digest
import menu_host as host


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(spec.loader.get_source(name), str(path), 'exec'), module.__dict__)
    return module


class NativeGuest:
    def __init__(self, channel, qmp, out, validator):
        self.channel, self.qmp, self.out, self.validator = channel, qmp, out, validator
        channel.settimeout(70)
        self.stream = channel.makefile('rwb')
        self.log = (out / 'serial.log').open('wb')
        self.frames, self.events = [], []
        self.capture_id, self.input_id = 0, 0
        self.pending = False
        self.timeout = 70
        self.on_frame = None

    def send(self, text):
        self.stream.write((text + '\n').encode('ascii'))
        self.stream.flush()

    def line(self, deadline=None):
        deadline = deadline or time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError('Native serial phase deadline')
            self.channel.settimeout(remaining)
            line = self.stream.readline(1024 * 1024 + 1)
            if not line or len(line) > 1024 * 1024:
                raise RuntimeError('Native guest serial ended or exceeded line bound')
            self.log.write(line); self.log.flush()
            if any(marker in line for marker in (b'DMP.fill.UNSUPPORTED=', b'DMP.blit.UNSUPPORTED=', b'GEMINI.cpu.UNSUPPORTED=')):
                raise RuntimeError('Original CPU renderer rejected a draw: ' + line.decode(errors='replace').strip())
            for prefix in (b'NE_', b'UI_CAPTURE_'):
                at = line.find(prefix)
                if at >= 0:
                    item = line[at:].strip(b'\r\n')
                    if item.startswith(b'NE_ERROR'):
                        raise RuntimeError(item.decode(errors='replace'))
                    if item.startswith(b'NE_INPUT_CONSUMED '):
                        self.events.append(json.loads(item.split(b' ', 1)[1]))
                    return item

    def until(self, prefix):
        deadline = time.monotonic() + self.timeout
        while True:
            line = self.line(deadline)
            if line.startswith(prefix):
                return line

    def ready(self):
        value = json.loads(self.until(b'NE_READY ').split(b' ', 1)[1])
        self.timeout = 12
        return value

    def capture(self):
        self.capture_id += 1
        ticket = self.capture_id
        self.send(f'CAPTURE {ticket}')
        state, meta, pages, ready = None, None, [], None
        deadline = time.monotonic() + self.timeout
        while ready is None:
            line = self.line(deadline)
            if line.startswith(b'NE_STATE '):
                if state is not None: raise RuntimeError('Repeated native state record')
                state = json.loads(line.split(b' ', 1)[1])
            elif line.startswith(b'UI_CAPTURE_META '):
                if meta is not None: raise RuntimeError('Repeated native capture identity')
                meta = json.loads(line.split(b' ', 1)[1])
            elif line.startswith(b'UI_CAPTURE_PAGE '):
                if len(pages) >= 151: raise RuntimeError('Oversized native capture')
                pages.append(json.loads(line.split(b' ', 1)[1]))
            elif line.startswith(b'UI_CAPTURE_READY '):
                ready = json.loads(line.split(b' ', 1)[1])
        if not state or not meta or any(x.get('capture_id') != ticket for x in (state, meta, ready)):
            raise RuntimeError('Native capture ticket mismatch')
        segments = self.validator.validate_segments(meta, pages, ready)
        self.pending = True
        raw = bytearray()
        self.qmp.call('stop')
        try:
            if self.qmp.call('query-status')['status'] != 'paused':
                raise RuntimeError('Native QEMU did not pause')
            for index, segment in enumerate(segments):
                part = self.out / f'capture-{ticket:03d}-page-{index:03d}.bin'
                self.qmp.call('pmemsave', {'val': segment['physical'], 'size': segment['length'], 'filename': str(part)})
                data = part.read_bytes()
                if len(data) != segment['length']: raise RuntimeError('Truncated native snapshot')
                raw.extend(data); part.unlink()
            if self.validator.fingerprint(raw) != meta['fingerprint_fnv1a64']:
                raise RuntimeError('Native guest/QMP fingerprint mismatch')
        finally:
            self.qmp.call('cont')
        try:
            image = self.validator.decode_image(raw)
        except ValueError:
            # The shoot page can legitimately be a uniform frame (no live view yet).
            rgba = bytearray(len(raw) * 2)
            for n in range(0, len(raw), 2):
                word = raw[n] | raw[n + 1] << 8
                rgba[n * 2:n * 2 + 4] = bytes(((word >> 12) * 17, ((word >> 8) & 15) * 17,
                                               ((word >> 4) & 15) * 17, (word & 15) * 17))
            image = Image.frombytes('RGBA', (640, 480), bytes(rgba))
        stem = f'capture-{ticket:03d}'
        (self.out / f'{stem}.rgba4444').write_bytes(raw)
        preview = Image.new('RGBA', image.size, (0, 0, 0, 255))
        preview.alpha_composite(image)
        preview.convert('RGB').save(self.out / f'{stem}.png')
        record = {'capture_id': ticket, 'native_frame': meta['frame'], 'state': state,
                  'meta': meta, 'raw_sha256': sha256(raw).hexdigest(), 'png': stem + '.png'}
        self.frames.append(record)
        self.send(f'ACK {ticket}')
        if self.until(b'NE_ACK ') != f'NE_ACK {ticket}'.encode():
            raise RuntimeError('Native ACK mismatch')
        self.pending = False
        if self.on_frame: self.on_frame(preview.convert('RGB'))
        return record, preview.convert('RGB')

    def snapshot_state(self):
        self.send('STATE')
        return json.loads(self.until(b'NE_SNAPSHOT ').split(b' ', 1)[1])

    def dump_threads(self):
        if self.pending: raise RuntimeError('Cannot inspect threads while a capture is retained')
        self.send('THREADS')
        return json.loads(self.until(b'NE_THREADS_DONE ').split(b' ', 1)[1])

    def capture_table(self):
        if self.pending: raise RuntimeError('Cannot inspect CaptureId table during retained display capture')
        self.send('CAPTABLE')
        state = json.loads(self.until(b'NE_CAPTURE_TABLE_STATE ').split(b' ', 1)[1])
        if state['physical'] != 0x1ff00000 or state['bytes'] != 0x4014:
            raise RuntimeError('Unexpected CaptureId model RAM bounds')
        self.qmp.call('stop')
        data = []
        try:
            if self.qmp.call('query-status')['status'] != 'paused':
                raise RuntimeError('CaptureId readback did not pause')
            for offset, name, fingerprint in ((0, 'capture-table.bin', state['fingerprint']),
                                              (0x8000, 'capture-table-checkpoint.bin', state['checkpoint_fingerprint'])):
                path = self.out / name
                self.qmp.call('pmemsave', {'val': state['physical'] + offset, 'size': state['bytes'], 'filename': str(path)})
                raw = path.read_bytes()
                if len(raw) != state['bytes'] or self.validator.fingerprint(raw) != fingerprint:
                    raise RuntimeError('CaptureId guest/QMP content mismatch')
                data.append(raw)
        finally:
            self.qmp.call('cont')
        header = [int.from_bytes(data[0][n:n+4], 'little') for n in range(0, 20, 4)]
        if header != state['header'] or header[0] != 1024:
            raise RuntimeError('CaptureId native header contract mismatch')
        return {**state, 'guest_qmp_exact': True, 'sha256': sha256(data[0]).hexdigest(),
                'checkpoint_sha256': sha256(data[1]).hexdigest(), 'checkpoint_matches_live': data[0] == data[1],
                'persistence': 'volatile model RAM only', 'physical_compatibility_verified': False}

    def shoot_request(self):
        self.send('SHOOTREQ')
        if self.until(b'NE_SHOOTREQ_OK') != b'NE_SHOOTREQ_OK':
            raise RuntimeError('Native shoot request failed')

    def transform(self, identifier):
        self.send(f'TRANSFORM {identifier:08x}')
        line = self.until(b'NE_TRANSFORM ')
        return json.loads(line.split(b' ', 1)[1])['trigger']

    def inject_tail(self, ident):
        self.send(f'TAILIN {ident:08x}')
        line = self.until(b'NE_TAIL_INJECTED ')
        time.sleep(0.4)
        self.send('STATE')
        return json.loads(line.split(b' ', 1)[1]), json.loads(self.until(b'NE_SNAPSHOT ').split(b' ', 1)[1])

    def inject_key(self, key, status=1):
        self.send(f'KEYIN {key:08x}')
        self.until(b'NE_KEY_INJECTED ')
        time.sleep(0.4)
        self.send('STATE')
        return json.loads(self.until(b'NE_SNAPSHOT ').split(b' ', 1)[1])

    def raw_event(self, identifier):
        if self.pending: raise ValueError('Invalid raw-event phase')
        self.send(f'EVENT {identifier:08x}')
        line = self.until(b'NE_EVENT_POSTED ')
        return json.loads(line.split(b' ', 1)[1])

    def key(self, name):
        if self.pending or name not in ('UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'MENU'):
            raise ValueError('Invalid native input phase')
        self.input_id += 1
        self.send(f'KEY {self.input_id} {name}')
        sent = json.loads(self.until(b'NE_KEY_SENT ').split(b' ', 1)[1])
        if sent.get('seq') != self.input_id: raise RuntimeError('Native key ticket mismatch')
        return self.input_id

    def after_key(self, name, overlay):
        sequence = self.key(name)
        deadline = time.monotonic() + 12
        previous = self.frames[-1]['native_frame']
        while time.monotonic() < deadline:
            frame, image = self.capture()
            state = frame['state']
            if state['last_input'] >= sequence and state['view_state'] != 1:
                raise RuntimeError('Original view state changed during the owned-menu transaction')
            if (state['last_input'] >= sequence and bool(state['overlay']) == overlay and
                    bool(frame['meta']['overlay_captured']) == overlay and frame['native_frame'] > previous):
                return frame, image
        raise TimeoutError(f'No fresh native frame after {name}')

    def stop(self):
        if self.pending: return False
        self.send('STOP')
        return self.until(b'NE_STOPPED') == b'NE_STOPPED'

    def close(self):
        self.log.close(); self.stream.close(); self.channel.close()


def row_title_pixels(image):
    """Count light pixels in the added row's label box (content, not a fixed glyph mask)."""
    crop = image.convert('RGB').crop((24, 330, 260, 370)).tobytes()
    return sum(1 for n in range(0, len(crop), 3) if min(crop[n:n + 3]) > 170)


def require_entry_title(image):
    if row_title_pixels(image) < 600:
        raise RuntimeError('Original New Menu title pixels are missing or changed')
    pixels = image.convert('RGB').crop((20, 326, 623, 374)).tobytes()
    orange = sum(pixels[n] > 100 and pixels[n] > pixels[n + 1] * 1.5 and pixels[n + 2] < 50
                 for n in range(0, len(pixels), 3))
    if orange < 10000:
        raise RuntimeError('Original New Menu visible highlight is missing')


def exercise(guest):
    initial, _ = guest.capture()
    state = initial['state']
    if not (state['node_installed'] == 1 and state['count'] == 6 and state['selected_own'] == 1 and
            state['title_sets'] > 0 and state['view_state'] == 1 and state['overlay'] == 0):
        raise RuntimeError('Original menu did not display/select the new row')
    previous, _ = guest.after_key('UP', False)
    if previous['state']['selected_own']:
        raise RuntimeError('Original UP did not leave the new row')
    initial, image = guest.after_key('DOWN', False)
    initial, image = settle(guest)
    if not initial['state']['selected_own']:
        raise RuntimeError('Original DOWN did not restore the new row')
    settled = initial
    entry_title_verified = True
    require_entry_title(image)
    guest.entry_title_verified = entry_title_verified
    opened, _ = guest.after_key('ENTER', True)
    if opened['state']['entries'] != 1 or opened['state']['category'] != 7:
        raise RuntimeError('Original confirmation did not enter the owned menu')
    moved, _ = guest.after_key('UP', True)
    if moved['state']['category'] != 6 or moved['raw_sha256'] == opened['raw_sha256']:
        raise RuntimeError('New menu did not consume UP')
    restored, _ = guest.after_key('DOWN', True)
    if restored['raw_sha256'] != opened['raw_sha256']:
        raise RuntimeError('New menu category/pixels failed to restore')
    parent, _ = guest.after_key('MENU', False)
    if not parent['state']['selected_own'] or parent['raw_sha256'] != settled['raw_sha256']:
        raise RuntimeError('Original parent pixels/focus failed to restore')
    again, _ = guest.after_key('ENTER', True)
    if again['state']['entries'] != 2 or again['raw_sha256'] != opened['raw_sha256']:
        raise RuntimeError('Native menu reentry failed')
    final, _ = guest.after_key('MENU', False)
    if final['state']['exits'] != 2 or final['raw_sha256'] != settled['raw_sha256']:
        raise RuntimeError('Second native exit failed')


def settle(guest, limit=8):
    """Capture until two consecutive completed frames are identical (fonts settle)."""
    previous, image = guest.capture()
    for _ in range(limit):
        current, image = guest.capture()
        if current['raw_sha256'] == previous['raw_sha256']:
            return current, image
        previous = current
    raise RuntimeError('Original menu frames kept changing')


VIEW_IDS = (0xA0, 0xA1, 0xA2, 0xA4, 0xA5, 0xB0, 0x11)


def open_probe(guest):
    """Open candidate original views and record which one draws content."""
    if not guest.frames: guest.capture()
    out = []
    for ident in VIEW_IDS:
        guest.send(f'OPENVIEW {ident:04x}')
        guest.until(b'NE_OPENVIEW ')
        time.sleep(1.5)
        record, image = guest.capture()
        colors = len({image.convert('RGB').getpixel((x, y))
                      for y in range(0, 480, 16) for x in range(0, 640, 24)})
        out.append({'id': f'{ident:04x}', 'view': record['state']['view'],
                    'view_state': record['state']['view_state'], 'colors': colors})
    return out


def shoot_observe(guest, frames=6, warmup_ms=0, settle_s=8.0, deadline_s=90.0):
    """Observe original startup over time; a successful capture is not a shooting-page pass."""
    timing = []
    first = guest.snapshot_state()
    timing.append(first)
    deadline = time.monotonic() + deadline_s
    while timing[-1]['guest_ms'] - first['guest_ms'] < warmup_ms and time.monotonic() < deadline:
        time.sleep(1)
        timing.append(guest.snapshot_state())
    if guest.__dict__.get('_shoot_on_ready') and not getattr(guest, '_shoot_sent', False):
        guest.shoot_request()
        guest._shoot_sent = True
        time.sleep(settle_s)
    captured = []
    for _ in range(frames):
        time.sleep(5)
        record, image = guest.capture()
        record['distinct_colors'] = len({image.convert('RGB').getpixel((x, y))
                                         for y in range(0, 480, 24) for x in range(0, 640, 32)})
        captured.append(record)
    threads = guest.dump_threads()
    timing.append(guest.snapshot_state())
    return {'frames': len(captured), 'threads': threads, 'guest_timing': timing,
            'requested_warmup_ms': warmup_ms,
            'warmup_guest_elapsed_ms': timing[-2]['guest_ms'] - first['guest_ms'],
            'distinct_view': sorted({f['state']['view'] for f in captured}),
            'view_state': sorted({f['state']['view_state'] for f in captured}),
            'node_installed': any(f['state']['node_installed'] for f in captured),
            'color_samples': sorted({f['distinct_colors'] for f in captured})}


def shoot_menu_probe(guest):
    # Open as soon as the original shooting view actually draws; waiting for a
    # fixed number of extra frames only widens the known startup-crash window.
    deadline = time.monotonic() + 100
    before = None
    while time.monotonic() < deadline:
        frame, image = guest.capture()
        frame['distinct_colors'] = len({image.convert('RGB').getpixel((x, y))
                                        for y in range(0, 480, 24) for x in range(0, 640, 32)})
        if frame['state']['entries'] == 0xc3 and frame['distinct_colors'] > 1:
            before = frame
            break
        time.sleep(2)
    if before is None:
        return {'shooting_frame': None, 'menu_raw_event': '0x150100f0', 'after_menu': []}
    guest.raw_event(0x150100f0)
    samples = []
    for _ in range(6):
        time.sleep(3)
        frame, _ = guest.capture()
        samples.append({'frame': frame['native_frame'], 'view_id': frame['state']['entries'],
                        'state': frame['state']['view_state'],
                        'changed_pixels': frame['raw_sha256'] != before['raw_sha256']})
    return {'shooting_frame': before, 'menu_raw_event': '0x150100f0', 'after_menu': samples}


def exercise_original(guest):
    initial, _ = settle(guest)
    if initial['state']['node_installed'] or initial['state']['overlay']:
        raise RuntimeError('Original mode unexpectedly installed the A7C2 menu')
    guest.after_key('DOWN', False)
    guest.after_key('UP', False)
    baseline, _ = settle(guest)
    guest.after_key('DOWN', False)
    guest.after_key('UP', False)
    restored, _ = settle(guest)
    if restored['raw_sha256'] != baseline['raw_sha256']:
        raise RuntimeError('Original menu pixels failed to restore after direction navigation')
    if any(f['state']['node_installed'] or f['state']['overlay'] for f in guest.frames):
        raise RuntimeError('Original mode changed the menu tree or rendered an overlay')


ID_CANDIDATES = (0x150100F0, 0x15010040, 0x15010030, 0x15010010,
                 0x15010050, 0x15010060, 0x15010070, 0x15010080)


def id_probe(guest):
    """Post real input-table event ids and record what the shoot page does."""
    observations = []
    if not guest.frames:
        guest.capture()
    for identifier in ID_CANDIDATES:
        before = guest.frames[-1]
        guest.raw_event(identifier)
        frame, _ = guest.capture()
        state, prior = frame['state'], before['state']
        observations.append({'id': f'{identifier:08x}',
                             'view': state['view'], 'view_state': state['view_state'],
                             'changed_view': state['view'] != prior['view'],
                             'changed_state': state['view_state'] != prior['view_state'],
                             'changed_pixels': frame['raw_sha256'] != before['raw_sha256']})
    return observations


KEYS = (0x1AB, 0x1AC, 0xA7, 0x2, 0x1AF, 0x15, 0x3, 0x30, 0x1F1, 0x1F0, 0x7090, 0x7091, 0x7093)


TAIL_IDS = (0x150100F0, 0x1AB, 0x15010040, 0x1AC, 0x15010030, 0xA7)


def tail_probe(guest):
    if not guest.frames: guest.capture()
    out = []
    for ident in TAIL_IDS:
        posted, state = guest.inject_tail(ident)
        out.append({'id': f'{ident:08x}', 'rc': posted['rc'], 'view': state['view'],
                    'view_state': state['view_state'], 'last_input': state['last_input']})
    return out


def keyin_probe(guest):
    """Inject real panel key codes through InputService and record the AP's reaction."""
    if not guest.frames: guest.capture()
    out = []
    prior = guest.inject_key(0) if False else None
    for key in KEYS:
        before = guest.inject_key(key)
        out.append({'key': f'{key:08x}', 'view': before['view'], 'view_state': before['view_state'],
                    'frame': before['frame']})
    return out


def map_probe(guest):
    """Sweep input-table ids through the AP's own trigger matcher."""
    if not guest.frames: guest.capture()
    ids = set()
    import json as _json
    cfg = Path(__file__).resolve().parents[1] / 'evidence' / 'input-ids.json'
    for value in _json.loads(cfg.read_text()):
        ids.add(int(value, 16))
    base = guest.transform(0x15010000)
    mapped, unmapped = [], 0
    for identifier in sorted(ids):
        trigger = guest.transform(identifier)
        if trigger == base:
            unmapped += 1
        else:
            mapped.append({'id': f'{identifier:08x}', 'trigger': f'{trigger:08x}'})
    return {'base': f'{base:08x}', 'view': guest.frames[-1]['state']['view'], 'unmapped': unmapped, 'mapped': mapped[:80]}


def key_probe(guest):
    """Shoot-page navigation probe: original events must be consumed by the AP."""
    observations = []
    for name in ('DOWN', 'UP', 'RIGHT', 'LEFT', 'MENU'):
        before = guest.frames[-1]['state'] if guest.frames else {}
        guest.key(name)
        frame, _ = guest.capture()
        state = frame['state']
        observations.append({'key': name, 'view': state['view'], 'view_state': state['view_state'],
                             'last_input': state['last_input'],
                             'changed_view': state['view'] != before.get('view'),
                             'changed_state': state['view_state'] != before.get('view_state')})
    return observations


def window(guest, self_test, out, a7c2_menu, shoot=False):
    import tkinter as tk
    from PIL import ImageTk, ImageGrab
    root = tk.Tk()
    root.title('ZV-E10 | ' + ('Original shooting page' if shoot else ('A7C2 menu option' if a7c2_menu else 'Original Sony menu')))
    root.resizable(False, False)
    panel = tk.Label(root, borderwidth=0)
    panel.pack()
    controls = tk.Frame(root)
    controls.pack(fill='x')
    failure, displayed = [], []
    checked = False

    def show(image):
        displayed[:] = [image]
        panel.image = ImageTk.PhotoImage(image)
        panel.configure(image=panel.image)
        root.update_idletasks()
        if (self_test and guest.frames[-1]['state']['overlay'] and
                guest.frames[-1]['meta']['overlay_captured'] and not (out / 'visible-new-menu.png').exists()):
            bounds = (panel.winfo_rootx(), panel.winfo_rooty(), panel.winfo_rootx()+640, panel.winfo_rooty()+480)
            visible = ImageGrab.grab(bbox=bounds).convert('RGB')
            visible.save(out / 'visible-new-menu.png')
            if visible.tobytes() != image.tobytes():
                raise RuntimeError('Visible owned menu differs from its guest frame')

    def send(name):
        state = guest.frames[-1]['state']
        if not state['overlay'] and (name == 'MENU' or (name == 'ENTER' and not state['selected_own'])):
            return
        overlay = bool(state['overlay'])
        if name == 'MENU': overlay = False
        elif name == 'ENTER' and state['selected_own']: overlay = True
        try:
            guest.after_key(name, overlay)
        except Exception as error:
            failure.append(error); root.destroy()

    keys = () if shoot else (('UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'MENU') if a7c2_menu else ('UP', 'DOWN', 'LEFT', 'RIGHT'))
    if shoot:
        tk.Label(controls, text='原拍摄页面 · 镜头状态与按键尚未就绪').pack()
    for name in keys:
        tk.Button(controls, text=name, command=lambda key=name: send(key)).pack(side='left', expand=True, fill='x')
    for event, name in [('<Up>','UP'),('<Down>','DOWN'),('<Left>','LEFT'),('<Right>','RIGHT'),
                        ('<Return>','ENTER'),('<Escape>','MENU')]:
        if not shoot: root.bind(event, lambda _, key=name: send(key))
    root.protocol('WM_DELETE_WINDOW', root.destroy)
    guest.on_frame = show

    def check():
        nonlocal checked
        try:
            root.update()
            bounds = (panel.winfo_rootx(), panel.winfo_rooty(), panel.winfo_rootx()+640, panel.winfo_rooty()+480)
            visible = ImageGrab.grab(bbox=bounds).convert('RGB')
            visible.save(out / 'visible-initial.png')
            if visible.tobytes() != displayed[-1].tobytes():
                raise RuntimeError('Visible native window differs from the guest frame')
            if shoot:
                shoot_observe(guest, frames=12)
                if guest.frames[-1]['state']['entries'] != 0xc3 or guest.frames[-1]['distinct_colors'] < 2:
                    raise RuntimeError('Original shooting view has no visible content')
            else:
                (exercise if a7c2_menu else exercise_original)(guest)
            visible = ImageGrab.grab(bbox=bounds).convert('RGB')
            visible.save(out / 'visible-parent.png')
            if visible.tobytes() != displayed[-1].tobytes():
                raise RuntimeError('Visible restored parent differs from its guest frame')
            checked = True
        except Exception as error:
            failure.append(error)
        finally:
            root.destroy()

    def load_shoot(attempt=0):
        try:
            frame, image = guest.capture()
            if frame['state']['entries'] == 0xc3 and len(image.getcolors(640 * 480) or []) > 1:
                return
            if attempt >= 90:
                raise RuntimeError('Original shooting page did not render within the observation window')
            root.after(1000, lambda: load_shoot(attempt + 1))
        except Exception as error:
            failure.append(error); root.destroy()

    try:
        guest.capture()
        if self_test: root.after(250, check)
        elif shoot: root.after(1000, load_shoot)
        root.mainloop()
    finally:
        guest.on_frame = None
        try: root.destroy()
        except tk.TclError: pass
    if failure: raise failure[0]
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--a7c2-menu', action='store_true', help='enable the optional A7C2 resource menu; default is original Sony menu')
    parser.add_argument('--a7c2-assets', type=Path, help='optional resource ZIP or prepared a7c2-root directory; enables A7C2 mode')
    parser.add_argument('--out', type=Path, help='new run directory; defaults to output/menu-<unique-id>')
    display = parser.add_mutually_exclusive_group()
    display.add_argument('--window', action='store_true', help='show real guest pixels (default)')
    display.add_argument('--headless', action='store_true', help='run bounded verification without a window')
    parser.add_argument('--open-probe', action='store_true', help='shoot page: open candidate views via root vtable+0x90')
    parser.add_argument('--tail-probe', action='store_true', help='shoot page: createEvent+pushFilterEvent tail injection')
    parser.add_argument('--keyin-probe', action='store_true', help='shoot page: inject panel key codes via InputService')
    parser.add_argument('--map-probe', action='store_true', help='shoot page: map input ids through the AP trigger matcher')
    parser.add_argument('--id-probe', action='store_true', help='shoot page: post real input-table ids and record effects')
    parser.add_argument('--key-probe', action='store_true', help='shoot page: send direction/MENU events and record AP consumption')
    parser.add_argument('--start-page', choices=('menu','shoot'), default='menu', help='menu: open settings menu; shoot: let the AP pick its own start page')
    parser.add_argument('--capture-table-model', action='store_true', help='explicit local model: provide one empty native CaptureId table in reserved guest RAM; requires --shoot-view')
    parser.add_argument('--full-services', action='store_true',
                        help='explicit full-service boot: overlay restores the original libIMDB.so target table (default target == qemu target) so the USB/tethering services omitted by the AP-only shortcut initialize at boot')
    parser.add_argument('--shoot-view', action='store_true', help='shoot probe only: request original Stlrec view 0xc3 through the guarded native selector on the UI thread')
    parser.add_argument('--smp', type=int, choices=(1, 2), default=1,
                        help='guest CPU count; default 1 keeps prior behaviour, 2 matches the SMP-preempt original kernel')
    parser.add_argument('--test-pattern', action='store_true', help='shoot probe only: composite diagnostic colour bars on the display output')
    parser.add_argument('--self-test', action='store_true', help='exercise and close the visible window automatically')
    args = parser.parse_args()
    if (args.test_pattern or args.shoot_view or args.capture_table_model) and (args.start_page != 'shoot' or args.a7c2_menu or args.a7c2_assets):
        parser.error('shoot models require --start-page shoot in original mode')
    if args.capture_table_model and not (args.shoot_view or args.full_services):
        parser.error('--capture-table-model requires --shoot-view or --full-services')
    import uuid
    out = (args.out or ROOT / 'output' / ('menu-' + uuid.uuid4().hex[:12])).resolve()
    zroot = ROOT
    a7c2_menu = args.a7c2_menu or args.a7c2_assets is not None
    donor = None
    if a7c2_menu:
        from menu_resources import prepare_resources, validate_root
        import zipfile
        try:
            asset_path = args.a7c2_assets or ROOT / 'work/a7c2-menu-assets/a7c2-root'
            if asset_path.is_file():
                destination = ROOT / 'work' / ('a7c2-import-' + digest(asset_path)[:16])
                asset_path = validate_root(destination / 'a7c2-root') if destination.exists() else prepare_resources(asset_path, destination)
            donor = validate_root(asset_path)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            parser.exit(1, f'A7C2 resource preparation failed: {error}\n')
    if out.exists(): parser.error('--out must be a new directory')
    result = {'ok': False, 'original_menu_row_verified': False, 'native_entry_verified': False,
              'qmp_quit': False, 'qemu_signal_used': False, 'original_panel_input_verified': False,
              'input_model': 'original-native-function-event', 'guest_done': False,
              'mode': 'a7c2-menu' if a7c2_menu else 'original',
              'a7c2_resources_required': a7c2_menu} 
    process = qmp = guest = None
    control = None
    try:
        build(zroot, donor, out, args.start_page, args.test_pattern, args.shoot_view, args.capture_table_model, args.full_services)
        validator = load_module('zve_legacy_capture', zroot / 'scripts/capture-menu.py')
        control = tempfile.mkdtemp(prefix='zve-native-entry-')
        qmp_path, serial_path = Path(control) / 'qmp', Path(control) / 'serial'
        command = host.qemu_command(zroot / 'work/qemu-src/build-zve10/qemu-system-arm', zroot) + ['-nodefaults', '-no-user-config',
                   '-M', 'zve10', '-cpu', 'cortex-a9', '-smp', str(args.smp), '-m', '1024',
                   '-kernel', str(zroot / 'work/kbuild-ui/arch/arm/boot/Image'), '-initrd', str(out / 'native-ui.cpio'),
                   '-append', 'console=ttyAM0,115200n8 cfg.uart=1 mem=1G@0 memrsv=0x1A5E000@0x02E68000 memrsv=128M@0x20000000:uc rdinit=/init loglevel=8 ' + __import__('os').environ.get('ZVE_APPEND', ''),
                   '-display', 'none', '-serial', f'unix:{serial_path},server=on,wait=on',
                   '-qmp', f'unix:{qmp_path},server=on,wait=off', '-monitor', 'none', '-no-reboot']
        if args.capture_table_model:
            index = command.index('-append') + 1
            command[index] += ' memrsv=128K@0x1ff00000 '
        for relative, expected in host.ASSETS.items():
            if digest(zroot / relative) != expected: raise RuntimeError('Baseline launch asset differs')
        result['command'] = command
        import os
        environment = os.environ.copy()
        for name in ('ZVE10_NO_UART_IRQ', 'ZVE10_NO_TIMER_IRQ'): environment.pop(name, None)
        with (out / 'qemu.log').open('wb') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=environment)
            result['qemu_pid'] = process.pid
            serial = None
            try:
                serial = host.connect(serial_path, process)
                qmp = host.Qmp(host.connect(qmp_path, process))
                result['block_devices'] = qmp.call('query-block')
                if result['block_devices']: raise RuntimeError('Unexpected native candidate block device')
                guest = NativeGuest(serial, qmp, out, validator)
                result['ready'] = guest.ready()
                if args.open_probe:
                    result['probe'] = open_probe(guest)
                    verified = True
                elif args.shoot_view and args.key_probe:
                    result['probe'] = shoot_menu_probe(guest)
                    verified = True
                elif args.shoot_view and not args.headless:
                    verified = window(guest, args.self_test, out, False, shoot=True)
                    result['window_rgb_exact'] = verified
                elif args.start_page == 'shoot' and not (args.key_probe or args.id_probe or args.map_probe or args.tail_probe or args.keyin_probe):
                    if args.full_services and args.shoot_view:
                        guest._shoot_on_ready = True  # host requests 0xc3 after the warm-up settle
                    result['probe'] = shoot_observe(guest, frames=12 if args.shoot_view else 6,
                                                    warmup_ms=60000 if args.capture_table_model else (20000 if args.shoot_view else 0),
                                                    settle_s=8.0, deadline_s=180.0 if args.full_services else 90.0)
                    result['shoot_request_host_driven'] = bool(args.full_services and args.shoot_view)
                    verified = True
                elif args.tail_probe:
                    result['probe'] = tail_probe(guest)
                    verified = True
                elif args.keyin_probe:
                    result['probe'] = keyin_probe(guest)
                    verified = True
                elif args.map_probe:
                    result['probe'] = map_probe(guest)
                    verified = True
                elif args.id_probe:
                    result['probe'] = id_probe(guest)
                    verified = True
                elif args.key_probe:
                    result['probe'] = key_probe(guest)
                    verified = True
                elif not args.headless:
                    verified = window(guest, args.self_test, out, a7c2_menu)
                    result['window_rgb_exact'] = verified
                    if a7c2_menu:
                        result['entry_title_verified'] = bool(getattr(guest, 'entry_title_verified', False))
                        if getattr(guest, 'entry_title_error', None):
                            result['entry_title_error'] = guest.entry_title_error
                else:
                    (exercise if a7c2_menu else exercise_original)(guest)
                    if a7c2_menu:
                        result['entry_title_verified'] = getattr(guest, 'entry_title_verified', False)
                        if getattr(guest, 'entry_title_error', None):
                            result['entry_title_error'] = guest.entry_title_error
                    verified = True
                result['test_pattern_enabled'] = args.test_pattern
                result['shoot_view_requested'] = args.shoot_view
                result['capture_table_model'] = args.capture_table_model
                result['full_services'] = args.full_services
                result['shooting_page_rendered'] = args.shoot_view and any(
                    f['state']['entries'] == 0xc3 and f.get('distinct_colors', 0) > 1 for f in guest.frames)
                result['shooting_page_verified'] = False
                after_menu = result.get('probe', {}).get('after_menu', []) if args.key_probe else []
                result['shooting_to_menu_verified'] = any(
                    f.get('view_id') == 0xba and f.get('changed_pixels') for f in after_menu)
                result['semantic_checks_performed'] = verified and args.start_page == 'menu'
                result['original_menu_verified'] = verified and args.start_page == 'menu'
                result['original_menu_row_verified'] = verified and a7c2_menu
                result['native_entry_verified'] = verified and a7c2_menu
                if args.capture_table_model:
                    guest.send('UIPC')
                    result['uipc_dump'] = json.loads(guest.until(b'NE_UIPC_DONE ').split(b' ', 1)[1])
                    result['capture_table_readback'] = guest.capture_table()
                result['guest_done'] = guest.stop()
                if not result['guest_done']: raise RuntimeError('Native control did not stop normally')
                result['shooting_page_display_verified'] = bool(result['shooting_page_rendered'])
                result['ok'] = True
            except Exception as error:
                result['error'] = f'{type(error).__name__}: {error}'
            finally:
                try:
                    if guest:
                        result['frames'] = guest.frames; result['events'] = guest.events
                        try:
                            if not result.get('error') and not result['guest_done'] and not guest.pending:
                                result['guest_done'] = guest.stop()
                        except Exception as error:
                            result['native_control_close_error'] = str(error)
                            result['ok'] = False
                        guest.close()
                    elif serial:
                        serial.close()
                except Exception as error:
                    result['native_serial_close_error'] = str(error)
                    result['ok'] = False
                finally:
                    host.finish(process, qmp, None, qmp_path, result)
    except Exception as error:
        result['error'] = result.get('error', f'{type(error).__name__}: {error}')
    finally:
        if control:
            if process is None or process.poll() is not None: shutil.rmtree(control)
            else: result['retained_control_directory'] = control
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'ok': result['ok'], 'result': str(out / 'result.json'), 'error': result.get('error')}, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
