"""Small checks for the native patch boundary and host failure paths."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


class NativeBoundaryTests(unittest.TestCase):
    def test_real_jump_writer_alignment_and_cross_page_span(self):
        source = (ROOT / 'source/menu/native_entry.inc').read_text()
        hooks = (ROOT / 'source/menu/menu_hooks.inc').read_text()
        jump = hooks[hooks.index('static unsigned ne_jump('):hooks.index('\nstatic int ne_hook(')]
        start = hooks.index('    uintptr_t page = address &')
        span = hooks[start:hooks.index('    if (mprotect(', start)]
        program = '''#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
''' + jump + '\nstatic size_t span(uintptr_t address) {\n' + span + '''return protection_span; }
int main(void) {
    _Alignas(4096) unsigned char buffer[12288];
    const unsigned positions[] = {0,2,4,4090,4092,4094,4096,4098};
    for (unsigned i=0;i<sizeof positions/sizeof positions[0];++i) {
        memset(buffer,0xcc,sizeof buffer);
        unsigned char *where=buffer+positions[i];
        unsigned written=ne_jump(where,UINT32_C(0x12345679));
        uint16_t opcode[2]; memcpy(opcode,where,4);
        assert(opcode[0]==0xf8df && (opcode[1]&0xf000)==0xf000);
        uintptr_t literal=(((uintptr_t)where+4)&~(uintptr_t)3)+(opcode[1]&0xfff);
        assert(!(literal&3));
        uint32_t destination; memcpy(&destination,(void *)literal,4);
        assert(destination==UINT32_C(0x12345679));
        assert(written==((positions[i]&3)?10u:8u));
        if (positions[i]&3) { uint16_t nop;memcpy(&nop,where+4,2);assert(nop==0xbf00); }
        for (unsigned k=0;k<sizeof buffer;++k)
            if(k<positions[i] || k>=positions[i]+written) assert(buffer[k]==0xcc);
        uintptr_t first=(uintptr_t)where&~(uintptr_t)4095;
        assert((uintptr_t)where+written<=first+span((uintptr_t)where));
    }
    assert(span(0xb8dffa)==8192);
    assert(span(0x3014f0)==4096);
    puts("PASS actual jump writer: 8 placements, aligned literals, original cross-page entry");
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'check.c').write_text(program)
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', str(path / 'check.c'), '-o', str(path / 'check')], check=True)
            subprocess.run([str(path / 'check')], check=True)

    def test_protocol_uses_the_selected_uart_sink(self):
        source = (ROOT / 'source/menu/transport.inc').read_text()
        function = source[source.index('static int ne_transport_line('):source.index('\nstatic int ne_transport_coherent_locked(')]
        program = '''#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
static volatile int ne_transport_fd=-1;
''' + function + '''
int main(void) {
    int fds[2]; assert(!pipe(fds));
    assert(fcntl(fds[0],F_SETFL,O_NONBLOCK)>=0);
    ne_transport_fd=fds[1];
    assert(!ne_transport_line("NE_ACK %u\\n",17u));
    char bytes[64]={0}; ssize_t n=read(fds[0],bytes,sizeof bytes);
    assert(n==10 && !memcmp(bytes,"NE_ACK 17\\n",10));
    errno=0;assert(read(fds[0],bytes,sizeof bytes)==-1 && errno==EAGAIN);
    assert(!close(fds[1]) && !close(fds[0]));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'check.c').write_text(program)
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(path / 'check.c'), '-o', str(path / 'check')], check=True)
            subprocess.run([str(path / 'check')], check=True)

    def test_real_repeated_state_record_still_fails(self):
        import menu_run as run
        guest = object.__new__(run.NativeGuest)
        guest.capture_id, guest.timeout = 0, 3
        guest.send = lambda message: None
        guest.line = lambda deadline: b'NE_STATE {"capture_id":1}'
        with self.assertRaisesRegex(RuntimeError, 'Repeated native state record'):
            guest.capture()

    def test_owned_transaction_refuses_invalid_original_view_state(self):
        import menu_run as run
        guest = object.__new__(run.NativeGuest)
        guest.frames = [{'native_frame': 1}]
        guest.key = lambda name: 4
        guest.capture = lambda: ({'native_frame': 2, 'state': {'last_input': 4, 'view_state': 0xffffffff}}, None)
        with self.assertRaisesRegex(RuntimeError, 'Original view state changed'):
            guest.after_key('UP', True)

    def test_render_fingerprint_is_bound_to_the_current_category(self):
        source = (ROOT / 'source/menu/native_entry.inc').read_text()
        function = source[source.index('static uint64_t ne_overlay_hash('):source.index('\nstatic int ne_post_function(')]
        program = '''#include <assert.h>
#include <stdint.h>
#include <pthread.h>
static uint32_t ne_packed, ne_overlay_packed, ne_overlay_physical;
static uint64_t ne_overlay_fingerprint;
static pthread_mutex_t ne_present_mutex=PTHREAD_MUTEX_INITIALIZER;
''' + function + '''
int main(void) {
    ne_packed=ne_overlay_packed=0x107;ne_overlay_physical=0x22000000;
    ne_overlay_fingerprint=UINT64_C(0x123456789abcdef0);
    assert(ne_overlay_hash(0x22000000)==ne_overlay_fingerprint);
    ne_packed=0x106;assert(!ne_overlay_hash(0x22000000));
    ne_packed=0x107;assert(!ne_overlay_hash(0x22096000));
    ne_packed=0;assert(!ne_overlay_hash(0x22000000));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'check.c').write_text(program)
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread',
                            str(path / 'check.c'), '-o', str(path / 'check')], check=True)
            subprocess.run([str(path / 'check')], check=True)

    def test_empty_highlight_does_not_count_as_the_entry_title(self):
        import menu_run as run
        from PIL import Image
        for background in ((0,0,0), (255,136,0)):
            with self.assertRaisesRegex(RuntimeError, 'title pixels are missing'):
                run.require_entry_title(Image.new('RGB', (640,480), background))

    def test_actual_present_target_selects_the_current_buffer(self):
        source = (ROOT / 'source/menu/transport.inc').read_text()
        functions = source[source.index('static void ne_transport_fail_locked('):source.index('\nstatic void ne_transport_retired(')]
        program = '''#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <errno.h>
#define HEADLESS_BYTES 8
#ifndef NE_SHOOT_PROBE
#define NE_SHOOT_PROBE 0
#endif
struct headless_snapshot {unsigned char *pixels;uint64_t frame,fingerprint;uint32_t index,physical;};
static pthread_mutex_t ne_transport_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t ne_transport_cond=PTHREAD_COND_INITIALIZER;
static struct headless_snapshot ne_latest;
static uint64_t ne_cache_frame;
static unsigned ne_latest_valid,ne_overlay_captured;
static int ne_stopped,ne_error_number;
static const char *ne_error_phase;
static uint64_t headless_fingerprint(const void *p,size_t n){const unsigned char *s=p;uint64_t h=0;while(n--)h=h*33+*s++;return h;}
static uint64_t wanted;
static uint32_t overlay_physical;
static uint64_t ne_present_hash(uint32_t physical){return physical==22?wanted:0;}
static uint64_t ne_overlay_hash(uint32_t physical){return physical==overlay_physical?wanted:0;}
''' + functions + '''
int main(void){
    unsigned char old[8]={1,0,2,0,3,0,4,0},current[8]={5,0,6,0,7,0,8,0};
    struct headless_snapshot copies[2]={{old,1,0,0,11},{current,1,0,1,22}};
    wanted=headless_fingerprint(current,8);
    /* Overlay: the presented buffer matches, so its actual pixels are published. */
    overlay_physical=22;ne_transport_cache(copies,2,1);
    assert(ne_latest_valid && ne_latest.index==1 && ne_latest.physical==22 && ne_overlay_captured);
    assert(!memcmp(ne_latest.pixels,current,8));
    current[0]=9;assert(ne_latest.pixels[0]==5);
    /* Overlay: presented pixels differ from every captured buffer, so nothing is published. */
    ne_latest_valid=0;wanted^=1;copies[0].physical=copies[1].physical=22;
    copies[0].frame=copies[1].frame=2;
    ne_transport_cache(copies,2,2);assert(!ne_latest_valid && !ne_error_phase);
    /* Plain frame keeps the original selection rule instead of requiring a present match. */
    overlay_physical=0;wanted^=1;copies[0].physical=11;copies[1].physical=22;
    copies[0].frame=copies[1].frame=3;
    ne_transport_cache(copies,2,3);
    assert(ne_latest_valid && ne_latest.index==0 && !ne_overlay_captured);
    free(ne_latest.pixels);
}'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'check.c').write_text(program)
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread',
                            str(path / 'check.c'), '-o', str(path / 'check')], check=True)
            subprocess.run([str(path / 'check')], check=True)

    def test_packaged_qemu_libraries_are_verified_before_launch(self):
        import menu_host
        import json, hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(menu_host.qemu_command('/binary', root), ['/binary'])
            libraries = root / 'runtime/qemu-libs'
            libraries.mkdir(parents=True)
            loader = libraries / 'ld-linux-x86-64.so.2'
            loader.write_bytes(b'fixture-loader')
            manifest = {'files': {loader.name: {'bytes': loader.stat().st_size,
                         'sha256': hashlib.sha256(loader.read_bytes()).hexdigest()}}}
            (libraries / 'manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(menu_host.qemu_command('/binary', root)[0], str(loader))
            loader.write_bytes(b'changed')
            with self.assertRaises(ValueError): menu_host.qemu_command('/binary', root)
            manifest['files'] = {'../escape': {'bytes': 0, 'sha256': '0'*64}}
            (libraries / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): menu_host.qemu_command('/binary', root)

    def test_native_serial_phase_has_total_deadline(self):
        import menu_run as run
        class Channel:
            def settimeout(self, seconds): self.timeout = seconds
        class ContinuousNoise:
            def readline(self, bound):
                run.time.monotonic.clock += 1
                return b'original background trace\n'
        class Clock:
            clock = 0
            def __call__(self): return self.clock
        original = run.time.monotonic
        run.time.monotonic = Clock()
        try:
            guest = object.__new__(run.NativeGuest)
            guest.channel, guest.stream = Channel(), ContinuousNoise()
            guest.timeout = 3
            with tempfile.TemporaryFile() as log:
                guest.log = log
                with self.assertRaises(TimeoutError): guest.line()
        finally:
            run.time.monotonic = original

    def test_settle_waits_for_three_identical_frames_after_a_late_draw(self):
        from menu_run import settle
        class Guest:
            def __init__(self, hashes):
                self.hashes = iter(hashes)
                self.calls = 0
            def capture(self):
                self.calls += 1
                return {'raw_sha256': next(self.hashes)}, object()
        guest = Guest(['a', 'a', 'b', 'b', 'b'])
        frame, _ = settle(guest)
        self.assertEqual(frame['raw_sha256'], 'b')
        self.assertEqual(guest.calls, 5)
        with self.assertRaises(RuntimeError):
            settle(Guest(['a', 'a', 'b', 'b']), limit=3)

    def test_changed_source_seam_is_refused(self):
        from menu_build import replace_once
        for source in ('absent marker', 'seam seam'):
            with self.assertRaises(ValueError): replace_once(source, 'seam', 'replacement')
        self.assertEqual(replace_once('left seam right', 'seam', 'replacement'), 'left replacement right')

    def test_failed_native_close_still_has_final_qmp_boundary(self):
        # Exercise the actual cleanup suite without launching a VM.
        import ast
        source = (ROOT / 'scripts/menu_run.py').read_text()
        tree = ast.parse(source)
        cleanup = next(node for node in ast.walk(tree) if isinstance(node, ast.Try) and
                       any(isinstance(item, ast.Expr) and isinstance(item.value, ast.Call) and
                           isinstance(item.value.func, ast.Attribute) and item.value.func.attr == 'finish'
                           for item in node.finalbody))
        class Guest:
            frames, events, pending = [], [], False
            def close(self): raise OSError('injected serial close failure')
        class Host:
            called = False
            def finish(self, *args): self.called = True
        host = Host()
        scope = {'guest': Guest(), 'result': {'guest_done': True, 'ok': True}, 'host': host,
                 'serial': None, 'process': None, 'qmp': None, 'qmp_path': None}
        exec(compile(ast.Module(body=[cleanup], type_ignores=[]), '<actual-cleanup>', 'exec'), scope)
        self.assertTrue(host.called)
        self.assertFalse(scope['result']['ok'])
        self.assertIn('injected serial close failure', scope['result']['native_serial_close_error'])


if __name__ == '__main__':
    unittest.main()
