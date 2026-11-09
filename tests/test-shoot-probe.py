"""Run the actual receive observer against pointer output and allocation bounds."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def test_preload_version_check_rejects_the_glibc_217_regression():
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    from menu_build import verify_library_versions
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text('#include <time.h>\nvoid *required_clock = (void *)clock_gettime;\n')
        subprocess.run(['cc', '-shared', '-fPIC', '-nostartfiles', str(path / 'check.c'), '-o', str(path / 'check.so')], check=True)
        try:
            verify_library_versions(path / 'check.so', {'libc.so.6': {'GLIBC_2.4', 'GLIBC_2.12'}})
        except ValueError as error:
            assert 'GLIBC_2.17' in str(error)
        else:
            raise AssertionError('the unsupported libc dependency was admitted')
        required = verify_library_versions(path / 'check.so', {'libc.so.6': {'GLIBC_2.17'}})
        assert required == {'libc.so.6': ['GLIBC_2.17']}


def test_receive_observer_reads_the_returned_allocation_only():
    source = (ROOT / 'source/menu/original.inc').read_text()
    start = source.index('static unsigned ne_rcv_logs;')
    observer = source[start:source.index('\n#endif', start)]
    program = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
static char line[512];
static uintptr_t object_base;
static int status, allocation_size=1, size_calls;
static void *allocation;
static void ne_line(const char *format, ...) {
    va_list ap;va_start(ap,format);vsnprintf(line,sizeof line,format,ap);va_end(ap);
}
static int receive(uint32_t queue, void **output, uint32_t timeout) {
    assert(queue==8388667 && timeout==17);
    if(!status && output) *output=allocation;
    return status;
}
static int message_size(void *message) {
    assert(message==allocation);++size_calls;return allocation_size;
}
static void *resolve(void *handle, const char *name) {
    (void)handle;
    if(!strcmp(name,"osal_rcv_msg_tmo"))return receive;
    assert(!strcmp(name,"osal_msg_size"));return message_size;
}
static int address_info(void *p,Dl_info *info){(void)p;(void)info;return 0;}
#define dlsym resolve
#define dladdr address_info
#define syscall(number) 7L
''' + observer + r'''
int main(void) {
    allocation=malloc(1);assert(allocation);*(unsigned char *)allocation=0xab;
    void *output=NULL;
    assert(!osal_rcv_msg_tmo(8388667,&output,17));assert(output==allocation);
    assert(strstr(line,"\"size\":1,\"hex\":\"ab\""));assert(size_calls==1);
    status=-1022;output=(void *)1;
    assert(osal_rcv_msg_tmo(8388667,&output,17)==-1022);
    assert(output==(void *)1 && size_calls==1);
    assert(strstr(line,"\"size\":0,\"hex\":\"\""));
    status=0;assert(!osal_rcv_msg_tmo(8388667,NULL,17));assert(size_calls==1);
    free(allocation);allocation=(void *)1;allocation_size=5000;
    assert(!osal_rcv_msg_tmo(8388667,&output,17));
    assert(strstr(line,"\"size\":5000,\"hex\":\"\""));
    allocation_size=-1;assert(!osal_rcv_msg_tmo(8388667,&output,17));
    assert(strstr(line,"\"size\":-1,\"hex\":\"\""));
    allocation=malloc(128);assert(allocation);memset(allocation,0xcd,128);allocation_size=128;
    assert(!osal_rcv_msg_tmo(8388667,&output,17));
    const char *hex=strstr(line,"\"hex\":\"")+7;assert(hex);
    assert(strchr(hex,'"')-hex==128);free(allocation);
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)


def test_full_tiled_fill_writes_uniform_bytes_and_rejects_other_operations():
    program = r'''
#include <assert.h>
#include <stdlib.h>
#include "ui-raster.h"
#include "shoot_fill.h"
static void word(unsigned char *p,unsigned at,uint32_t value){memcpy(p+at,&value,4);}
int main(void){
    size_t size=640u*480u*2u;
    unsigned char *buffer=malloc(size+32);assert(buffer);
    unsigned char params[48]={0};
    word(params,0,0x32ac6200);word(params,4,640u|(480u<<16));
    word(params,12,640u|(480u<<16));word(params,20,1);params[32]=255;
    memset(buffer,0x5a,size+32);
    assert(!ne_full_tiled_fill(buffer+16,size,params));
    for(size_t i=0;i<size;++i)assert(!buffer[16+i]);
    params[28]=255;params[31]=255;
    assert(!ne_full_tiled_fill(buffer+16,size,params));
    for(size_t i=0;i<size;i+=2){assert(buffer[16+i]==0x0f);assert(buffer[17+i]==0xf0);}
    for(size_t i=0;i<16;++i){assert(buffer[i]==0x5a);assert(buffer[size+16+i]==0x5a);}
    assert(ne_full_tiled_fill(buffer+16,size-1,params)==-5);
    const unsigned offsets[]={4,8,12,16,20,24,32,36};
    for(unsigned i=0;i<sizeof offsets/sizeof offsets[0];++i){
        unsigned char bad[48];memcpy(bad,params,48);bad[offsets[i]]^=1;
        assert(ne_full_tiled_fill(buffer+16,size,bad)==-5);
    }
    free(buffer);
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-function', '-fsanitize=address,undefined',
                        '-I', str(ROOT / 'source/ui'), '-I', str(ROOT / 'source/menu'),
                        str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)


def test_diagnostic_underlay_preserves_original_opaque_black_and_white():
    source = (ROOT / 'source/menu/original.inc').read_text()
    start = source.index('static unsigned ne_shoot_frames;')
    function = source[start:source.index('\n#endif', start)]
    program = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
static void ne_line(const char *format, ...){(void)format;}
''' + function + r'''
int main(void){
    uint16_t *pixels=calloc(640u*480u,sizeof *pixels);assert(pixels);
    pixels[0]=0x000f;pixels[1]=0xffff;
    ne_shoot_frame(pixels,640u*480u);
    assert(pixels[0]==0x000f && pixels[1]==0xffff && pixels[2]==0x0fff);
    assert(pixels[430u*640u]==0x000f);
    /* The next present is copied from the original source, with freshly drawn OSD. */
    for(unsigned i=0;i<640u*480u;++i)pixels[i]=0;
    pixels[430u*640u+10]=0xffff;
    ne_shoot_frame(pixels,640u*480u);
    assert(pixels[430u*640u+10]==0xffff && pixels[430u*640u+8]==0x000f);
    assert(pixels[430u*640u]==0xffff);
    ne_shoot_frame(pixels,1);assert(ne_shoot_frames==2);
    free(pixels);
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)


def test_shoot_warmup_uses_guest_time_with_a_host_deadline(monkeypatch):
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    import menu_run
    from PIL import Image
    for rate in (1000, 0):
        clock = [0.0]
        monkeypatch.setattr(menu_run.time, 'monotonic', lambda: clock[0])
        monkeypatch.setattr(menu_run.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        class Guest:
            def snapshot_state(self):
                return {'guest_ms': int(clock[0] * rate)}
            def capture(self):
                assert clock[0] >= (2 if rate else 90)
                return {'state': {'view': 1, 'view_state': 0, 'node_installed': 0}}, Image.new('RGB', (640,480))
            def dump_threads(self):
                return {'count': 1}
        result = menu_run.shoot_observe(Guest(), frames=1, warmup_ms=2000)
        assert result['warmup_guest_elapsed_ms'] == (2000 if rate else 0)
        assert result['frames'] == 1 and clock[0] <= 95


def test_capture_table_model_has_real_bounded_data_and_rejects_unknown_requests():
    program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "ui-raster.h"
#include "capture_table_model.h"
int main(void){
    uint32_t request[6]={0,0x1000,0,0,0,0};
    assert(!ne_capture_table_request(request,52,0x3060c4));
    assert(ne_capture_table_request(request,23,0x3060c4)==-1);
    assert(ne_capture_table_request(request,65,0x3060c4)==-1);
    assert(ne_capture_table_request(request,52,0)==-1);
    assert(ne_capture_table_request(request,52,0x4015e)==-1);
    request[1]=0x1001;assert(!ne_capture_table_request(request,52,0x3060c4));
    request[1]=0x1002;assert(!ne_capture_table_request(request,52,0x3060c4));
    request[1]=0x1003;assert(ne_capture_table_request(request,52,0x3060c4)==-1);request[1]=0x1000;
    for(unsigned i=0;i<6;++i){if(i==1)continue;request[i]^=1;assert(ne_capture_table_request(request,52,0x3060c4)==-1);request[i]^=1;}
    unsigned char *memory=malloc(NE_CAPTURE_TABLE_BYTES+16);assert(memory);memset(memory,0x5a,NE_CAPTURE_TABLE_BYTES+16);
    assert(ne_capture_table_initialize(memory,NE_CAPTURE_TABLE_BYTES-1)==-1);
    assert(!ne_capture_table_initialize(memory,NE_CAPTURE_TABLE_BYTES));
    assert(ui_u32(memory)==1024 && ui_u32(memory+4)==1023 && ui_u32(memory+8)==1023 && ui_u32(memory+12)==1023 && !ui_u32(memory+16));
    for(unsigned i=20;i<NE_CAPTURE_TABLE_BYTES;++i)assert(!memory[i]);
    for(unsigned i=NE_CAPTURE_TABLE_BYTES;i<NE_CAPTURE_TABLE_BYTES+16;++i)assert(memory[i]==0x5a);
    /* Original client mutations stay in the shared table; no per-request reset. */
    memory[40]=37;assert(memory[40]==37);
    assert(!ne_capture_table_initialize(memory,NE_CAPTURE_TABLE_BYTES) && !memory[40]);free(memory);
    memory=calloc(1,NE_CAPTURE_TABLE_MAPPING);assert(memory);uint32_t owner=0;
    assert(!ne_capture_table_initialize(memory,NE_CAPTURE_TABLE_MAPPING));memory[40]=37;
    assert(!ne_capture_table_access(memory,NE_CAPTURE_TABLE_MAPPING,0x1001,221,&owner) && owner==221 && memory[40]==37);
    assert(ne_capture_table_access(memory,NE_CAPTURE_TABLE_MAPPING,0x1001,223,&owner)==-1);
    memory[41]=63;
    assert(ne_capture_table_access(memory,NE_CAPTURE_TABLE_MAPPING,0x1002,223,&owner)==-1 && owner==221);
    assert(!ne_capture_table_access(memory,NE_CAPTURE_TABLE_MAPPING,0x1002,221,&owner) && !owner);
    assert(!memcmp(memory,memory+NE_CAPTURE_TABLE_CHECKPOINT,NE_CAPTURE_TABLE_BYTES));
    assert(memory[40]==37 && memory[41]==63);
    assert(ne_capture_table_access(memory,NE_CAPTURE_TABLE_MAPPING,0x1002,221,&owner)==-1);free(memory);
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-function', '-fsanitize=address,undefined',
                        '-I', str(ROOT / 'source/ui'), '-I', str(ROOT / 'source/menu'),
                        str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)


def test_capture_table_qmp_readback_rejects_bounds_and_resumes_after_read_failure():
    import importlib.util
    import json
    import sys
    from types import SimpleNamespace
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('capture_table_run_test', ROOT / 'scripts/menu_run.py')
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    calls = []
    state = {'physical': 0x1ff00001, 'bytes': 0x4014, 'fingerprint': 'x', 'checkpoint_fingerprint': 'x'}
    def call(command, arguments=None):
        calls.append(command)
        if command == 'query-status': return {'status': 'paused'}
        if command == 'pmemsave': raise RuntimeError('independent read failed')
    with tempfile.TemporaryDirectory() as directory:
        guest = SimpleNamespace(pending=False, send=lambda _: None,
                                until=lambda _: b'NE_CAPTURE_TABLE_STATE ' + json.dumps(state).encode(),
                                qmp=SimpleNamespace(call=call), out=Path(directory))
        try: run.NativeGuest.capture_table(guest)
        except RuntimeError as error: assert 'bounds' in str(error)
        else: raise AssertionError('unexpected physical memory was accepted')
        assert calls == []
        state['physical'] = 0x1ff00000
        try: run.NativeGuest.capture_table(guest)
        except RuntimeError as error: assert 'independent read failed' in str(error)
        else: raise AssertionError('failed independent RAM read was accepted')
        assert calls == ['stop', 'query-status', 'pmemsave', 'cont']


def test_sync_observers_preserve_five_arguments_inout_result_and_errno():
    source = (ROOT / 'source/menu/original.inc').read_text()
    start = source.index('static int ne_trace_sync_wrapper(')
    functions = source[start:source.index('/* The receiver owns', start)]
    program = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
static uintptr_t object_base=0x10000000;
static uint32_t wrapper[6],input=41,output;
static uint32_t ui_u32(const void *p){uint32_t v;memcpy(&v,p,4);return v;}
static void ne_line(const char *format,...){(void)format;errno=EIO;}
static int send_original(void *self,const void *in,int n,void *out,int m){
    assert(self==wrapper && in==&input && out==&output && n==4 && m==4 && errno==EINVAL);
    output=*(const uint32_t *)in+2;errno=ERANGE;return -73;
}
static int recv_original(void *self,void *in,int n,void *out,int m){
    assert(self==wrapper && in==&input && out==&output && n==4 && m==4 && errno==EINVAL);
    ++*(uint32_t *)in;output=*(uint32_t *)in+5;errno=ENOTTY;return 17;
}
static void *resolve(void *handle,const char *name){
    (void)handle;errno=ENOSYS;
    if(!strcmp(name,"_ZN3MWF12EventWrapper4SendEPKviPvi"))return send_original;
    assert(!strcmp(name,"_ZN3MWF12EventWrapper11SendAndRecvEPviS1_i"));return recv_original;
}
#define dlsym resolve
#define syscall(number) 7L
''' + functions + r'''
int main(void){
    wrapper[1]=0x37807c;errno=EINVAL;
    assert(ne_event_send(wrapper,&input,4,&output,4)==-73 && output==43 && input==41 && errno==ERANGE);
    wrapper[1]=0xcf016d;errno=EINVAL;
    assert(ne_event_send_recv(wrapper,&input,4,&output,4)==17 && output==47 && input==42 && errno==ENOTTY);
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)


def test_content_slots_are_checked_and_only_the_six_words_change():
    source = (ROOT / 'source/menu/original.inc').read_text()
    start = source.index('static int ne_install_content_observers(')
    function = source[start:source.index('typedef void *(*ne_content_create_fn)', start)]
    program = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
static uintptr_t object_base;
#define ne_content_loop_wrapper ((void *)0x12345679)
#define ne_content_start_wrapper ((void *)0x23456789)
''' + function + r'''
int main(void){
    unsigned char *arena=mmap(NULL,8192,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_32BIT,-1,0);
    assert(arena!=MAP_FAILED && (uintptr_t)arena>0x13c2000);object_base=(uintptr_t)arena-0x13c2000;
    const unsigned offsets[]={0xc18+0x38,0x1258+0x38,0x1330+0x38};
    memset(arena,0x5a,8192);assert(ne_install_content_observers()==-1);
    const unsigned native[]={0x8e3711,0x8f3591,0x8f3591},starts[]={0x907aa9,0x90dc99,0x91a733};
    for(unsigned i=0;i<3;++i){uint32_t pair[2]={(uint32_t)(object_base+native[i]),(uint32_t)(object_base+starts[i])};memcpy(arena+offsets[i],pair,8);}
    unsigned char before[8192];memcpy(before,arena,8192);assert(!ne_install_content_observers());
    for(unsigned i=0;i<3;++i){uint32_t pair[2];memcpy(pair,arena+offsets[i],8);assert(pair[0]==0x12345679 && pair[1]==0x23456789);memcpy(before+offsets[i],pair,8);}
    assert(!memcmp(before,arena,8192));assert(!munmap(arena,8192));
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)


def test_pending_resource_snapshot_bounds_and_change_detection():
    source = (ROOT / 'source/menu/original.inc').read_text()
    start = source.index('static void ne_trace_pending_batch(')
    function = source[start:source.index('static uintptr_t ne_model_event_wrapper', start)]
    program = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdarg.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>
static uintptr_t object_base;
static unsigned lines;
static void ne_line(const char *format,...){(void)format;++lines;}
static uint32_t ui_u32(const void *p){uint32_t x;memcpy(&x,p,4);return x;}
static void put(void *p,uintptr_t x){uint32_t v=(uint32_t)x;memcpy(p,&v,4);}
''' + function + r'''
int main(void){
    unsigned char *arena=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_32BIT,-1,0);
    assert(arena!=MAP_FAILED && (uintptr_t)arena>0x145b048);
    object_base=(uintptr_t)arena-0x145b048;put(arena,(uintptr_t)(arena+32));
    unsigned char *context=arena+32,*node=arena+256,*commands=arena+512,*command=arena+768;
    put(context+0xc,1);put(context+0x14,11);put(context+0x18,0x1200a041);
    put(context+0x70,(uintptr_t)(arena+1024));put(context+0x74,(uintptr_t)(arena+1028));
    put(arena+1024,(uintptr_t)node);put(node+0xc,18);put(node+4,11);
    put(node+0x10,(uintptr_t)commands);commands[8]=1;put(commands+0xc,(uintptr_t)command);put(command+4,2);
    ne_trace_pending_batch();assert(lines==2);
    ne_trace_pending_batch();assert(lines==2);
    commands[8]=0;ne_trace_pending_batch();assert(lines==4);
    put(context+0x74,(uintptr_t)(arena+1024+33*4));ne_trace_pending_batch();assert(lines==4);
    put(context+0x74,(uintptr_t)(arena+1025));ne_trace_pending_batch();assert(lines==4);
    put(context+0x74,(uintptr_t)(arena+1000));ne_trace_pending_batch();assert(lines==4);
    assert(!munmap(arena,4096));
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)


def test_remote_stage_observers_preserve_native_arguments_results_and_errno():
    source = (ROOT / 'source/menu/original.inc').read_text()
    start = source.index('static uintptr_t (*ne_original_remote_sinks)')
    functions = source[start:source.index('static int ne_install_remote_stages(', start)]
    program = r'''
#include <assert.h>
#include <stdint.h>
#include <errno.h>
#include <unistd.h>
static void ne_line(const char *format,...){(void)format;errno=EIO;}
static unsigned object,calls;
static uintptr_t one(void *p){assert(p==&object && errno==EINTR);++calls;errno=EAGAIN;return 137;}
static uintptr_t two(void *p,uint32_t option){assert(p==&object && option==0x81234567 && errno==EINTR);++calls;errno=EAGAIN;return 138;}
static uintptr_t three(uint32_t module,uint32_t mode,uint32_t cookie){assert(module==0x16a && mode==3 && cookie==0x81234567 && errno==EINTR);++calls;errno=EAGAIN;return 140;}
static uintptr_t five(uint32_t request,uint32_t module,uint32_t reply,void *out,uint32_t cookie){
assert(request==0xf1234567 && module==0x16a && reply==0x312345 && out==&object && cookie==0x81234567 && errno==EINTR);
++calls;errno=EAGAIN;return 139;}
''' + functions + r'''
int main(void){
ne_original_remote_sinks=one;ne_original_remote_config=two;ne_original_remote_infra=two;ne_original_remote_module=five;ne_original_im_load=three;
errno=EINTR;assert(ne_remote_sinks_wrapper(&object)==137 && errno==EAGAIN);
errno=EINTR;assert(ne_remote_config_wrapper(&object,0x81234567)==138 && errno==EAGAIN);
errno=EINTR;assert(ne_remote_infra_wrapper(&object,0x81234567)==138 && errno==EAGAIN);
errno=EINTR;assert(ne_remote_module_wrapper(0xf1234567,0x16a,0x312345,&object,0x81234567)==139 && errno==EAGAIN);
errno=EINTR;assert(ne_im_load_wrapper(0x16a,3,0x81234567)==140 && errno==EAGAIN);
assert(calls==5);}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-D_GNU_SOURCE', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)


def test_media_batch_observer_forwards_all_five_arguments():
    source = (ROOT / 'source/menu/original.inc').read_text()
    start = source.index('typedef uintptr_t (*ne_batch_fn)')
    functions = source[start:source.index('static uintptr_t ne_media_scan_wrapper', start)]
    program = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
static unsigned calls;
static uint32_t expected_model,expected_function;
static void ne_line(const char *format,...){(void)format;errno=EIO;}
static const uint32_t resource_ids[]={18,25,196,249,0};
static const unsigned message=37;
static uintptr_t native_batch(uint32_t model,uint32_t function,const uint32_t *ids,
                              const void *messages,uint32_t option){
    assert(model==expected_model && function==expected_function && ids==resource_ids && messages==&message);
    assert(option==0xdeadbeef && errno==EINTR);++calls;errno=EAGAIN;return (uintptr_t)0x12345678;
}
''' + functions + r'''
int main(void){ne_original_batch=native_batch;
const uint32_t models[]={10,245,294,2},functions[]={65,44,17,1};
for(unsigned i=0;i<4;++i){expected_model=models[i];expected_function=functions[i];errno=EINTR;
assert(ne_batch_wrapper(models[i],functions[i],resource_ids,&message,0xdeadbeef)==0x12345678 && calls==i+1 && errno==EAGAIN);}}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)


def test_uipc_dump_is_read_only_and_stops_at_its_output_cap():
    source = (ROOT / 'source/menu/original.inc').read_text()
    start = source.index('static int ne_dump_uipc(')
    function = source[start:source.index('static int ne_capture_table_model_snapshot(', start)]
    program = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static unsigned chunks,done;
static int guarded_open(const char *path,int flags){
assert(!strcmp(path,"/proc/osal/uipc") && flags==(O_RDONLY|O_CLOEXEC));
return open("/dev/zero",flags);}
static void ne_line(const char *format,...){
char text[512];va_list ap;va_start(ap,format);vsnprintf(text,sizeof text,format,ap);va_end(ap);
if(strstr(text,"NE_UIPC_DONE")){assert(strstr(text,"\"bytes\":65536,\"capped\":true"));++done;}
else{assert(strstr(text,"\"hex\":\"0000000000000000"));++chunks;}}
#define open guarded_open
''' + function + r'''
int main(void){assert(!ne_dump_uipc() && done==1 && chunks==1024);}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)


def test_thread_dump_reads_only_its_own_process_and_terminates():
    source = (ROOT / 'source/menu/original.inc').read_text()
    start = source.index('static void ne_dump_thread_file(')
    functions = source[start:source.index('\n#endif', start)]
    program = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static long ui_tid,rm_tid;
static unsigned done,comm;
static void ne_line(const char *format,...){
    char text[512];va_list ap;va_start(ap,format);
    int n=vsnprintf(text,sizeof text,format,ap);va_end(ap);
    assert(n>0 && n<(int)sizeof text);
    if(strstr(text,"NE_THREADS_DONE"))++done;
    if(strstr(text,"\"file\":\"comm\"") && strstr(text,"\"hex\":\""))++comm;
}
static int own_open(const char *path,int flags){
    assert(!strncmp(path,"/proc/self/task/",16));
    assert(flags==(O_RDONLY|O_CLOEXEC));
    return open(path,flags);
}
#define open own_open
''' + functions + r'''
int main(void){ui_tid=rm_tid=getpid();ne_dump_threads();assert(done==1 && comm>=1);}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(path / 'check.c'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True, timeout=10)


def test_draw_rejection_fails_before_returning_a_cached_frame():
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    import menu_run
    class Channel:
        def settimeout(self, seconds):
            pass
    class Stream:
        def readline(self, size):
            return b'UI_OBSERVE pid=103 DMP.fill.UNSUPPORTED=0x1\n'
    guest = object.__new__(menu_run.NativeGuest)
    guest.timeout, guest.channel, guest.stream = 3, Channel(), Stream()
    with tempfile.TemporaryFile() as log:
        guest.log = log
        try:
            guest.line()
        except RuntimeError as error:
            assert 'renderer rejected' in str(error)
        else:
            raise AssertionError('unsupported pixels were accepted')
