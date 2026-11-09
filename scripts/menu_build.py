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
ORIGINAL_IMDB_SHA = '69778dddf4069c3f92b3cd266bdfb821a31d311422e5e57e06196df696938c21'
NOLIRO_IMDB_SHA = 'd43a46ba57d7e364e691d5468d79c99b5eca9709a314b28ead9a6381a064eefa'
IM_ELF_SHA = '3fd399b62b468c0302b370362378a3719df6b7d68ff9f6e1c09312a84beeabbf'
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


def verify_library_versions(path, providers):
    elf = ELFFile(BytesIO(Path(path).read_bytes()))
    section = elf.get_section_by_name('.gnu.version_r')
    required = {}
    if section is not None:
        for version, auxiliaries in section.iter_versions():
            names = {item.name for item in auxiliaries}
            missing = names - providers.get(version.name, set())
            if missing:
                raise ValueError('Guest library version unavailable: ' + version.name + ': ' + ', '.join(sorted(missing)))
            required[version.name] = sorted(names)
    return required


def verify_base_archive(path, title_output=None, guest_versions=None, originals=None):
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
        if guest_versions is not None and name.startswith('lib/') and raw[data:data + 4] == b'\x7fELF':
            elf = ELFFile(BytesIO(raw[data:end]))
            dynamic = elf.get_section_by_name('.dynamic')
            versions = elf.get_section_by_name('.gnu.version_d')
            if dynamic is not None and versions is not None:
                for tag in dynamic.iter_tags():
                    if tag.entry.d_tag == 'DT_SONAME':
                        guest_versions[tag.soname] = {item.name for _, entries in versions.iter_versions() for item in entries}
                        break
        if name in {f'usr/lib/{key}' for key in ELFS}:
            found[name] = sha256(raw[data:end]).hexdigest()
        if originals is not None and name == 'usr/bin/im.elf':
            originals[name] = raw[data:end]
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


