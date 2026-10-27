#!/usr/bin/env python3
"""Prepare ZV-E10 firmware into work/ for the emulator.

Takes the official macOS update package, extracts the firmware image, decrypts
and unpacks it with fwtool.py, then extracts the camera filesystems and the
settings the emulator boots from. Only reads the user's own firmware; nothing
is flashed or executed from it.

Requires: 7z, debugfs (e2fsprogs), and a fwtool.py checkout with its Python
dependencies installed. See docs/setup.md.
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'

# From the 2.03 update package; a mismatch means a different firmware revision.
DMG_SHA256 = '547948c49d28c31de04726113d94cd2200817a0af8e0d7d90abf2b321f19fca8'
FIRMWARE_DAT_SHA256 = '8f1cae050e96403ee035dd0b858417916c0c8c60d6eed777afbea159c71ace64'

# Extracted firmware tree -> local destination.
PARTITIONS = {
    'nflasha3': ('work/boot', 'fat'),          # initrd image
    'nflasha7': ('work/rootfs', 'ext2'),       # root filesystem
    'nflasha15': ('work/usr', 'ext2'),         # /usr
}
# Backup template the camera uses for its settings; one of the region variants.
BACKUP_TEMPLATE = '0110_backup/SYSASTRA-DSLR/RK/CX88701_ALLLANG.bin'


def run(cmd, **kwargs):
    print('+', ' '.join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def need(command):
    if not shutil.which(command):
        sys.exit(f'missing required command: {command} (see docs/setup.md)')


def extract_dmg(dmg, out):
    if not dmg.exists():
        sys.exit(f'{dmg} not found; download the ZV-E10 2.03 update package first')
    actual = sha256(dmg)
    if actual != DMG_SHA256:
        sys.exit(f'{dmg} is not the expected 2.03 package\n  expected {DMG_SHA256}\n  actual   {actual}')
    run(['7z', 'x', '-y', dmg, f'-o{out}'])
    found = list(out.rglob('FirmwareData_*.dat'))
    if len(found) != 1:
        sys.exit(f'expected one FirmwareData_*.dat in {out}, found {len(found)}')
    if sha256(found[0]) != FIRMWARE_DAT_SHA256:
        sys.exit(f'{found[0]} is not the expected firmware image')
    return found[0]


def unpack_firmware(dat, fwtool, python, out):
    if not fwtool.exists():
        sys.exit(f'fwtool.py not found at {fwtool}; clone it as described in docs/setup.md')
    probe = subprocess.run([python, '-c', 'import yaml,Crypto.Cipher'], capture_output=True)
    if probe.returncode:
        sys.exit(f'{python} cannot import fwtool dependencies (yaml, pycryptodome);\n'
                 'install them or pass --fwtool-python pointing at a venv that has them')
    run([python, fwtool, 'unpack', '-f', dat, '-o', out])
    roots = [p for p in out.rglob('0700_part_image') if p.is_dir()]
    if len(roots) != 1:
        sys.exit(f'expected one 0700_part_image in {out}, found {len(roots)}')
    return roots[0].parent


def extract_partition(image, kind, dest):
    if not image.exists():
        sys.exit(f'{image} not found; firmware unpack may have failed')
    dest.mkdir(parents=True, exist_ok=True)
    if kind == 'fat':
        run(['7z', 'x', '-y', image, f'-o{dest}'])
    else:
        # rdump keeps symlinks, permissions and device nodes. Without root it
        # cannot restore ownership; file contents are unaffected.
        result = subprocess.run(['debugfs', '-R', f'rdump / {dest}', str(image)],
                                capture_output=True, text=True)
        if result.returncode:
            sys.exit(f'debugfs failed on {image}:\n{result.stderr.strip()}')
        ownership = [l for l in result.stderr.splitlines() if 'changing ownership' in l]
        other = [l for l in result.stderr.splitlines()
                 if l.strip() and 'changing ownership' not in l]
        for line in other:
            print('  debugfs:', line, file=sys.stderr)
        if ownership:
            print(f'  note: {len(ownership)} entries keep the invoking user as owner '
                  '(run under fakeroot or as root to preserve the firmware ownership)')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dmg', type=Path, default=ROOT / 'Update_ZVE10V203.dmg',
                        help='official ZV-E10 2.03 update package')
    parser.add_argument('--fwtool', type=Path, default=WORK / 'fwtool/fwtool.py',
                        help='path to fwtool.py')
    parser.add_argument('--fwtool-python', default=sys.executable,
                        help='interpreter that can import fwtool dependencies')
    parser.add_argument('--keep-intermediate', action='store_true',
                        help='keep the large DMG and firmware.tar extraction directories')
    args = parser.parse_args()

    for command in ('7z', 'debugfs'):
        need(command)

    WORK.mkdir(exist_ok=True)
    for name in ('rootfs', 'usr', 'boot', 'setting', 'tmp'):
        if (WORK / name).exists():
            sys.exit(f'work/{name} already exists; keep or rename it before unpacking a fresh copy')
    dmg_out = WORK / 'update'
    fw_out = WORK / 'unpacked'

    print('== 1/4 extract firmware image from the update package')
    dat = extract_dmg(args.dmg, dmg_out)

    print('== 2/4 decrypt and unpack the firmware')
    fw_root = unpack_firmware(dat, args.fwtool, args.fwtool_python, fw_out)

    print('== 3/4 extract camera filesystems')
    dev = fw_root / '0700_part_image/dev'
    for name, (rel, kind) in PARTITIONS.items():
        print(f'-- {name} -> {rel}')
        extract_partition(dev / name, kind, ROOT / rel)

    print('== 4/4 copy settings the emulator boots from')
    for source, dest in ((fw_root / '0800_appli/setting', WORK / 'setting'),
                         (fw_root / '0800_appli/tmp', WORK / 'tmp')):
        if source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
    backup = fw_root / BACKUP_TEMPLATE
    if not backup.is_file():
        sys.exit(f'backup template {backup} not found')
    (WORK / 'setting').mkdir(parents=True, exist_ok=True)
    for name in ('Backup.bin', 'Backup.bak'):
        shutil.copyfile(backup, WORK / 'setting' / name)

    required = ('rootfs/bin/busybox', 'rootfs/kmod/devno.ko', 'rootfs/kmod/dmac.ko',
                'usr/bin/bootin.elf', 'usr/bin/im.elf', 'usr/lib/libIMDB.so',
                'boot/initrd.img', 'setting/DmmConfig.bin')
    for name in required:
        if not (WORK / name).is_file():
            sys.exit(f'incomplete extraction: work/{name} is missing')
    library = WORK / 'usr/lib/libObj.so'
    if not library.is_file() or sha256(library) != 'cfdc59b94fa56116e9d99154ca03a2c1aaf6039dd272679b78b0b76e21c722ac':
        sys.exit('extracted libObj.so does not match the supported ZV-E10 2.03 build')

    if not args.keep_intermediate:
        shutil.rmtree(dmg_out, ignore_errors=True)

    print('\nfirmware prepared under work/:')
    for rel in ('rootfs', 'usr', 'boot', 'setting', 'tmp'):
        path = WORK / rel
        count = sum(1 for _ in path.rglob('*')) if path.is_dir() else 0
        print(f'  {rel}/ ({count} entries)')
    print('\nnext: build the kernel and QEMU, then run ./start-zve10.sh')
    print('see docs/setup.md for the build steps')


if __name__ == '__main__':
    main()
