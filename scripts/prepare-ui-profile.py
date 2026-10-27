#!/usr/bin/env python3
"""Copy the verified A7C2 AP-only target selection to the ARM32 IMDB layout."""
from io import BytesIO
from pathlib import Path
import hashlib
import json
import struct
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'work/usr/lib/libIMDB.so'
destination = ROOT / 'work/initramfs-ui/usr/lib/libIMDB.so'
raw = source.read_bytes()
elf = ELFFile(BytesIO(raw))
assert elf.elfclass == 32 and elf['e_machine'] == 'EM_ARM'

def file_offset(address):
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_vaddr'] <= address < segment['p_vaddr'] + segment['p_filesz']:
            return segment['p_offset'] + address - segment['p_vaddr']
    raise ValueError(f'Unmapped address {address:#x}')

def string(address):
    start = file_offset(address)
    return raw[start:raw.index(b'\0', start)].decode()

symbols = {s.name: s for s in elf.get_section_by_name('.dynsym').iter_symbols()}
base = symbols['imdb_raw']['st_value']
assert base == 0xe4b0
qemu_name = struct.unpack_from('<I', raw, file_offset(base + 12))[0]
assert string(qemu_name) == 'qemu'
exclude = {
    'libUsbBusPower.so', 'libInfraUsbCmn.so', 'libsensapi.so', 'libUsbControl.so',
    'libBusPower.so', 'libHotplug.so', 'libInfraCrypt.so', 'libInfraMediaPwrMgr.so',
    'libNetServiceTethering.so', 'libTetheringResource.so',
    '/usr/kmod/liro.ko',
}
copy = bytearray(raw)
changed = []
kept = set()
for index in range(300):
    offset = file_offset(base + 0x84 + index * 0x2c)
    kind, phase, targets, identity, name_pointer = struct.unpack_from('<5I', raw, offset)
    if kind == 40:
        break
    name = string(name_pointer)
    if name in exclude:
        assert targets & 2, name
        struct.pack_into('<I', copy, offset + 8, targets & ~2)
        assert struct.unpack_from('<I', copy, offset + 8)[0] & 1 == targets & 1
        changed.append({'name': name, 'file_offset': hex(offset + 8), 'before': hex(targets), 'after': hex(targets & ~2)})
    if name in {'appFw.so', 'libgrm.so', 'libuxengine.so'}:
        assert targets & 2, name
        kept.add(name)
else:
    raise AssertionError('Missing IMDB end marker')
assert {item['name'] for item in changed} == exclude
assert len(kept) == 3
assert sum(a != b for a, b in zip(raw, copy)) == len(exclude)
destination.chmod(destination.stat().st_mode | 0o200)
destination.write_bytes(copy)
print(json.dumps({'source_sha256': hashlib.sha256(raw).hexdigest(), 'changed': changed,
                  'application_and_graphics_retained': sorted(kept), 'destination': str(destination)}, indent=2))
