#define _GNU_SOURCE
#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include "../source/ui/ui-raster.h"
#include "../source/ui/ui-lz77.h"

static uintptr_t object_base=0x10000000;
static unsigned char *arena, compressed[156], reference[1024];
static unsigned locks, unlocks, events;
static int held, fail_lock, wrong_bits, mutate_lock;
static char last_phase[80];
static jmp_buf failure;
static void put(unsigned offset, uint32_t value) { memcpy(arena+offset,&value,4); }
static uintptr_t source_buffer(uintptr_t input) { assert(input==(uintptr_t)(arena+0x100)); return (uintptr_t)(arena+0x1000); }
static uintptr_t output_bitmap(uintptr_t output) { assert(output==(uintptr_t)(arena+0x200)); return (uintptr_t)(arena+0x500); }
static unsigned native_bits(unsigned format) { assert(format==0x302); return 16; }
static int native_bpp(uint32_t format,int16_t *bpp) { assert(format==1); *bpp=2; return 0; }
static uintptr_t native_lock(uintptr_t output,uint32_t *stride)
{
    assert(output==(uintptr_t)(arena+0x200) && !held);
    ++locks;
    if (fail_lock) return 0;
    held=1; *stride=128;
    if (mutate_lock) put(0x624,0x2276b380);
    return (uintptr_t)(arena+0x2000+(wrong_bits ? 16 : 0));
}
static void native_event(unsigned event,uintptr_t bitmap,int status,int error)
{
    assert(held && bitmap==(uintptr_t)(arena+0x500));
    if (event==4) {
        assert(!events && !status && !error);
        for (unsigned i=0;i<1024;++i) assert(arena[0x2000+i]==0xa5);
    } else {
        assert(event==8 && events==1 && error==(status!=0));
        if (!status) assert(!memcmp(arena+0x2000,reference,sizeof reference));
    }
    ++events;
}
static void native_unlock(uintptr_t output)
{
    assert(output==(uintptr_t)(arena+0x200) && held && events==2);
    held=0; ++unlocks;
}
static uintptr_t native_address(unsigned offset)
{
    switch (offset) {
    case 0x862a69:return (uintptr_t)native_bits;
    case 0x69d145:return (uintptr_t)native_bpp;
    case 0x863889:return (uintptr_t)native_lock;
    case 0x644df1:return (uintptr_t)native_event;
    case 0x86389b:return (uintptr_t)native_unlock;
    default:assert(0);return 0;
    }
}
static void record(const char *name,uintptr_t value) { (void)value; snprintf(last_phase,sizeof last_phase,"%s",name); }
static __attribute__((noreturn)) void fixture_exit(int code) { assert(code==71); longjmp(failure,1); }
#define UI_IMAGE_FN(offset,type) ((type)native_address(offset))
#define _exit fixture_exit
#include "../source/ui/ui-image-decode.h"
#undef _exit

static void load(const char *path,unsigned char *data,size_t length)
{
    FILE *f=fopen(path,"rb"); assert(f);
    assert(fread(data,1,length,f)==length && fgetc(f)==EOF && !ferror(f));
    assert(!fclose(f));
}
static void reset(void)
{
    memset(arena,0,0x4000); memset(arena+0x2000,0xa5,1024);
    locks=unlocks=events=0; held=fail_lock=wrong_bits=mutate_lock=0; last_phase[0]=0;
    put(4,(uintptr_t)(arena+0x100)); put(8,(uintptr_t)(arena+0x200)); put(12,0x302);
    put(16,2u<<16|64); put(20,sizeof compressed);
    put(0x100,(uintptr_t)(arena+0x300)); put(0x200,(uintptr_t)(arena+0x400));
    assert((uintptr_t)source_buffer<0x60000000u && (uintptr_t)output_bitmap<0x60000000u);
    put(0x32c,(uintptr_t)source_buffer); put(0x430,(uintptr_t)output_bitmap);
    put(0x500,object_base+0x13ba5a0); put(0x504,(uintptr_t)(arena+0x600));
    put(0x508,(uintptr_t)(arena+0x2000));
    put(0x608,2u<<16|64); put(0x618,8u<<16|64); put(0x61c,1);
    put(0x624,0x2276a380); put(0x62c,1);
    memcpy(arena+0x1000,compressed,sizeof compressed);
}
static void reject(const char *phase)
{
    if (!setjmp(failure)) { (void)software_lz_decode((uintptr_t)arena,0,0,0); assert(0); }
    assert(!held && !strcmp(last_phase,phase));
    for (unsigned i=0;i<1024;++i) assert(arena[0x2000+i]==0xa5);
}
int main(void)
{
    (void)ui_fill;(void)ui_blit;(void)ui_surface;
    arena=mmap(NULL,0x4000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_32BIT,-1,0);
    assert(arena!=MAP_FAILED && (uintptr_t)arena<0x60000000u-0x4000);
    load("evidence/gemini-assets/border-1a05cb40.lz77",compressed,sizeof compressed);
    load("evidence/gemini-assets/border-sony-reference.raw",reference,sizeof reference);
    reset(); assert(software_lz_decode((uintptr_t)arena,0,0,0)==1);
    assert(!memcmp(arena+0x2000,reference,sizeof reference));
    assert(locks==1 && unlocks==1 && events==2 && !held);
    reset(); arena[0x1000]=0x11; reject("LDEC.cpu.stream"); assert(!locks && !events);
    reset(); put(20,155); reject("LDEC.cpu.stream"); assert(!locks && !events);
    reset(); put(0x62c,0); reject("LDEC.cpu.output_format"); assert(!locks);
    reset(); put(0x618,16u<<16|64); reject("LDEC.cpu.output_span"); assert(!locks);
    reset(); fail_lock=1; reject("LDEC.cpu.write_lock"); assert(locks==1 && !unlocks && !events);
    reset(); wrong_bits=1; reject("LDEC.cpu.changed_output"); assert(locks==unlocks && events==2);
    reset(); mutate_lock=1; reject("LDEC.cpu.changed_output"); assert(locks==unlocks && events==2);
    assert(!munmap(arena,0x4000));
    puts("PASS: authentic LZ image bytes, native write lease/events, private validation before commit and failure cleanup");
    return 0;
}
