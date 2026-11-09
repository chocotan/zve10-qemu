"""QMP and normal-owner shutdown shared by both menu modes."""
import hashlib
import json
from pathlib import Path
import select
import socket
import time

ASSETS = {
    'work/qemu-src/build-zve10/qemu-system-arm': '9bbe1b5b74ff60fc5f90d6481a7c1921bf777158c8f30dd038c17c909f144d7a',
    'work/kbuild-ui/arch/arm/boot/Image': 'f2a608ee75459fb15c6243b0a3ec3460a1015bb602af37a21df81b3cc6784772',
}

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def fingerprint(raw):
    value = 0xcbf29ce484222325
    for byte in raw:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return f'{value:016x}'

def connect(path, process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        channel = socket.socket(socket.AF_UNIX)
        channel.settimeout(15)
        try:
            channel.connect(str(path))
            return channel
        except (FileNotFoundError, ConnectionRefusedError):
            channel.close()
            if process.poll() is not None:
                raise RuntimeError('QEMU exited before its socket became ready')
            select.select([], [], [], 0.02)
    raise TimeoutError(f'QEMU socket not ready: {path.name}')

def qemu_command(binary, root):
    """Use the package's loader/library closure when present, without global LD_LIBRARY_PATH."""
    libraries = Path(root) / 'runtime/qemu-libs'
    if not libraries.exists():
        return [str(binary)]
    manifest = json.loads((libraries / 'manifest.json').read_text())
    for name, record in manifest['files'].items():
        if Path(name).name != name:
            raise ValueError('Invalid packaged QEMU library name')
        path = libraries / name
        if path.is_symlink() or path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            raise ValueError('Packaged QEMU library identity differs: ' + name)
    loader = libraries / 'ld-linux-x86-64.so.2'
    if loader.name not in manifest['files']:
        raise ValueError('Missing packaged QEMU loader')
    return [str(loader), '--library-path', str(libraries), str(binary)]


class Qmp:
    def __init__(self, channel):
        self.channel = channel
        self.stream = channel.makefile('rwb')
        self.ticket = 0
        if 'QMP' not in json.loads(self.stream.readline()):
            raise RuntimeError('No QMP greeting')
        self.call('qmp_capabilities')

    def call(self, name, arguments=None):
        self.ticket += 1
        self.stream.write((json.dumps({'execute': name, 'arguments': arguments or {},
                                      'id': self.ticket}) + '\n').encode())
        self.stream.flush()
        while True:
            line = self.stream.readline()
            if not line:
                raise RuntimeError(f'QMP closed during {name}')
            reply = json.loads(line)
            if 'event' in reply:
                continue
            if reply.get('id') != self.ticket:
                raise RuntimeError('QMP response identity mismatch')
            if 'error' in reply:
                raise RuntimeError(reply['error'])
            return reply['return']

    def close(self):
        self.stream.close()
        self.channel.close()

def finish(process, qmp, guest, endpoint, result):
    errors = []
    if guest:
        result.update(boot=guest.boot, frames=guest.frames, inputs=guest.inputs)
        try:
            guest.close()
        except Exception as error:
            errors.append(f'guest.close: {type(error).__name__}: {error}')
    try:
        if process.poll() is None:
            if qmp is None:
                qmp = Qmp(connect(endpoint, process))
            qmp.call('quit')
            result['qmp_quit'] = True
    except Exception as error:
        errors.append(f'qmp.quit: {type(error).__name__}: {error}')
    finally:
        if qmp:
            try:
                qmp.close()
            except Exception as error:
                errors.append(f'qmp.close: {type(error).__name__}: {error}')
        try:
            result['qemu_rc'] = process.wait(timeout=15)
        except Exception as error:
            result['qemu_rc'] = None
            errors.append(f'owner.wait: {type(error).__name__}: {error}')
        result['qemu_exited'] = process.poll() is not None
    if errors:
        result['cleanup_errors'] = errors
    if errors or result['qemu_rc'] != 0 or not result.get('qmp_quit') or not result['qemu_exited']:
        result['ok'] = False
        result.setdefault('error', 'QEMU cleanup did not complete normally')

