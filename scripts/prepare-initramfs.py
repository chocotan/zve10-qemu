#!/usr/bin/env python3
"""Assemble the emulator initramfs trees from the prepared firmware.

Run after scripts/prepare-firmware.py. Produces:

  work/initramfs-camera/  shell boot: root filesystem plus the settings
  work/camera.cpio        packed initramfs for ./start-zve10.sh
  work/initramfs-ui/      original application: adds /usr, /system and the
                          UI init used by ./start-zve10-ui.sh

Both trees are built from the extracted firmware only; no file inside the
camera images is modified. The shell init is compiled from source here.
"""
import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'

# Files from the boot partition that stay in work/boot for the boot loader.
BOOT_ONLY = {'initrd.img', 'vmlinux.bin'}

# Without /dev/console the kernel cannot attach stdio to init, so the shell
# never becomes usable. The tty names match the kernel command line.
DEVICE_NODES = {
    'console': (5, 1),
    'null': (1, 3),
    'kmsg': (1, 11),
    'ttyAM0': (204, 16),
    'ttyAMA0': (204, 64),
}

DEFAULT_CROSS = WORK / 'armv7-eabihf--glibc--stable-2020.08-1/bin/arm-linux-'


def need(path, why):
    if not path.exists():
        sys.exit(f'{path} not found: {why}')


def copy_tree(source, dest):
    shutil.copytree(source, dest, dirs_exist_ok=True, symlinks=True)


def copy_file(source, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def compile_shell_init(cross, out):
    compiler = os.environ.get('CROSS_COMPILE', str(cross)) + 'gcc'
    if not shutil.which(compiler):
        sys.exit(f'{compiler} not found; set CROSS_COMPILE to your ARM toolchain prefix')
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(compiler), '-nostdlib', '-static', '-Os',
                    '-fomit-frame-pointer', '-fno-stack-protector', '-Wl,-e,_start',
                    '-o', str(out), str(ROOT / 'source/initramfs/init-shell.c')],
                   check=True)
    return out


def create_device_nodes(tree):
    dev = tree / 'dev'
    dev.mkdir(parents=True, exist_ok=True)
    for name, (major, minor) in DEVICE_NODES.items():
        node = dev / name
        node.unlink(missing_ok=True)
        try:
            os.mknod(node, stat.S_IFCHR | 0o600, os.makedev(major, minor))
        except PermissionError:
            sys.exit(f'cannot create {node}; run this preparation in a saved fakeroot session:\n'
                     '  fakeroot -s work/fakeroot.state python3 scripts/prepare-initramfs.py')


def build_camera(init):
    tree = WORK / 'initramfs-camera'
    copy_tree(WORK / 'rootfs', tree)
    copy_tree(WORK / 'setting', tree / 'setting')
    (tree / 'etc/ld.so.preload').unlink(missing_ok=True)
    create_device_nodes(tree)
    copy_file(init, tree / 'init')
    (tree / 'init').chmod(0o755)
    return tree


def build_ui(init):
    tree = WORK / 'initramfs-ui'
    copy_tree(WORK / 'rootfs', tree)
    (tree / 'etc/ld.so.preload').unlink(missing_ok=True)

    # The /usr filesystem replaces the minimal one in the root filesystem.
    shutil.rmtree(tree / 'usr', ignore_errors=True)
    copy_tree(WORK / 'usr', tree / 'usr')

    # The boot partition also carries the firmware blobs the application loads.
    system = tree / 'system'
    system.mkdir(parents=True, exist_ok=True)
    for entry in sorted((WORK / 'boot').iterdir()):
        if entry.name in BOOT_ONLY:
            continue
        if entry.is_dir():
            copy_tree(entry, system / entry.name)
        else:
            copy_file(entry, system / entry.name)

    copy_tree(WORK / 'setting', tree / 'setting')
    copy_tree(WORK / 'tmp', tree / 'tmp')
    backup = WORK / 'setting/Backup.bin'
    if backup.is_file():
        copy_file(backup, tree / 'setting/Backup.bak')

    # The application init loads this module; without it the UI cannot start.
    module = WORK / 'modules/dma330-stub/dma330_stub.ko'
    if module.is_file():
        copy_file(module, tree / 'usr/kmod/dma330_stub.ko')
    else:
        print(f'  warning: {module.relative_to(ROOT)} is missing; build it as shown in docs/setup.md\n'
              '           ./start-zve10-ui.sh will fail to start the application without it',
              file=sys.stderr)

    create_device_nodes(tree)
    copy_file(init, tree / 'init')
    (tree / 'init').chmod(0o755)
    return tree


def pack(tree, archive):
    listing = subprocess.check_output(['find', '.', '-print0'], cwd=tree)
    temporary = archive.with_suffix(archive.suffix + '.part')
    try:
        with temporary.open('wb') as out:
            subprocess.run(['cpio', '--null', '-o', '-H', 'newc', '--quiet', '--owner=0:0'],
                           input=listing, cwd=tree, stdout=out, check=True)
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive.stat().st_size


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--skip-cpio', action='store_true',
                        help='build the trees without packing work/camera.cpio')
    args = parser.parse_args()

    for command in ('cpio', 'find'):
        if not shutil.which(command):
            sys.exit(f'missing required command: {command}')
    need(WORK / 'rootfs', 'run scripts/prepare-firmware.py first')
    need(WORK / 'usr', 'run scripts/prepare-firmware.py first')
    need(WORK / 'boot', 'run scripts/prepare-firmware.py first')
    need(WORK / 'setting/Backup.bin', 'run scripts/prepare-firmware.py first')
    need(WORK / 'tmp', 'run scripts/prepare-firmware.py first')
    for name in ('initramfs-camera', 'initramfs-ui'):
        if (WORK / name).exists():
            sys.exit(f'work/{name} already exists; keep or rename it before preparing a fresh tree')
    if os.geteuid() != 0:
        sys.exit('device nodes need a saved fakeroot session; run:\n'
                 '  fakeroot -s work/fakeroot.state python3 scripts/prepare-initramfs.py')

    print('== 1/3 compile the shell init')
    shell_init = compile_shell_init(DEFAULT_CROSS, WORK / 'init-shell')
    print(f'  {shell_init.relative_to(ROOT)}')

    print('== 2/3 build the initramfs trees')
    print(f'  {build_camera(shell_init).relative_to(ROOT)}')
    print(f'  {build_ui(ROOT / "source/initramfs/init-ui.sh").relative_to(ROOT)}')

    if not args.skip_cpio:
        print('== 3/3 pack work/camera.cpio')
        size = pack(WORK / 'initramfs-camera', WORK / 'camera.cpio')
        print(f'  camera.cpio ({size} bytes)')

    print('\nnext: build the kernel with this camera.cpio, then run ./start-zve10.sh')


if __name__ == '__main__':
    main()
