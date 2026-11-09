"""Append one UTF-8 record to the original mode-0 UXC string bank."""
import struct


def append_title(data, resource, text):
    if len(data) < 16 or data[:4] != b'uxc\x07' or data[8] != 8:
        raise ValueError('Expected a mode-0 UXC bank with an 8-byte table prefix')
    header = struct.unpack_from('<I', data, 12)[0]
    count = header & 0x1fff
    namespace = struct.unpack_from('<H', data, 10)[0]
    if count >= 0x1fff or resource != 0x02000000 | (namespace << 13) | count:
        raise ValueError('New resource must be the next unused bank index')
    body = 16 + ((header >> 11) & 0x7ffc)
    if body < 16 + count * 2 or body > len(data) or len(data) % 4:
        raise ValueError('Invalid original bank table/body boundary')
    original = data[body:]
    if len(original) // 4 >= 0xffff:
        raise ValueError('Appended resource exceeds the mode-0 index range')
    encoded = text.encode('utf-8')
    if not encoded or b'\0' in encoded or len(encoded) > 256:
        raise ValueError('Invalid owned title')
    new_table_size = ((count + 1) * 2 + 3) & ~3
    new_header = (header & ~0x03ffffff) | ((new_table_size // 4) << 13) | (count + 1)
    table = data[16:16 + count * 2] + struct.pack('<H', len(original) // 4)
    table += bytes(new_table_size - len(table))
    record = struct.pack('<I', 0x1e000000 | (resource & 0xffffff)) + encoded + b'\0'
    record += bytes(-len(record) % 4)
    return data[:12] + struct.pack('<I', new_header) + table + original + record
