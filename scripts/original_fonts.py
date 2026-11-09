"""Read-only loader for the original A7C2 menu fonts (no host-font fallback).

Each .ltt is an "LTT\\n" container holding concatenated SFNT faces; the face
byte range must be sliced out before Pillow/FreeType can open it, because SFNT
table offsets are relative to the face start.
"""

from __future__ import annotations

import hashlib
import io
import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

SFNT_VERSION = 0x00010000
MAX_SIZE = 128


class FontAssetError(RuntimeError):
    """Rejected asset: bad guard, bad SFNT structure or unexpected family."""


@dataclass(frozen=True)
class FontSpec:
    relpath: str
    size: int
    sha256: str
    sfnt_offset: int
    family: str


FONTS = {
    "univers": FontSpec(
        relpath="usr/share/app/UniversOTS-SJ_wIcon.ltt",
        size=611416,
        sha256="ea39c41ceab7b3a2ac0c966482876fbb692af6f5af50e7766c9f447516109b2a",
        sfnt_offset=53808,
        family="Univers OTS-SJ",
    ),
    "myinghei": FontSpec(
        relpath="simulation/language-fonts/MYingHeiC-GB18030-SJ_wIcon.ltt",
        size=2054740,
        sha256="a8afccc2e226d5a519f3698796c2a76a0ad6e163f7e5fc9e35d5e89d58db3276",
        sfnt_offset=2984,
        family="MYingHeiC-GB18030-SJ",
    ),
    "icons": FontSpec(
        relpath="usr/share/app/Sony_DI_Icons.ttf",
        size=622344,
        sha256="f4957fda675cad6c118c91297ed53828fbe4ef0ea28bc50ae2db3458bc5341c2",
        sfnt_offset=0,
        family="Sony_DI_Icons",
    ),
}


def _spec(kind: str) -> FontSpec:
    try:
        return FONTS[kind]
    except KeyError:
        raise FontAssetError(f"unknown font kind: {kind!r}") from None


def _guarded_bytes(root: Path, kind: str) -> tuple[FontSpec, Path, bytes]:
    spec = _spec(kind)
    path = Path(root) / spec.relpath
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FontAssetError(f"cannot read {kind} at {path}: {exc}") from None
    if len(data) != spec.size:
        raise FontAssetError(f"{kind}: size {len(data)} != {spec.size}")
    if hashlib.sha256(data).hexdigest() != spec.sha256:
        raise FontAssetError(f"{kind}: sha256 mismatch at {path}")
    return spec, path, data


def extract_sfnt(data: bytes, offset: int) -> bytes:
    """Return the exact face bytes (4-byte padded table span) at `offset`."""
    if offset < 0 or offset >= len(data):
        raise FontAssetError(f"sfnt offset {offset} outside {len(data)} bytes")
    if len(data) - offset < 12:
        raise FontAssetError("truncated sfnt header")
    version, num_tables = struct.unpack(">IH", data[offset : offset + 6])
    if version != SFNT_VERSION:
        raise FontAssetError(f"unexpected sfnt version 0x{version:08x}")
    if num_tables == 0:
        raise FontAssetError("empty table directory")
    dir_end = offset + 12 + 16 * num_tables
    if dir_end > len(data):
        raise FontAssetError("truncated table directory")
    span = 0
    for index in range(num_tables):
        pos = offset + 12 + 16 * index
        table_offset, table_length = struct.unpack(">II", data[pos + 8 : pos + 16])
        if table_offset + table_length > len(data) - offset:
            raise FontAssetError(
                f"table {index} at {table_offset}+{table_length} exceeds face data"
            )
        span = max(span, table_offset + table_length)
    span = (span + 3) & ~3
    if offset + span > len(data):
        raise FontAssetError(f"face span {span} exceeds {len(data) - offset} bytes")
    return data[offset : offset + span]


def source_record(root: Path, kind: str) -> dict:
    """Guarded provenance for reporting; does not touch FreeType."""
    spec, path, data = _guarded_bytes(root, kind)
    face = extract_sfnt(data, spec.sfnt_offset)
    return {
        "kind": kind,
        "path": str(path),
        "sha256": spec.sha256,
        "size": spec.size,
        "sfnt_offset": spec.sfnt_offset,
        "sfnt_size": len(face),
        "family": spec.family,
    }


def load_font(root: Path, kind: str, size: int) -> ImageFont.FreeTypeFont:
    if isinstance(size, bool) or not isinstance(size, int):
        raise FontAssetError(f"size must be int, got {type(size).__name__}")
    if not 1 <= size <= MAX_SIZE:
        raise FontAssetError(f"size {size} outside 1..{MAX_SIZE}")
    spec, _path, data = _guarded_bytes(root, kind)
    face = extract_sfnt(data, spec.sfnt_offset)
    font = ImageFont.truetype(io.BytesIO(face), size)
    family = font.getname()[0]
    if family != spec.family:
        raise FontAssetError(f"{kind}: family {family!r} != {spec.family!r}")
    return font
