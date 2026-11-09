#!/usr/bin/env python3
"""Import the pinned A7C2 2.01 menu-resource ZIP into a new directory.

Every member is checked against a pinned size and SHA-256 here. The manifest
inside the archive is only compared by name, never trusted for verification,
and nothing from the archive is executed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

ARCHIVE_PREFIX = 'a7c2-menu-resources-2.01-v1/'
MAX_ENTRIES = 32
MAX_BYTES = 128 << 20
CHUNK = 1 << 20

# Paths relative to a7c2-root; both decoder sources sit beside that root.
RESOURCES = {
    'usr/lib/appFw.so': (99960744, '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'),
    'usr/share/app/image_02_32_IPSX.uxc': (9392312, '1a07a804dd2120fbb2aa366a4d35253e2fe63be7c6dde19a42920250df9d0c71'),
    'usr/share/app/Sony_DI_Icons.ttf': (622344, 'f4957fda675cad6c118c91297ed53828fbe4ef0ea28bc50ae2db3458bc5341c2'),
    'usr/share/app/UniversOTS-SJ_wIcon.ltt': (611416, 'ea39c41ceab7b3a2ac0c966482876fbb692af6f5af50e7766c9f447516109b2a'),
    'simulation/language-fonts/MYingHeiC-GB18030-SJ_wIcon.ltt':
        (2054740, 'a8afccc2e226d5a519f3698796c2a76a0ad6e163f7e5fc9e35d5e89d58db3276'),
    'usr/share/app/string_simplifiedchinese_horizontal.uxc':
        (100480, 'f136388b71e9431313002aee23f9c972b56e92602123b76b4786e0d3d872fb33'),
    'usr/share/app/string_simplifiedchinese_g.uxc': (37948, '7d719ac81928947c9980e4faed38f8c7d211c0a7ee794e90425c508b9a24c170'),
    'usr/share/app/style_cmn.uxc': (2096, '8811cbec2699757b94b3994ff128ac1508bdcacb9dbe34b094b9c50eb98bc5fa'),
    'usr/share/app/lang_cmn.uxc': (1048, '29d40af5c87960629f08addfa2d0f80d0a27490a52672848a5a622f183019337'),
    'usr/share/app/color_cmn.uxc': (684, 'e52bb5a3e551a2a3f6dfddd1dc95b7c27d03cf6e40449a58157297a538c3a667'),
}
DECODERS = {
    'sony-lz77.c': (3687, 'cad2ac49979f08dd93cf7bd498ef66691dce35b924eccf5986eda03824328bbf'),
    'sony-lz77.h': (231, 'd11d5730a66867e564aeccc3020e4e6fa9ba63eda50885d73da47273bd9606ab'),
}
METADATA = ('README.md', 'RESOURCE-MANIFEST.json', 'SHA256SUMS')
ALLOWED = {**{'a7c2-root/' + name: pin for name, pin in RESOURCES.items()}, **DECODERS}


def _verify(path, size, digest):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != size: raise ValueError(f'Unverified pinned file: {path}')
    sha = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(CHUNK):
            sha.update(chunk)
    if sha.hexdigest() != digest:
        raise ValueError(f'Unverified pinned file: {path}')


def validate_root(root):
    """Check a ready a7c2-root tree: regular files only, pinned sizes/hashes."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir(): raise ValueError(f'Not a directory: {root}')
    found = {}
    for directory, names, files in os.walk(root):
        for name in names:
            if (Path(directory) / name).is_symlink(): raise ValueError(f'Symlink in resource tree: {name}')
        for name in files:
            path = Path(directory) / name
            if not stat.S_ISREG(path.lstat().st_mode): raise ValueError(f'Not a regular file: {path}')
            found[path.relative_to(root).as_posix()] = path
    if set(found) != set(RESOURCES):
        raise ValueError(f'Resource tree mismatch: missing {sorted(set(RESOURCES) - set(found))}, '
                         f'extra {sorted(set(found) - set(RESOURCES))}')
    for relative, (size, digest) in RESOURCES.items():
        _verify(found[relative], size, digest)
    for name, (size, digest) in DECODERS.items():
        if not root.parent.joinpath(name).exists():
            raise ValueError(f'Missing pinned file: {name}')
        _verify(root.parent / name, size, digest)
    return root


def _plan(archive):
    """Map archive-relative names to members after all structural guards."""
    entries = archive.infolist()
    if len(entries) > MAX_ENTRIES:
        raise ValueError(f'Too many archive entries: {len(entries)}')
    if sum(entry.file_size for entry in entries) > MAX_BYTES:
        raise ValueError('Archive expands beyond the size limit')
    allowed = set(ALLOWED) | set(METADATA)
    plan = {}
    for entry in entries:
        name = entry.filename
        if entry.flag_bits & 0x1:
            raise ValueError(f'Encrypted archive member: {name!r}')
        if entry.is_dir() or not name.startswith(ARCHIVE_PREFIX):
            raise ValueError(f'Unsafe archive member: {name!r}')
        relative = name[len(ARCHIVE_PREFIX):]
        if (not relative or relative.startswith('/') or '\\' in relative or ':' in relative
                or any(ord(character) < 0x20 or ord(character) == 0x7f for character in relative)
                or posixpath.normpath(relative) != relative):
            raise ValueError(f'Unsafe archive member: {name!r}')
        if relative not in allowed:
            raise ValueError(f'Archive member outside the whitelist: {name!r}')
        mode = entry.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind == stat.S_IFLNK or (kind and kind != stat.S_IFREG):
            raise ValueError(f'Not a regular archive member: {name!r}')
        known = ALLOWED.get(relative)
        if known and entry.file_size != known[0]:
            raise ValueError(f'Archive member size differs: {name!r}')
        if relative in plan:
            raise ValueError(f'Duplicate archive member: {name!r}')
        plan[relative] = entry
    missing = set(ALLOWED) - set(plan)
    if missing:
        raise ValueError(f'Missing archive members: {sorted(missing)}')
    return plan


def _extract(archive, plan, staging):
    for relative, entry in plan.items():
        target = Path(staging) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256()
        total = 0
        with archive.open(entry) as source, target.open('xb') as sink:
            while chunk := source.read(CHUNK):
                total += len(chunk)
                if total > entry.file_size:
                    raise ValueError(f'Oversized archive member: {entry.filename}')
                sha.update(chunk)
                sink.write(chunk)
        known = ALLOWED.get(relative)
        if total != entry.file_size or (known and sha.hexdigest() != known[1]):
            raise ValueError(f'Unverified archive member: {entry.filename}')


def prepare_resources(bundle, destination):
    """Import the resource bundle into a new destination; return destination/a7c2-root."""
    bundle, destination = Path(bundle), Path(destination)
    if destination.is_symlink() or destination.exists():
        raise ValueError(f'Destination must not exist: {destination}')
    if not destination.parent.is_dir():
        raise ValueError(f'Destination parent is not a directory: {destination.parent}')
    if bundle.is_symlink() or not bundle.is_file():
        raise ValueError(f'Bundle is not a regular file: {bundle}')
    with zipfile.ZipFile(bundle) as archive:
        plan = _plan(archive)
        staging = Path(tempfile.mkdtemp(prefix='.a7c2-resources-', dir=destination.parent))
        try:
            _extract(archive, plan, staging)
            validate_root(staging / 'a7c2-root')
            if destination.exists():
                raise ValueError(f'Destination appeared during import: {destination}')
            os.rename(staging, destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return destination / 'a7c2-root'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--bundle', type=Path, required=True,
                        help='a7c2-menu-resources-2.01-v1.zip')
    parser.add_argument('--destination', type=Path, required=True,
                        help='new directory holding a7c2-root and the decoder sources')
    args = parser.parse_args(argv)
    try:
        root = prepare_resources(args.bundle, args.destination)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f'menu-resources: {error}', file=sys.stderr)
        return 1
    print(root)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