def build(zroot, donor, out, start_page='menu', test_pattern=False, shoot_view=False, capture_table_model=False, full_services=False):
    zroot, out = Path(zroot).resolve(), Path(out).resolve()
    donor = Path(donor).resolve() if donor is not None else None
    if out.exists():
        raise ValueError('Candidate output directory must be new')
    out.mkdir(parents=True)
    base = zroot / 'work/ui.cpio'
    guest_versions, originals = {}, {}
    archive_members = verify_base_archive(base, guest_versions=guest_versions,
                                          originals=originals if capture_table_model else None)
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
        hooks += [('base_main', 'libObj.so', 0x13bc80), ('model_query', 'libObj.so', 0x140ef0),
                  ('request_model', 'libObj.so', 0x139b88), ('model_event', 'libObj.so', 0x8a9f84),
                  ('media_main', 'libObj.so', 0x633560), ('media_scan', 'libObj.so', 0x6341a8),
                  ('media_policy', 'libObj.so', 0x634350), ('media_batch', 'libObj.so', 0x3c74b6),
                  ('content_create', 'libObj.so', 0x8f41d8), ('media_config', 'libObj.so', 0x1712f2),
                  ('manager_init', 'libObj.so', 0x8d0c76)]
    if capture_table_model:
        hooks += [('remote_sinks', 'libObj.so', 0x39f63e), ('remote_config', 'libObj.so', 0x395f40),
                  ('remote_infra', 'libObj.so', 0x3a2a60), ('remote_module', 'libObj.so', 0x3a1c90),
                  ('im_load', 'im.elf', 0xb7dc)]
    if donor is not None:
        hooks += [('init', 'CautionConfig.so', 0xb8dffa),
                  ('populate', 'viewUnified2.so', 0x3014f0),
                  ('row', 'viewUnified2.so', 0x862130)]
    for name, library, address in hooks:
        raw = originals['usr/bin/im.elf'] if library == 'im.elf' else (zroot / 'work/usr/lib' / library).read_bytes()
        if sha256(raw).hexdigest() != (IM_ELF_SHA if library == 'im.elf' else ELFS[library]):
            raise ValueError('Original module differs: ' + library)
        prologue = va_bytes(raw, address, 12)
        instructions = list(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(prologue, address))
        if sum(i.size for i in instructions) != 12 or any('pc' in i.op_str or i.mnemonic.startswith(('b', 'cb', 'it')) for i in instructions):
            raise ValueError('Native trampoline would relocate unsupported instructions')
        pins.append(f'static const unsigned char ne_pin_{name}[12] = {{' + ','.join(str(x) for x in prologue) + '};\n')
    if shoot_view:
        raw = (zroot / 'work/usr/lib/viewUnified2.so').read_bytes()
        if sha256(raw).hexdigest() != ELFS['viewUnified2.so']:
            raise ValueError('Original view module differs')
        original = va_bytes(raw, 0x41a794, 36)
        boot_pair = va_bytes(raw, 0x8f9474, 8)
        if boot_pair != b'\xc3\x00\x00\x00\x03\x00\x00\x00':
            raise ValueError('Original boot shooting view/option pair differs')
        pins.append('static const unsigned char ne_pin_shoot_open[36] = {' + ','.join(str(x) for x in original) + '};\n')
        pins.append('static const unsigned char ne_pin_shoot_boot_pair[8] = {' + ','.join(str(x) for x in boot_pair) + '};\n')
        boot_open = va_bytes(raw, 0x414350, 32)
        pins.append('static const unsigned char ne_pin_shoot_boot_open[32] = {' + ','.join(str(x) for x in boot_open) + '};\n')
    if start_page == 'shoot':
        raw = (zroot / 'work/usr/lib/libObj.so').read_bytes()
        elf = ELFFile(BytesIO(raw))
        observed_slots = [(0x13c2c18, 0x8e3711, 0x907aa9), (0x13c3258, 0x8f3591, 0x90dc99),
                          (0x13c3330, 0x8f3591, 0x91a733)]
        if capture_table_model:
            observed_slots.extend(((0x13a7530, 0x345421, 0x344d31),
                                   (0x13aa890, 0x398a3d, 0x398777)))
        for table, target, start in observed_slots:
            address = table + 0x38
            if va_bytes(raw, address, 8) != target.to_bytes(4, 'little') + start.to_bytes(4, 'little') or not any(
                    segment['p_type'] == 'PT_LOAD' and segment['p_flags'] & 2 and
                    segment['p_vaddr'] <= address and address + 8 <= segment['p_vaddr'] + segment['p_memsz']
                    for segment in elf.iter_segments()):
                raise ValueError('Original writable content processor slot differs')
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
    code = replace_once(code, '    uintptr_t result = original_draw(a, b, c, d);',
                        '    uintptr_t result = original_draw(a, b, c, d);\n'
                        '    if (raster_failed) record("NE_ERROR phase=cpu_raster_failure", raster_failed);')
    code = replace_once(code, '            record("native.menu.views.base", views_base);',
                        '            record("native.menu.views.base", views_base);\n            native_entry_modules(handle);')
    code = replace_once(code, '    int result = ui_present_copy(dst.pixels,span,src.pixels,span,p);',
                        '    int result = ui_present_copy(dst.pixels,span,src.pixels,span,p);\n'
                        '    if (!result) result = native_entry_present(dst.pixels,span,ui_u32(p + 4),(uintptr_t)__builtin_return_address(0));')
    if start_page == 'shoot':
        code = replace_once(code,
            '    if (!ui_surface(p, &span) && !map_surface(ui_u32(p), span, &m)) {',
            '    if (!ne_tiled_fill(p, mode, (uintptr_t)__builtin_return_address(0))) status = 0;\n'
            '    else if (!ui_surface(p, &span) && !map_surface(ui_u32(p), span, &m)) {')
        code = replace_once(code,
            '    if (status) { ++raster_failed; record("DMP.fill.UNSUPPORTED", raster_failed); return (uintptr_t)status; }',
'''    if (status) {
        uintptr_t fill_caller = (uintptr_t)__builtin_return_address(0) & ~(uintptr_t)1;
        record("DMP.fill.caller_offset", fill_caller - object_base);
        if (fill_caller == object_base + 0x6837d0 && p) {
            uintptr_t bitmap = ui_u32(p + 48);
            record("DMP.fill.bitmap", bitmap);
            if (bitmap >= 4096 && bitmap <= UINT32_MAX - 48)
                dump_params("DMP.fill.bitmap_fields", (void *)bitmap, 48);
        }
        ++raster_failed; record("DMP.fill.UNSUPPORTED", raster_failed); return (uintptr_t)status;
    }''')
        code = replace_once(code, '    return native_send(queue, message);',
'''    if (queue == 0x4015e && message && native_size) {
        int length = native_size(message);
        ne_line("NE_CAPTURE_TABLE_SIZE {\\"queue\\":%u,\\"length\\":%d,\\"tid\\":%ld}\\n", queue, length, syscall(224));
        if (length >= 24 && length <= 64) {
            ne_line("NE_CAPTURE_TABLE_SEND {\\"queue\\":%u,\\"length\\":%d,\\"tid\\":%ld,"
                    "\\"words\\":[%u,%u,%u,%u,%u,%u]}\\n", queue, length, syscall(224),
                    ui_u32(message), ui_u32((unsigned char *)message+4), ui_u32((unsigned char *)message+8),
                    ui_u32((unsigned char *)message+12), ui_u32((unsigned char *)message+16), ui_u32((unsigned char *)message+20));
        }
    }
#if NE_CAPTURE_TABLE_MODEL
    if (queue == 0x4015e) return ne_capture_table_model_send(queue, message);
#endif
    return native_send(queue, message);''')
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
    if capture_table_model:
        code = replace_once(code, 'int osal_wai_sem_tmo(uint32_t id, uint32_t timeout)\n{',
                            'int osal_wai_sem_tmo(uint32_t id, uint32_t timeout)\n{\n    int incoming_errno = errno;')
        code = replace_once(code,
            '    int result = native_wait(id, timeout);\n    if (main) record("thread.osal_sem.return", result);\n    return result;',
'''    uintptr_t im_caller = (uintptr_t)__builtin_return_address(0) & ~(uintptr_t)1;
    int im_trace = im_caller >= 0xb7dc && im_caller < 0xb8de;
    if (im_trace) ne_line("NE_IM_LOCK {\\"edge\\":\\"enter\\",\\"id\\":%u,\\"timeout\\":%u,\\"caller\\":%lu,\\"tid\\":%ld}\\n", id, timeout, (unsigned long)im_caller, syscall(224));
    errno = incoming_errno;
    int result = native_wait(id, timeout), original_errno = errno;
    if (main) record("thread.osal_sem.return", result);
    if (im_trace) ne_line("NE_IM_LOCK {\\"edge\\":\\"return\\",\\"id\\":%u,\\"result\\":%d,\\"tid\\":%ld}\\n", id, result, syscall(224));
    errno = original_errno;
    return result;''')
        code = replace_once(code, '    void *handle = native_dlopen(path, flags);',
'''    int remote_load = path && strstr(path, "libInfraRemote.so");
    int incoming_errno = errno;
    if (remote_load) ne_line("NE_IM_DLOPEN {\\"edge\\":\\"enter\\",\\"tid\\":%ld}\\n", syscall(224));
    errno = incoming_errno;
    void *handle = native_dlopen(path, flags);
    int original_errno = errno;
    if (remote_load) ne_line("NE_IM_DLOPEN {\\"edge\\":\\"return\\",\\"loaded\\":%s,\\"tid\\":%ld}\\n", handle ? "true" : "false", syscall(224));
    errno = original_errno;''')
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
               f'-DNE_TEST_PATTERN={int(test_pattern)}',
               f'-DNE_SHOOT_VIEW={int(shoot_view)}',
               f'-DNE_SHOOT_REQ_ON_DEMAND={int(full_services)}',
               f'-DNE_CAPTURE_TABLE_MODEL={int(capture_table_model)}',
               '-I', str(out), '-I', str(MENU_SOURCE), '-o', str(library),
               str(out / 'observer-derived.c')]
    if donor is not None:
        command.append(str(MENU_SOURCE / 'menu_shell.c'))
    command += ['-ldl', '-lpthread', '-lrt']
    result = subprocess.run(command, capture_output=True, text=True)
    (out / 'build.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    required_versions = verify_library_versions(library, guest_versions)
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
    if full_services:
        original_imdb = zroot / 'work/usr/lib/libIMDB.so'
        if digest(original_imdb) != ORIGINAL_IMDB_SHA:
            raise ValueError('Original libIMDB.so identity differs')
        # Full-service table restores every original service for the qemu
        # target, but disables the LIRO/av-cam entry: its kernel task never
        # reports ready without the imaging ASIC (A7C2 complete-boot lesson).
        import hashlib
        raw = bytearray(original_imdb.read_bytes())
        elf = ELFFile(BytesIO(bytes(raw)))
        symbols = {s.name: s for s in elf.get_section_by_name('.dynsym').iter_symbols()}
        imdb_base = symbols['imdb_raw']['st_value']
        def entry_offset(address):
            for segment in elf.iter_segments():
                if segment['p_type'] == 'PT_LOAD' and segment['p_vaddr'] <= address < segment['p_vaddr'] + segment['p_filesz']:
                    return segment['p_offset'] + address - segment['p_vaddr']
            raise ValueError('IMDB entry address unmapped')
        def entry_string(address):
            start = entry_offset(address)
            return bytes(raw[start:raw.index(b'\0', start)]).decode()
        patched = 0
        for index in range(300):
            offset = entry_offset(imdb_base + 0x84 + index * 0x2c)
            if int.from_bytes(raw[offset:offset + 4], 'little') == 40:
                break
            name = entry_string(int.from_bytes(raw[offset + 16:offset + 20], 'little'))
            if name == '/usr/kmod/liro.ko':
                field = offset + 8
                targets = int.from_bytes(raw[field:field + 4], 'little')
                raw[field:field + 4] = (targets & ~2).to_bytes(4, 'little')
                patched += 1
        if patched != 1:
            raise ValueError('Expected exactly one liro.ko IMDB entry')
        patched_sha = hashlib.sha256(bytes(raw)).hexdigest()
        if patched_sha == ORIGINAL_IMDB_SHA or patched_sha != NOLIRO_IMDB_SHA:
            raise ValueError('liro.ko IMDB patch result differs from pinned expectation')
        (out / 'libIMDB-original.so').write_bytes(bytes(raw))
        spec += 'file /usr/lib/libIMDB.so libIMDB-original.so 0755 0 0\n'
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
               'guest_version_requirements': required_versions,
               'capture_table_model': capture_table_model,
               'full_services': full_services,
               'mode': 'a7c2-menu' if donor is not None else 'original',
               'resource_header_sha256': resource_manifest['generated_header_sha256'] if resource_manifest else None,
               'input_model': 'original-native-function-event; physical panel mapping unverified'}
    (out / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt
