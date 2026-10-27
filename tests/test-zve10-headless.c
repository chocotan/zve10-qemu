#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

/* Synthetic native objects and PFNs: these tests do not execute Sony firmware. */
static uintptr_t object_base;
static char test_path[512];
static int fail_lock, change_identity, fail_pagemap, fail_pin, fail_sync, short_reads;
struct counters { unsigned waits, locks, unlocks, callbacks, active, gate, pages, ready, exported; };
static struct counters *calls;
static uint32_t get32(const void *p) { uint32_t v; memcpy(&v,p,4); return v; }
static void put32(void *p, uint32_t v) { memcpy(p,&v,4); }
static void put16(void *p, uint16_t v) { memcpy(p,&v,2); }
static unsigned char *at(unsigned n) { return (void *)(object_base+n); }
static int native_bpp(uint32_t f, int16_t *v) { assert(f==1); *v=2; return 0; }
static int native_phys(void *b, uint32_t *v) { *v=get32((void *)(uintptr_t)(get32((char *)b+4)+0x24)); return 0; }
static int native_read(void *b, int32_t timeout, const void **out)
{
    assert(timeout==0); ++calls->locks;
    if (fail_lock) return -8;
    ++calls->active;
    *out=(void *)(uintptr_t)get32((char *)b+8);
    if (change_identity) put32((void *)(uintptr_t)(get32((char *)b+4)+0x30),1);
    return 0;
}
static void native_unlock(void *b) { (void)b; assert(calls->active); --calls->active; ++calls->unlocks; }
static int native_wait(uint32_t sid, uint32_t timeout)
{
    assert(sid==0x800123 && timeout==UINT32_MAX && !calls->gate);
    ++calls->waits; calls->gate=1; return 0;
}
static void native_complete(void);
static uintptr_t test_native(unsigned offset)
{
    switch(offset) {
    case 0x69d145: return (uintptr_t)native_bpp;
    case 0x684e6d: return (uintptr_t)native_phys;
    case 0x69b901: return (uintptr_t)native_read;
    case 0x69b29d: return (uintptr_t)native_unlock;
    case 0x6fafb9: return (uintptr_t)native_complete;
    default: assert(!"unexpected native call"); return 0;
    }
}
static void *test_dlsym(void *h, const char *name)
{
    assert(h==RTLD_NEXT && !strcmp(name,"osal_wai_sem_tmo"));
    return (void *)native_wait;
}
static ssize_t test_pread(int fd, void *out, size_t size, off_t offset)
{
    (void)fd;
    if (short_reads==1) { short_reads=2; errno=EINTR; return -1; }
    uint64_t entry=(UINT64_C(1)<<63) | (0x10000 + ((uint64_t)offset/8)%0x1000);
    if (fail_pagemap==1) entry=0;
    if (fail_pagemap==2) entry=(UINT64_C(1)<<63) | 0x40000;
    unsigned within=(unsigned)(offset%8);
    assert(size<=8-within);
    if (short_reads && size>4) size=4;
    memcpy(out,(unsigned char *)&entry+within,size);
    ++calls->pages;
    return (ssize_t)size;
}
static int test_mlock(const void *p, size_t n)
{
    if (fail_pin) { errno=ENOMEM; return -1; }
    return mlock(p,n);
}
static int test_fsync(int fd)
{
    if (fail_sync) { errno=ENOSPC; return -1; }
    return fsync(fd);
}
static ssize_t test_write(int fd, const void *data, size_t length)
{
    assert(fd==2 && length && ((const char *)data)[length-1]=='\n');
    if (length>=19 && !memcmp(data,"UI_OUTPUT_COMMITTED",19)) {
        assert(calls->callbacks && !calls->gate && !calls->active);
    } else if (length>=16 && !memcmp(data,"UI_CAPTURE_READY",16)) {
        assert(calls->callbacks && !calls->gate && !calls->active);
        assert(calls->exported);
        ++calls->ready;
    } else {
        assert(calls->gate && !calls->active);
        ++calls->exported;
    }
    return (ssize_t)length;
}
static void record(const char *name, uintptr_t value)
{
    fprintf(stderr,"TEST %s=%#lx\n",name,(unsigned long)value);
}
#define UI_HEADLESS_FN(offset, type) ((type)test_native(offset))
#define UI_HEADLESS_PATH test_path
#define dlsym test_dlsym
#define pread test_pread
#define mlock test_mlock
#define fsync test_fsync
#define write test_write
#include "../source/ui/ui-headless.h"
#undef write
#undef dlsym
#undef pread
#undef mlock
#undef fsync

static void read_json(char *buffer, size_t capacity)
{
    FILE *f=fopen(test_path,"r"); assert(f);
    size_t n=fread(buffer,1,capacity-1,f); assert(!ferror(f)); buffer[n]=0;
    assert(!fclose(f));
}
static void native_complete(void)
{
    assert(calls->gate && !calls->active && headless_published);
    char json[24000]; read_json(json,sizeof json);
    assert(strstr(json,"\"label\":\"committed_native_frame\""));
    assert(strstr(json,"\"export_ready\":true") || strstr(json,"\"export_ready\":false"));
    if (headless_retained.pixels) {
        assert(strstr(json,"\"segments\":[{"));
        size_t length=0;
        for (unsigned i=0;i<headless_retained.segments;++i) {
            assert(headless_retained.page[i].offset==length);
            assert(headless_retained.page[i].length>0 && headless_retained.page[i].length<=4096);
            length+=headless_retained.page[i].length;
        }
        assert(length==HEADLESS_BYTES);
    }
    ++calls->callbacks; calls->gate=0;
    unsigned count=get32(at(0x145d0f0+0x5c));
    memcpy(at(0x145d0f0+0x70),at(0x145d0f0+0xb0),32*count);
    put32(at(0x145d0f0+0x58),count); put32(at(0x145d0f0+0x5c),0);
}
static void setup(void)
{
    native_glyph_images=13;
    put32(at(0x145dbc0),(uint32_t)(object_base+0x6f6cf7));
    put32(at(0x145dbb8),(uint32_t)(object_base+0x145d0f0));
    put32(at(0x145dbc4),0x800123);
    for (unsigned i=0;i<2;++i) {
        unsigned char *b=at(0x10000+i*0x2000), *m=b+0x1000;
        unsigned char *pixels=at(0x20000+i*0x100000);
        put32(b,(uint32_t)(object_base+0x13ba5a0));
        put32(b+4,(uint32_t)(uintptr_t)m); put32(b+8,(uint32_t)(uintptr_t)pixels);
        memset(m,0,0x34); put16(m+8,640); put16(m+10,480);
        put16(m+0x18,640); put16(m+0x1a,480); put32(m+0x1c,1);
        put32(m+0x24,0x22bb2000+i*0x100000);
        /* Uniform words with unequal bytes must not be classified as nonuniform. */
        for (unsigned n=0;n<HEADLESS_BYTES;n+=2) put16(pixels+n,0xf00f);
        unsigned char *r=at(0x145d0f0+0xb0+32*i);
        memset(r,0,32); put16(r+4,480); put16(r+6,640);
        put16(r+8,480); put16(r+10,640); put16(r+12,2);
        put32(r+16,1); put32(r+20,get32(m+0x24)); put32(r+24,0x101+i);
        put32(r+28,(uint32_t)(uintptr_t)b);
    }
}
static void update(unsigned count)
{
    put32(at(0x145d0f0+0x5c),count);
    assert(!software_headless_update(object_base+0x145d0f0+0xb0,count,0,0));
}
static void scenario(unsigned which)
{
    setup();
    if (which==0) {
        native_glyph_images=1;
        put16(at(0x20000)+2,0x1234);
        short_reads=1; update(1);
        assert(!headless_retained.pixels && calls->callbacks==1 && !calls->pages);
        char json[24000]; read_json(json,sizeof json); assert(strstr(json,"\"export_ready\":false"));
        native_glyph_images=13;
        put16(at(0x20000)+2,0xf00f);
        put16(at(0x20000)+HEADLESS_BYTES-2,0x1234); update(1);
        unsigned char *retained=headless_retained.pixels;
        assert(retained && headless_retained.frame==2 && headless_retained.index==0);
        assert(get32(retained)==0xf00ff00f && headless_u16(retained+HEADLESS_BYTES-2)==0x1234);
        put16(at(0x20000)+HEADLESS_BYTES-2,0x5678); update(1);
        assert(headless_retained.pixels==retained && headless_retained.frame==2);
        assert(headless_u16(retained+HEADLESS_BYTES-2)==0x1234);
        assert(headless_native_frames==3 && calls->callbacks==3 && calls->unlocks==3);
        assert(calls->ready==1 && calls->pages);
        read_json(json,sizeof json); assert(strstr(json,"\"native_frame_count\":3"));
    } else if (which==1) {
        put16(at(0x120000)+2,0x1234); update(2);
        assert(headless_retained.index==1 && calls->locks==2 && calls->unlocks==2 && calls->callbacks==1);
    } else {
        put32(at(0x145d0f0+0x5c),1);
        switch(which) {
        case 2: software_headless_update(object_base+0x145d0f0+0xb0,3,0,0); break;
        case 3: put32(at(0x145dbc0),0); update(1); break;
        case 4: put32(at(0x11000+0x2c),1); update(1); break;
        case 5: put32(at(0x145d0f0+0xb0+20),0x22000000); update(1); break;
        case 6: fail_lock=1; update(1); break;
        case 7: fail_pagemap=1; put16(at(0x20000)+2,0x1234); update(1); break;
        case 8: change_identity=1; update(1); break;
        case 9: put32(at(0x13000+0x30),1); update(2); break;
        case 10: fail_sync=1; update(1); break;
        case 11: fail_pin=1; put16(at(0x20000)+2,0x1234); update(1); break;
        case 12:
            put16(at(0x20000)+2,0x1234); update(1);
            fail_sync=1; update(1); break;
        case 13: software_headless_update(object_base+0x145d0f0+0xb0+32,1,0,0); break;
        case 14: fail_pagemap=2; put16(at(0x20000)+2,0x1234); update(1); break;
        default: assert(0);
        }
        assert(!"failure returned instead of exiting71");
    }
    assert(!calls->active && !calls->gate);
}
int main(void)
{
    (void)native_glyph_draws; (void)native_glyph_bitmaps;
    assert(headless_fingerprint((const unsigned char *)"",0)==UINT64_C(0xcbf29ce484222325));
    assert(headless_fingerprint((const unsigned char *)"a",1)==UINT64_C(0xaf63dc4c8601ec8c));
    assert(headless_fingerprint((const unsigned char *)"foobar",6)==UINT64_C(0x85944171f73967e8));
    int flags=MAP_PRIVATE|MAP_ANONYMOUS;
#ifdef MAP_32BIT
    flags|=MAP_32BIT;
#endif
    void *base=mmap(NULL,0x1460000,PROT_READ|PROT_WRITE,flags,-1,0);
    assert(base!=MAP_FAILED && (uintptr_t)base<=UINT32_MAX-0x1460000);
    object_base=(uintptr_t)base;
    calls=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED|MAP_ANONYMOUS,-1,0);
    assert(calls!=MAP_FAILED);
    char directory[]="/tmp/zve10-headless-test-XXXXXX"; assert(mkdtemp(directory));
    for (unsigned i=0;i<15;++i) {
        memset(calls,0,sizeof *calls);
        assert(snprintf(test_path,sizeof test_path,"%s/%u.json",directory,i)>0);
        pid_t child=fork(); assert(child>=0);
        if (!child) { scenario(i); _exit(0); }
        int status; assert(waitpid(child,&status,0)==child);
        assert(WIFEXITED(status) && WEXITSTATUS(status)==(i<2 ? 0 : 71));
        assert(!calls->active);
        assert(calls->callbacks==(i==0 ? 3u : i==1 || i==12 ? 1u : 0u));
        if (i==2 || i==3 || i==13) assert(!calls->waits);
        if (i==9) assert(calls->locks==1 && calls->unlocks==1);
        if (i==12) assert(access(test_path,F_OK)<0);
        unlink(test_path);
    }
    assert(!rmdir(directory));
    puts("PASS: native leases, all-record copy, exact completion, retained first nonuniform frame, page export and terminal failures");
    return 0;
}
