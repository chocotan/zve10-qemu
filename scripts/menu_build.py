"""Build a cold-start original-AP candidate without editing the baseline tree."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]
MENU_SOURCE = ROOT / 'source/menu'

BASE_CPIO_SHA = '57af0f87b348f09d939fd5bf08bbdae2440cc911dfc67dbc9af8cd2e9aec7dfa'
BASE_OBSERVER_SHA = '20fe5f88bbb8b7d104b1a85064b5bc72218739a8d36a5bdbd074a4f0fe49dcb1'
ELFS = {
    'libObj.so': 'cfdc59b94fa56116e9d99154ca03a2c1aaf6039dd272679b78b0b76e21c722ac',
    'viewUnified2.so': 'bdf0690fbeef898bba1114c5804e88fdb437b5e31598eac32df05925504f6e1a',
    'CautionConfig.so': '5ad8746a229da259fe00b297e8f897d682f7ae9a13393025b3d1c95a808e68d7',
}


def digest(path):
    with Path(path).open('rb') as stream:
        import hashlib
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Pinned source seam changed: {old[:70]!r}')
    return text.replace(old, new, 1)


def va_bytes(raw, address, size):
    elf = ELFFile(BytesIO(raw))
    if elf.elfclass != 32 or elf['e_machine'] != 'EM_ARM':
        raise ValueError('Expected pinned original ARM32 ELF')
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_vaddr'] <= address and address + size <= segment['p_vaddr'] + segment['p_filesz']:
            offset = segment['p_offset'] + address - segment['p_vaddr']
            return raw[offset:offset + size]
    raise ValueError('Native ABI address outside original file')


def verify_base_archive(path, title_output=None):
    # The source hash binds the complete archive; check critical effective members too.
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != BASE_CPIO_SHA:
        raise ValueError('Original UI cpio identity differs')
    found, offset, title_data = {}, 0, None
    while offset + 110 <= len(raw):
        if not raw[offset]:
            offset += 1
            continue
        if raw[offset:offset + 6] != b'070701':
            raise ValueError('Unexpected original newc chain')
        fields = [int(raw[offset + 6 + n * 8:offset + 14 + n * 8], 16) for n in range(13)]
        size, namesize = fields[6], fields[11]
        start = offset + 110
        if namesize < 1 or start + namesize > len(raw) or raw[start + namesize - 1]:
            raise ValueError('Bad original newc name')
        name = raw[start:start + namesize - 1].decode().removeprefix('./')
        data = (start + namesize + 3) & ~3
        end = data + size
        if end > len(raw):
            raise ValueError('Truncated original newc member')
        if name in {f'usr/lib/{key}' for key in ELFS}:
            found[name] = sha256(raw[data:end]).hexdigest()
        if title_output is not None and name == 'usr/share/app/string_japanese.uxc':
            title_data = raw[data:end]
        offset = (end + 3) & ~3
    for name, expected in ELFS.items():
        if found.get('usr/lib/' + name) != expected:
            raise ValueError('Original archive/module identity mismatch: ' + name)
    if title_output is not None:
        if title_data is None or sha256(title_data).hexdigest() != 'f7daf36401895a1da47eb7dba399903a66af71a0e913ae1dec9bab560baec1cd':
            raise ValueError('Original Japanese title bank identity differs')
        from menu_title import append_title
        title_output.write_bytes(append_title(title_data, 0x0204eafe, 'New Menu'))
    return found


def build(zroot, donor, out, start_page='menu'):
    zroot, out = Path(zroot).resolve(), Path(out).resolve()
    donor = Path(donor).resolve() if donor is not None else None
    if out.exists():
        raise ValueError('Candidate output directory must be new')
    out.mkdir(parents=True)
    base = zroot / 'work/ui.cpio'
    archive_members = verify_base_archive(base)
    resource_manifest = None
    if donor is not None:
        from original_assets import prepare
        resource_manifest = prepare(donor, out)
    source_dir = zroot / 'source/ui'
    if digest(source_dir / 'ui-observe.c') != BASE_OBSERVER_SHA:
        raise ValueError('Original observer source changed')
    sources = {p.name: p.read_bytes() for p in source_dir.glob('ui-*') if p.suffix in ('.h', '.c')}
    variant = MENU_SOURCE / ('a7c2' if donor is not None else '.')
    native = {p.name: p.read_bytes() for p in variant.glob('*') if p.suffix in ('.h', '.inc')}
    before = {'baseline/' + name: sha256(data).hexdigest() for name, data in sources.items()}
    before.update({'native/' + name: sha256(data).hexdigest() for name, data in native.items()})
    for name, data in native.items():
        (out / name).write_bytes(data)
    for name, data in sources.items():
        if name != 'ui-observe.c':
            (out / name).write_bytes(data)
    # Exact original module prologues must move whole, PC-independent instructions.
    pins = []
    hooks = [('main', 'viewUnified2.so', 0x2fccc0)]
    if start_page == 'shoot':
        hooks += [('base_main', 'libObj.so', 0x13bc80)]
    if donor is not None:
        hooks += [('init', 'CautionConfig.so', 0xb8dffa),
                  ('populate', 'viewUnified2.so', 0x3014f0),
                  ('row', 'viewUnified2.so', 0x862130)]
    for name, library, address in hooks:
        raw = (zroot / 'work/usr/lib' / library).read_bytes()
        if sha256(raw).hexdigest() != ELFS[library]:
            raise ValueError('Original module differs: ' + library)
        prologue = va_bytes(raw, address, 12)
        instructions = list(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(prologue, address))
        if sum(i.size for i in instructions) != 12 or any('pc' in i.op_str or i.mnemonic.startswith(('b', 'cb', 'it')) for i in instructions):
            raise ValueError('Native trampoline would relocate unsupported instructions')
        pins.append(f'static const unsigned char ne_pin_{name}[12] = {{' + ','.join(str(x) for x in prologue) + '};\n')
    (out / 'native_pins.h').write_text(''.join(pins))
    code = sources['ui-observe.c'].decode()
    code = replace_once(code, '#include "ui-lz77.h"', '#include <stdlib.h>\n#include "ui-lz77.h"\n#include <pthread.h>\n#include "native_entry.h"')
    code = replace_once(code,
        '__attribute__((naked)) int pthread_cond_wait(void *condition __attribute__((unused)), void *mutex __attribute__((unused)))',
        '__attribute__((naked)) int pthread_cond_wait(pthread_cond_t *condition __attribute__((unused)), pthread_mutex_t *mutex __attribute__((unused)))')
    if start_page == 'shoot':
        # Probe: let the AP decide its own start page instead of forcing the settings menu.
        code = replace_once(code, '    try_original_menu();\n    return result;',
                            '    if (getenv("NE_FORCE_MENU")) try_original_menu();\n    native_entry_after_draw();\n    return result;')
    else:
        code = replace_once(code, '    try_original_menu();\n    return result;',
                            '    try_original_menu();\n    native_entry_after_draw();\n    return result;')
    code = replace_once(code, '            record("native.menu.views.base", views_base);',
                        '            record("native.menu.views.base", views_base);\n            native_entry_modules(handle);')
    code = replace_once(code, '    int result = ui_present_copy(dst.pixels,span,src.pixels,span,p);',
                        '    int result = ui_present_copy(dst.pixels,span,src.pixels,span,p);\n'
                        '    if (!result) result = native_entry_present(dst.pixels,span,ui_u32(p + 4),(uintptr_t)__builtin_return_address(0));')
    if start_page == 'shoot':
        # Observe which queues/models the shooting UI asks for (derived copy only).
        code = replace_once(code, 'if (syscall(224) == ui_tid && output_messages++ < 32)',
                            'if (output_messages++ < 600)')
        # Identify which module blocks each wait (derived copy only).

        code = replace_once(code, '        record("thread.osal_sem.id", id);',
'''        record("thread.osal_sem.id", id);
        {
            Dl_info wait_info;
            uintptr_t wait_caller = (uintptr_t)__builtin_return_address(0);
            if (dladdr((void *)wait_caller, &wait_info) && wait_info.dli_fbase && wait_info.dli_fname) {
                char wait_note[192];
                int wait_len = snprintf(wait_note, sizeof wait_note,
                    "SEMWAIT pid=%d tid=%ld id=%#x module=%s off=%#lx\\n",
                    getpid(), syscall(224), id, wait_info.dli_fname,
                    (unsigned long)(wait_caller - (uintptr_t)wait_info.dli_fbase));
                if (wait_len > 0 && wait_len < (int)sizeof wait_note) write(2, wait_note, wait_len);
            }
        }''')
    code += '\n#include "' + ('native_entry.inc' if donor is not None else 'original.inc') + '"\n'
    (out / 'observer-derived.c').write_text(code)
    headless = sources['ui-headless.h'].decode()
    headless = replace_once(headless, 'if (native_glyph_images>=13 && !headless_retained.pixels',
                             'if (0 && native_glyph_images>=13 && !headless_retained.pixels')
    headless = replace_once(headless, '    const struct headless_snapshot *export =',
                             '    ne_transport_cache(copies,(unsigned)count,frame);\n    const struct headless_snapshot *export =')
    headless = replace_once(headless, '    UI_HEADLESS_FN(0x6fafb9, void (*)(void))();',
                             '    UI_HEADLESS_FN(0x6fafb9, void (*)(void))();\n    ne_transport_retired(frame);')
    (out / 'ui-headless.h').write_text(headless)
    font = sources['ui-font-probe.h'].decode()
    if donor is not None:
        font = replace_once(font, '    return original_string_id(a,b,c,d);',
                            '    if (b == NE_TITLE) return native_entry_title(a,b,c,d);\n    return original_string_id(a,b,c,d);')
    (out / 'ui-font-probe.h').write_text(font)
    compiler = zroot / 'work/armv7-eabihf--glibc--stable-2020.08-1/bin/arm-linux-gcc'
    library = out / 'libnativeentry.so'
    command = [str(compiler), '-shared', '-fPIC', '-O2', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
               f'-DNE_WITH_A7C2={int(donor is not None)}',
               f'-DNE_SHOOT_PROBE={int(start_page == "shoot")}',
               '-I', str(out), '-I', str(MENU_SOURCE), '-o', str(library),
               str(out / 'observer-derived.c')]
    if donor is not None:
        command.append(str(MENU_SOURCE / 'menu_shell.c'))
    command += ['-ldl', '-lpthread', '-lrt']
    result = subprocess.run(command, capture_output=True, text=True)
    (out / 'build.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    for prefix, directory in [('baseline', source_dir), ('native', variant)]:
        for key, expected in before.items():
            if key.startswith(prefix + '/') and digest(directory / key.split('/', 1)[1]) != expected:
                raise ValueError('Build input changed during compilation')
    init_source = (zroot / 'source/initramfs/init-ui.sh').read_text()
    init_source = replace_once(init_source, 'LD_PRELOAD=/usr/lib/libuiobserve.so', 'LD_PRELOAD=/usr/lib/libnativeentry.so')
    (out / 'init-native.sh').write_text(init_source)
    spec = ('dir /usr 0755 0 0\ndir /usr/lib 0755 0 0\n'
            'file /init init-native.sh 0755 0 0\n'
            'file /usr/lib/libnativeentry.so libnativeentry.so 0755 0 0\n')
    (out / 'overlay.spec').write_text(spec)
    with (out / 'overlay.cpio').open('wb') as stream:
        subprocess.run([str(zroot / 'work/kbuild-ui/usr/gen_init_cpio'), 'overlay.spec'], cwd=out, stdout=stream, check=True)
    runtime = out / 'native-ui.cpio'
    shutil.copyfile(base, runtime)
    with runtime.open('ab') as stream, (out / 'overlay.cpio').open('rb') as overlay:
        shutil.copyfileobj(overlay, stream)
    receipt = {'schema': 1, 'original_files_modified': False, 'guest_programs_executed': False,
               'base_cpio_sha256': BASE_CPIO_SHA, 'base_members': archive_members,
               'source_sha256': before, 'command': command, 'library_sha256': digest(library),
               'runtime_cpio_sha256': digest(runtime),
               'mode': 'a7c2-menu' if donor is not None else 'original',
               'resource_header_sha256': resource_manifest['generated_header_sha256'] if resource_manifest else None,
               'input_model': 'original-native-function-event; physical panel mapping unverified'}
    (out / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt
