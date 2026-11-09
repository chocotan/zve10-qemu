"""Build a private guest asset header from pinned A7C2 2.01 resources.

Only original sprites, original strings/fonts, palette entries and the original
44-widget layout are inputs. This module never renders a complete menu frame.
"""
import ctypes
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import struct
import subprocess
import tempfile
from PIL import Image, ImageDraw

from original_fonts import load_font, source_record

SPECS = {
    'usr/lib/appFw.so': '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
    'usr/share/app/image_02_32_IPSX.uxc': '1a07a804dd2120fbb2aa366a4d35253e2fe63be7c6dde19a42920250df9d0c71',
    'usr/share/app/color_cmn.uxc': 'e52bb5a3e551a2a3f6dfddd1dc95b7c27d03cf6e40449a58157297a538c3a667',
    'usr/share/app/style_cmn.uxc': '8811cbec2699757b94b3994ff128ac1508bdcacb9dbe34b094b9c50eb98bc5fa',
    'usr/share/app/lang_cmn.uxc': '29d40af5c87960629f08addfa2d0f80d0a27490a52672848a5a622f183019337',
    'usr/share/app/string_simplifiedchinese_g.uxc': '7d719ac81928947c9980e4faed38f8c7d211c0a7ee794e90425c508b9a24c170',
    'usr/share/app/string_simplifiedchinese_horizontal.uxc': 'f136388b71e9431313002aee23f9c972b56e92602123b76b4786e0d3d872fb33',
}
DECODER_SHA = 'cad2ac49979f08dd93cf7bd498ef66691dce35b924eccf5986eda03824328bbf'
NORMAL = [0x41e7, 0x41e5, 0x4209, 0x41dd, 0x41e1, 0x41eb, 0x41e9, 0x4205]
SELECTED = [value - 1 for value in NORMAL]
TITLE_IDS = [0x451, 0x92, 0x93, 0x90, 0x91, 0x8f, 0x60, 0x454]


def take(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError('Asset field outside its source')
    return data[offset:offset + size]


def u16(data, offset):
    return struct.unpack('<H', take(data, offset, 2))[0]


def u32(data, offset):
    return struct.unpack('<I', take(data, offset, 4))[0]


def lookup(data, table, index):
    header = u32(data, table + 4)
    count, mode, prefix = header & 0x1fff, data[table] & 3, data[table] & 0x7c
    body = table + prefix + ((header >> 11) & 0x7ffc)
    if not 0 <= index < count or prefix < 8 or body > len(data):
        raise ValueError('Unsupported resource table/index')
    if mode == 1:
        at = table + prefix + index * 4
        if at + 4 > body:
            raise ValueError('Resource index overlaps its body')
        relative = u32(data, at)
    elif mode in (0, 3):
        split = u16(data, table + 8) if mode == 3 else index
        slot = index if index <= split else split + (index - split) * 2
        at = table + prefix + slot * 2
        if at + 2 > body:
            raise ValueError('Resource index overlaps its body')
        value = u16(data, at)
        if value == 0xffff:
            raise ValueError('Missing original resource')
        if mode == 3 and value & 0x8000:
            if at + 4 > body:
                raise ValueError('Wide resource index overlaps body')
            relative = (((value & 0x7fff) << 16) | u16(data, at + 2)) * 4
        else:
            relative = value * 4
    else:
        raise ValueError('Unsupported resource table mode')
    offset = body + relative
    if relative == 0xffffffff or not body <= offset < len(data):
        raise ValueError('Missing or out-of-range original resource')
    return offset


def record(data, resource):
    if data[:4] not in (b'uxc\x07', b'uxd\x07'):
        raise ValueError('Wrong original resource container')
    if u16(data, 10) != ((resource >> 13) & 0x7ff):
        raise ValueError('Resource namespace mismatch')
    offset = lookup(data, 8, resource & 0x1fff)
    if u32(data, offset) & 0xffffff != resource & 0xffffff:
        raise ValueError('Original resource ID mismatch')
    return offset


def string(data, resource):
    offset = record(data, resource)
    if u32(data, offset) >> 24 != 0x1e:
        raise ValueError('Expected original UTF-8 resource')
    end = data.find(b'\0', offset + 4)
    if end < 0 or end - offset > 4096:
        raise ValueError('Unterminated original string')
    return data[offset + 4:end].decode('utf-8')


def elf_bytes(data, address, size):
    if data[:6] != b'\x7fELF\x02\x01' or u16(data, 18) != 183:
        raise ValueError('Expected original AArch64 ELF')
    phoff = struct.unpack('<Q', take(data, 32, 8))[0]
    entsize, count = struct.unpack('<HH', take(data, 54, 4))
    if entsize != 56 or count > 128:
        raise ValueError('Unexpected original ELF program headers')
    for index in range(count):
        kind, _, offset, va, _, filesz, _, _ = struct.unpack('<II6Q', take(data, phoff + index * entsize, 56))
        if kind == 1 and va <= address and address + size <= va + filesz:
            return take(data, offset + address - va, size)
    raise ValueError('Original layout VA not backed by ELF bytes')


def glyph_run(root, text, size):
    chars, x = [], 0.0
    top, bottom = 0, 0
    for char in text:
        kind = 'icons' if 0xe000 <= ord(char) <= 0xefff else ('univers' if ord(char) < 128 else 'myinghei')
        font = load_font(root, kind, size)
        bbox = font.getbbox(char, anchor='ls')
        top, bottom = min(top, bbox[1]), max(bottom, bbox[3])
        chars.append((x, char, font))
        x += font.getlength(char)
    width, height = max(1, math.ceil(x)), max(1, bottom - top)
    if width > 540 or height > 64:
        raise ValueError('Original text exceeds the bounded menu label surface')
    image = Image.new('L', (width, height))
    draw = ImageDraw.Draw(image)
    for x, char, font in chars:
        draw.text((x, -top), char, font=font, fill=255, anchor='ls')
    return width, height, image.tobytes()


def array(name, ctype, values):
    values = list(values)
    lines = [', '.join(str(value) for value in values[i:i + 20]) for i in range(0, len(values), 20)]
    return f'static const {ctype} {name}[{len(values)}] = {{\n' + ',\n'.join(lines) + '\n};\n'


def prepare(root, out):
    root, out = Path(root).resolve(), Path(out)
    inputs, sources = {}, {}
    for relative, expected in SPECS.items():
        data = (root / relative).read_bytes()
        if sha256(data).hexdigest() != expected:
            raise ValueError(f'Unverified original A7C2 resource: {relative}')
        sources[relative] = data
        inputs[relative] = {'size': len(data), 'sha256': expected}
    app = sources['usr/lib/appFw.so']
    layout = elf_bytes(app, 0x40339b0, 44 * 52)
    rows = [struct.unpack_from('<13I', layout, index * 52) for index in range(44)]
    if any(row[9] >> 16 != index for index, row in enumerate(rows)):
        raise ValueError('Original layout registration order differs')
    if tuple(struct.unpack('<4h', layout[3 * 52 + 40:3 * 52 + 48])) != (0, 43, 640, 384):
        raise ValueError('Original eight-tab menu geometry differs')
    cpp = ['#include <stdint.h>\nstruct a7_sprite {unsigned width,height; const uint16_t *pixels;};\n'
           'struct a7_text {unsigned width,height; const unsigned char *alpha;};\n']
    cpp.append('static const uint32_t a7_layout[44][13] = {\n' + ',\n'.join(
        '{' + ','.join(f'0x{word:08x}u' for word in row) + '}' for row in rows) + '\n};\n')
    manifest = {'source_files': inputs, 'layout': {'elf_va': '0x40339b0', 'count': 44, 'stride': 52,
                 'sha256': sha256(layout).hexdigest()}, 'sprites': [], 'texts': [],
                'original_ap_consumed': False, 'complete_frame_pre_rendered': False}
    colors = sources['usr/share/app/color_cmn.uxc']
    style = sources['usr/share/app/style_cmn.uxc']
    for name, data, resource, delta in [('background', colors, 0x0209402c, 4),
                                         ('header', colors, 0x02094000, 4),
                                         ('text', style, 0x0207a000, 12)]:
        offset = record(data, resource)
        rgba = take(data, offset + delta, 4)
        packed = sum((channel >> 4) << shift for channel, shift in zip(rgba, (12, 8, 4, 0)))
        cpp.append(f'static const uint16_t a7_{name}_color = 0x{packed:04x};\n')
    # Use the existing bounded Sony decoder, not a guessed interpretation of its stream.
    decoder = root.parent / 'sony-lz77.c'
    if sha256(decoder.read_bytes()).hexdigest() != DECODER_SHA:
        raise ValueError('Unverified Sony decoder source')
    manifest['decoder_sha256'] = DECODER_SHA
    with tempfile.TemporaryDirectory(prefix='a7c2-asset-decode-') as temp:
        library = Path(temp) / 'decode.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(decoder), '-o', str(library)], check=True)
        lib = ctypes.CDLL(str(library))
        lib.sony_lz77_decode.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
        images = sources['usr/share/app/image_02_32_IPSX.uxc']
        for variant, ids in [('normal', NORMAL), ('selected', SELECTED)]:
            declarations = []
            for index, low in enumerate(ids):
                resource = 0x02000000 | low
                offset = record(images, resource)
                width, height = u16(images, offset + 8), u16(images, offset + 10)
                if (width, height, u32(images, offset + 4)) != (54, 48, 0xc0000000):
                    raise ValueError('Original category sprite layout differs')
                size = u32(images, offset + 12)
                payload = take(images, offset + 4 + u32(images, offset + 16), size)
                stride = (width + 15) & ~15
                target = ctypes.create_string_buffer(stride * height * 2)
                source = ctypes.create_string_buffer(payload)
                if lib.sony_lz77_decode(source, len(payload), target, len(target)):
                    raise ValueError('Original category sprite could not be decoded')
                raw = target.raw
                pixels = [u16(raw, (y * stride + x) * 2) for y in range(height) for x in range(width)]
                name = f'a7_{variant}_{index}'
                cpp.append(array(name, 'uint16_t', pixels))
                declarations.append(f'{{{width},{height},{name}}}')
                manifest['sprites'].append({'variant': variant, 'category': index, 'resource_id': f'{resource:08x}',
                    'record_offset': offset, 'payload_sha256': sha256(payload).hexdigest(),
                    'decoded_sha256': sha256(raw).hexdigest(), 'width': width, 'height': height})
            cpp.append(f'static const struct a7_sprite a7_tab_{variant}[8] = {{' + ','.join(declarations) + '};\n')
    g = sources['usr/share/app/string_simplifiedchinese_g.uxc']
    horizontal = sources['usr/share/app/string_simplifiedchinese_horizontal.uxc']
    title_strings = [string(g, 0x02006000 | index) for index in TITLE_IDS]
    page_template = string(g, 0x02006432)
    if page_template != '${v1:2}/${v2}':
        raise ValueError('Original page formatter differs')
    footer = string(horizontal, 0x0200a2b1)
    if footer != '\ue80a关闭':
        raise ValueError('Original MENU-close label differs')
    header_style = record(style, 0x0207a029)
    footer_style = record(style, 0x0207a00f)
    header_size, footer_size = style[header_style + 6], style[footer_style + 6]
    declarations = []
    for index, text in enumerate(title_strings):
        w, h, alpha = glyph_run(root, text, header_size)
        name = f'a7_title_{index}'
        cpp.append(array(name, 'unsigned char', alpha))
        declarations.append(f'{{{w},{h},{name}}}')
        manifest['texts'].append({'role': 'title', 'category': index, 'resource_id': f'{0x02006000 | TITLE_IDS[index]:08x}',
                                 'text': text, 'pixel_size': header_size, 'alpha_sha256': sha256(alpha).hexdigest()})
    cpp.append('static const struct a7_text a7_titles[8] = {' + ','.join(declarations) + '};\n')
    # Owned row label for the ZV-E10 menu entry, rendered with the original font.
    w, h, alpha = glyph_run(root, 'New Menu', header_size)
    cpp.append(array('a7_owned_label_alpha', 'unsigned char', alpha))
    cpp.append(f'static const struct a7_text a7_owned_label = {{{w},{h},a7_owned_label_alpha}};\n')
    manifest['texts'].append({'role': 'owned-label', 'text': 'New Menu', 'pixel_size': header_size,
                             'alpha_sha256': sha256(alpha).hexdigest()})
    for role, text, size in [('page', page_template.replace('${v1:2}', ' 0').replace('${v2}', '0'), header_size),
                              ('footer', footer, footer_size)]:
        w, h, alpha = glyph_run(root, text, size)
        name = f'a7_{role}_alpha'
        cpp.append(array(name, 'unsigned char', alpha))
        cpp.append(f'static const struct a7_text a7_{role}_text = {{{w},{h},{name}}};\n')
        manifest['texts'].append({'role': role, 'resource_id': '02006432' if role == 'page' else '0200a2b1',
                                 'text': text, 'pixel_size': size, 'alpha_sha256': sha256(alpha).hexdigest()})
    manifest['fonts'] = [source_record(root, kind) for kind in ('univers', 'myinghei', 'icons')]
    header = ''.join(cpp).encode('ascii')
    (out / 'original_assets.h').write_bytes(header)
    manifest['generated_header_sha256'] = sha256(header).hexdigest()
    (out / 'resource-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest
