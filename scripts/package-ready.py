#!/usr/bin/env python3
"""Build a private Linux x86_64 ready-to-run bundle from verified local files."""
import argparse
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'zve10-qemu-linux-x86_64-v2'
FIRMWARE_SHA = '547948c49d28c31de04726113d94cd2200817a0af8e0d7d90abf2b321f19fca8'


def digest(path):
    with path.open('rb') as source:
        return file_digest(source, 'sha256').hexdigest()


def package(output):
    output = Path(output).resolve()
    if output.exists(): raise ValueError('Archive must not already exist')
    output.parent.mkdir(parents=True, exist_ok=True)
    firmware = ROOT / 'Update_ZVE10V203.dmg'
    if digest(firmware) != FIRMWARE_SHA: raise ValueError('Official firmware identity differs')
    selected = []
    for name in ('source', 'scripts', 'tests', 'docs'):
        for path in (ROOT / name).rglob('*'):
            if path.is_file() and not any(p in ('__pycache__', '.pytest_cache') for p in path.parts):
                selected.append(path)
    selected += [ROOT / name for name in ('README.md', 'LICENSE', 'THIRD-PARTY.md', 'AGENTS.md', 'requirements.txt')]
    selected += list(ROOT.glob('start*.sh'))
    for name in ('Update_ZVE10V203.dmg', 'work/ui.cpio', 'work/usr/lib/libObj.so',
                 'work/usr/lib/viewUnified2.so', 'work/usr/lib/CautionConfig.so',
                 'work/qemu-src/build-zve10/qemu-system-arm', 'work/kbuild-ui/arch/arm/boot/Image',
                 'work/kbuild-clean/arch/arm/boot/Image', 'work/kbuild-ui/usr/gen_init_cpio',
                 'incoming/a7c2-menu-resources-2.01-v1.zip'):
        path = ROOT / name
        if not path.is_file() or path.is_symlink(): raise ValueError('Missing ordinary ready file: ' + name)
        selected.append(path)
    for name in ('work/armv7-eabihf--glibc--stable-2020.08-1', 'runtime/qemu-libs'):
        for path in (ROOT / name).rglob('*'):
            if path.is_symlink():
                if not path.resolve().is_relative_to(ROOT): raise ValueError('External toolchain symlink')
                selected.append(path)
            elif path.is_file(): selected.append(path)
    selected = sorted(set(selected))
    total = sum(path.lstat().st_size for path in selected)
    if shutil.disk_usage(output.parent).free < total * 2 + 256 * 1024 * 1024:
        raise OSError('Insufficient host space for staging and archive')
    records = {}
    with tempfile.TemporaryDirectory(prefix='.ready-bundle-', dir=output.parent) as temporary:
        stage = Path(temporary) / NAME
        stage.mkdir()
        for path in selected:
            name = path.relative_to(ROOT).as_posix()
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink():
                link = os.readlink(path)
                target.symlink_to(link)
                records[name] = {'symlink': link}
            else:
                subprocess.run(['cp', '--reflink=auto', '--preserve=mode,timestamps', str(path), str(target)], check=True)
                source_hash = digest(path)
                if digest(target) != source_hash: raise ValueError('Bundle staging readback differs: ' + name)
                records[name] = {'bytes': target.stat().st_size, 'sha256': source_hash,
                                 'mode': stat.S_IMODE(target.stat().st_mode)}
        manifest = {'schema': 1, 'name': NAME, 'platform': 'Linux x86_64',
                    'default_mode': 'original', 'a7c2_mode': 'explicitly optional',
                    'official_firmware_sha256': FIRMWARE_SHA,
                    'host_requirements': ['Python 3.11+', 'Pillow', 'pyelftools', 'capstone', 'Tk/X11 for a window'],
                    'shooting_page_display_verified': True,
                    'shooting_to_menu_verified': False,
                    'shooting_view_capture_video_verified': False, 'files': records}
        (stage / 'BUNDLE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (stage / 'START-HERE.txt').write_text(
            'Linux x86_64 ready-to-run ZV-E10 menu bundle\n\n'
            './start.sh           Original Sony menu (default; no A7C2 assets needed)\n'
            './start-a7c2.sh      Optional A7C2 resource menu\n'
            './start.sh --headless    Bounded console verification\n'
            './start.sh --start-page shoot --shoot-view --capture-table-model\n'
            '                       Original shooting-page display (experimental)\n\n'
            'Includes the official ZV-E10 2.03 update package, compiled QEMU and\n'
            'its shared libraries, prepared guest files, kernel and ARM toolchain.\n'
            'Python 3.11+, Pillow, pyelftools, capstone and optional Tk/X11 are\n'
            'ordinary host dependencies; start.sh reports anything missing.\n'
            'The original shooting page can draw its HUD. Shooting-page MENU\n'
            'transition, live view, photo and video are NOT ready. Startup remains\n'
            'nondeterministic; failed runs are retained in their output directory.\n'
            'No camera or physical SD is connected. No firmware is flashed.\n'
            'This local bundle contains original firmware and is not part of Git.\n'
            'See README.md and docs/menu-modes.md for scope and validation.\n')
        part = output.with_name(output.name + '.part')
        with tarfile.open(part, 'w:gz', compresslevel=3, dereference=False) as archive:
            archive.add(stage, arcname=NAME)
        if output.exists(): raise ValueError('Archive destination appeared during packing')
        part.rename(output)
    archive_hash = digest(output)
    output.with_name(output.name + '.sha256').write_text(f'{archive_hash}  {output.name}\n')
    receipt = {'archive': output.name, 'bytes': output.stat().st_size, 'sha256': archive_hash,
               'payload_files': len(records), 'uncompressed_file_bytes': total,
               'official_firmware_included': True, 'qemu_and_libraries_included': True,
               'default_mode': 'original', 'a7c2_optional': True, 'published_to_git': False}
    output.with_name(output.name + '.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.out), indent=2))
