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
#include "../source/ui/ui-gemini-raster.h"

static uintptr_t object_base=0x10000000;
static unsigned native_glyph_draws, native_glyph_images;
static uintptr_t native_glyph_bitmaps[64];
static unsigned char *arena, *gpu;
static uintptr_t current_context, current_surface;
static unsigned finishes, locks, unlocks, maps, unmaps;
static int held, fail_lock, fail_map, mutate_lock, mutate_finish, mutate_map, fail_unmap;
static char events[32], last_detail[80];
static unsigned event_count;
static jmp_buf failure;
static void event(char c) { assert(event_count+1 < sizeof events); events[event_count++]=c; events[event_count]=0; }
static void record(const char *name, uintptr_t value)
{
    (void)value;
    if (strncmp(name,"GEMINI.cpu.",11) == 0 && strcmp(name,"GEMINI.cpu.UNSUPPORTED"))
        snprintf(last_detail,sizeof last_detail,"%s",name);
}
struct hook { uint32_t offset; unsigned char prologue[8]; void *replacement; void *original; };
#include "../source/ui/ui-draw-probe.h"

static void put(unsigned offset, uint32_t value) { memcpy(arena+offset,&value,4); }
static uintptr_t thread_data(void) { return (uintptr_t)(arena+0x1f00); }
static uintptr_t thread_context(uintptr_t t) { assert(t == thread_data()); return current_context; }
static uintptr_t thread_surface(uintptr_t t) { assert(t == thread_data()); return current_surface; }
static void native_finish(void)
{
    assert(!held && !maps); ++finishes; event('F');
    memset(gpu,0,640u*480*2); /* Preceding native asynchronous clear is drained here. */
    if (mutate_finish) put(0x908,0x20400000);
}
static int native_lock(uintptr_t bitmap, uint32_t timeout, uint32_t *bits)
{
    assert(finishes == 1 && bitmap == (uintptr_t)(arena+0xb00) && !timeout && !held);
    ++locks; event('L');
    if (fail_lock) return -8;
    held=1; *bits=(uintptr_t)(arena+0x3000);
    if (mutate_lock) put(0xc18,0x00080008);
    return 0;
}
static void native_unlock(uintptr_t bitmap)
{
    assert(bitmap == (uintptr_t)(arena+0xb00) && held);
    held=0; ++unlocks; event('U');
}
static uintptr_t native_address(unsigned offset)
{
    switch (offset) {
    case 0x7bbb31: return (uintptr_t)thread_data;
    case 0x7bbbe1: return (uintptr_t)thread_context;
    case 0x7bbc21: return (uintptr_t)thread_surface;
    case 0x7c0d31: return (uintptr_t)native_finish;
    case 0x69b901: return (uintptr_t)native_lock;
    case 0x69b29d: return (uintptr_t)native_unlock;
    default: assert(0); return 0;
    }
}
struct surface_mapping { void *base; unsigned char *pixels; size_t length; };
static int map_surface(uint32_t physical, size_t span, struct surface_mapping *m)
{
    assert(finishes == 1 && physical == 0x20312200 && span == 640u*480*2);
    ++maps; event('M');
    if (fail_map) return -5;
    m->base=gpu; m->pixels=gpu; m->length=span;
    if (mutate_map) put(0x908,0x20400000);
    return 0;
}
static int fixture_unmap(void *base, size_t length)
{
    assert(base == gpu && length == 640u*480*2 && !held);
    ++unmaps; event('N'); return fail_unmap ? -1 : 0;
}
static __attribute__((noreturn)) void fixture_exit(int status) { assert(status == 71); longjmp(failure,1); }
#define GEMINI_CPU_NATIVE(offset) native_address(offset)
#define munmap fixture_unmap
#define _exit fixture_exit
#include "../source/ui/ui-gemini-backend.h"
#undef _exit
#undef munmap

/* Low-address fixtures preserve the original ARM32 pointer fields on the host. */
static void reset(void)
{
    memset(arena,0,0x4000); memset(gpu,0x55,640u*480*2);
    finishes=locks=unlocks=maps=unmaps=event_count=0;
    held=fail_lock=fail_map=mutate_lock=mutate_finish=mutate_map=fail_unmap=0;
    events[0]=last_detail[0]=0;
    put(0,object_base+0x13bf2e0);
    put(0x2c,1); put(0x30,0x00170067); put(0x34,1); put(0x58,1); put(0x5c,1);
    put(0x60,0); put(0x64,480u<<16|640);
    put(0xa8,0); put(0xac,480u<<16|640); put(0xb8,(uintptr_t)(arena+0xa00));
    put(0x16c,(uintptr_t)(arena+0x600)); put(0x170,(uintptr_t)(arena+0x400));
    put(0x410,2); put(0x42c,(uintptr_t)(arena+0x500)); put(0x500,(uintptr_t)(arena+0x1000));
    put(0x608,1); put(0x614,480); put(0x618,640); put(0x61c,3);
    put(0x630,480); put(0x634,640); put(0x678,(uintptr_t)(arena+0x900));
    put(0x68c,640); put(0x690,480);
    put(0x908,0x20312200); put(0x90c,640u*480*2); put(0x910,1280); put(0x914,0x8001);
    put(0xa00,object_base+0x13bf150); put(0xa14,8u<<16|4); put(0xa1c,0x302);
    put(0xa34,0x00010001); put(0xa38,0x00030003); put(0xa3c,3);
    put(0xa40,7); put(0xa48,(uintptr_t)(arena+0xb00));
    put(0xb00,object_base+0x13ba5a0); put(0xb04,(uintptr_t)(arena+0xc00));
    put(0xb08,(uintptr_t)(arena+0x3000));
    put(0xc08,2u<<16|4); put(0xc18,8u<<16|4); put(0xc1c,1); put(0xc24,0x21000000);
    float matrix[14]={1,0,0,0,0,1,0,0,0,0,1,0,17,174};
    memcpy(arena+0x2000,matrix,sizeof matrix);
    put(0x2100,0xffffffff);
    struct ui_gemini_rect sr={1,0,2,2}, dr={0,0,2,2};
    memcpy(arena+0x2200,&sr,8); memcpy(arena+0x2210,&dr,8);
    float points[]={0,0,0,2,2,2,2,0}; memcpy(arena+0x2240,points,sizeof points);
    for (unsigned i=0;i<8;++i) { uint16_t p=(i&1) ? 0xf00f : 0x00ff; memcpy(arena+0x3000+i*2,&p,2); }
    current_context=(uintptr_t)(arena+0x400); current_surface=(uintptr_t)(arena+0x600);
}

static uintptr_t call(unsigned kind)
{
    uintptr_t r=(uintptr_t)(arena+0x1800), s=(uintptr_t)arena, m=(uintptr_t)(arena+0x2000);
    uintptr_t c=(uintptr_t)(arena+0x2100), sr=(uintptr_t)(arena+0x2200), dr=(uintptr_t)(arena+0x2210);
    if (kind == 0) return software_gemini_solid(r,s,m,c,dr);
    if (kind == 1) return software_gemini_rect(r,s,m,c,sr,dr);
    if (kind == 2) return software_gemini_quad(r,s,m,c,sr,(uintptr_t)(arena+0x2240));
    return software_gemini_line(r,s,m,c,sr,dr);
}
static uint16_t output(unsigned x, unsigned y)
{
    y=479-y;
    size_t index=((y/8)*80+x/8)*64;
    for (unsigned bit=0;bit<3;++bit) {
        index+=((x>>bit)&1)<<(bit*2);
        index+=((y>>bit)&1)<<(bit*2+1);
    }
    return ui_u16(gpu+index*2);
}
static void rejected(unsigned kind, const char *detail)
{
    if (!setjmp(failure)) { (void)call(kind); assert(!"unsupported draw returned success"); }
    assert(!strcmp(last_detail,detail));
    assert(!held);
}
static void unchanged(void)
{
    for (unsigned i=0;i<640u*480*2;++i) assert(gpu[i] == 0x55);
    assert(!maps && !locks && !finishes);
}

int main(void)
{
    (void)ui_fill; (void)ui_blit; (void)ui_surface;
    (void)gemini_probe_solid; (void)gemini_probe_rect; (void)gemini_probe_quad; (void)gemini_probe_line;
    arena=mmap(NULL,0x4000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_32BIT,-1,0);
    gpu=malloc(640u*480*2);
    assert(arena != MAP_FAILED && (uintptr_t)arena <= UINT32_MAX-0x4000 && gpu);
    reset(); assert(call(0) == 1); assert(!strcmp(events,"FMN"));
    assert(output(17,174) == 0xffff && output(18,175) == 0xffff && output(19,175) == 0);
    reset(); assert(call(1) == 1); assert(!strcmp(events,"FLMUN") && locks == unlocks);
    assert(output(17,174) == 0xf00f && output(18,174) == 0x00ff && output(17,175) == 0xf00f);
    reset(); put(0x2100,0x80ffffff); assert(call(1)==1); assert(output(17,174)==0x8008);
    reset(); put(0xc2c,1); put(0xa44,1); put(0xa14,8u<<16|8); put(0xc18,8u<<16|8);
    for (unsigned code=0;code<64;++code) {
        unsigned x=0,y=0;
        for (unsigned bit=0;bit<3;++bit) {
            x+=((code>>(bit*2))&1)<<bit;
            y+=((code>>(bit*2+1))&1)<<bit;
        }
        uint16_t value=y==0 ? ((x&1) ? 0xf00f : 0x00ff) :
                       y==1 ? ((x&1) ? 0x0f0f : 0xffff) : 0x1234;
        memcpy(arena+0x3000+code*2,&value,2);
    }
    assert(call(1)==1 && !strcmp(events,"FLMUN"));
    assert(output(17,174)==0xf00f && output(18,174)==0x00ff && output(17,175)==0x0f0f);
    reset(); assert(call(2) == 1); assert(!strcmp(events,"FLMUN"));
    assert(output(17,174) == 0xf00f && output(18,175) == 0x00ff);
    reset(); put(0xa1c,8); put(0xa40,8); put(0xc1c,4); put(0x2100,0x800000ff);
    memset(arena+0x3000,255,32); assert(call(1) == 1); assert(output(17,174) == 0x8008);
    reset(); put(0xa1c,0x304); put(0xa40,8); put(0xa44,1); put(0xc1c,4);
    put(0xc2c,1); put(0xa14,8u<<16|8); put(0xc18,8u<<16|8);
    for (unsigned code=0;code<64;++code) {
        unsigned x=0,y=0;
        for (unsigned bit=0;bit<3;++bit) {
            x+=((code>>(bit*2))&1)<<bit;
            y+=((code>>(bit*2+1))&1)<<bit;
        }
        arena[0x3000+code]=(unsigned char)((x+y)&1 ? 255 : 0);
    }
    assert(call(1)==1 && !strcmp(events,"FLMUN"));
    assert(output(17,174)==0xffff && output(18,174)==0 && output(17,175)==0);
    reset();
    /* Only the proven last affine field at +0x34 is readable; the rest of a
     * guessed 4x4 matrix would cross into the protected next page. */
    uintptr_t guarded=(uintptr_t)(arena+0x3000-0x38);
    memcpy((void *)guarded,arena+0x2000,0x38);
    assert(!mprotect(arena+0x3000,0x1000,PROT_NONE));
    assert(software_gemini_solid((uintptr_t)(arena+0x1800),(uintptr_t)arena,guarded,
                                 (uintptr_t)(arena+0x2100),(uintptr_t)(arena+0x2210)) == 1);
    assert(!mprotect(arena+0x3000,0x1000,PROT_READ|PROT_WRITE));

    reset(); current_context=0; rejected(0,"GEMINI.cpu.current_or_default_target"); unchanged();
    reset(); current_surface+=4; rejected(0,"GEMINI.cpu.current_or_default_target"); unchanged();
    reset(); put(0x184c,1); rejected(0,"GEMINI.cpu.context_or_batch"); unchanged();
    reset(); put(0x1858,1); rejected(0,"GEMINI.cpu.context_or_batch"); unchanged();
    reset(); put(0x1860,0x00010000); rejected(0,"GEMINI.cpu.context_or_batch"); unchanged();
    reset(); put(0x148,(uintptr_t)(arena+0xd00)); rejected(0,"GEMINI.cpu.current_or_default_target"); unchanged();
    unsigned fields[]={0x16d0,0x608,0x61c,0x614,0x618,0x630,0x634,0x68c,0x690,
                       0x908,0x90c,0x910,0x914,0x918};
    for (unsigned i=0;i<sizeof fields/sizeof fields[0];++i) {
        reset(); put(fields[i],gemini_probe_read((uintptr_t)arena,fields[i]) ^ 1);
        rejected(0,"GEMINI.cpu.current_or_default_target"); unchanged();
    }
    reset(); put(0xc2c,2); rejected(1,"GEMINI.cpu.source_sorting"); unchanged();
    reset(); put(0xc2c,1); rejected(1,"GEMINI.cpu.source_sorting"); unchanged();
    reset(); put(0xc04,1); rejected(1,"GEMINI.cpu.source_origin"); unchanged();
    reset(); put(0xc30,1); rejected(1,"GEMINI.cpu.source_start"); unchanged();
    reset(); put(0xc24,0x20312200); rejected(1,"GEMINI.cpu.source_span_or_alias"); unchanged();
    reset(); put(0xa40,6); rejected(1,"GEMINI.cpu.source_format"); unchanged();
    reset(); put(0xa34,0x00020001); rejected(1,"GEMINI.cpu.source_filter"); unchanged();
    reset(); put(0x2214,2u<<16|3); rejected(1,"GEMINI.cpu.source_filter_scale"); unchanged();
    reset(); put(0x2030,0x3f000000); rejected(1,"GEMINI.cpu.source_filter_transform"); unchanged();
    reset(); rejected(3,"GEMINI.cpu.line"); unchanged();

    reset(); mutate_finish=1; rejected(1,"GEMINI.cpu.changed_during_finish");
    assert(!strcmp(events,"F") && !locks && !maps);
    reset(); fail_lock=1; rejected(1,"GEMINI.cpu.read_lock"); assert(!strcmp(events,"FL") && !unlocks);
    reset(); mutate_lock=1; rejected(1,"GEMINI.cpu.changed_during_lock"); assert(!strcmp(events,"FLU") && !maps);
    reset(); mutate_map=1; rejected(1,"GEMINI.cpu.changed_during_map"); assert(!strcmp(events,"FLMUN"));
    reset(); fail_map=1; rejected(1,"GEMINI.cpu.map_target"); assert(!strcmp(events,"FLMU") && !unmaps);
    reset(); put(0x30,0x0017006a); rejected(1,"GEMINI.cpu.raster"); assert(!strcmp(events,"FLMUN"));
    for (unsigned i=0;i<640u*480*2;++i) assert(!gpu[i]); /* Finish clear only, no rejected CPU draw. */
    reset(); fail_unmap=1; rejected(1,"GEMINI.cpu.unmap_target"); assert(!strcmp(events,"FLMUN"));
    assert(!munmap(arena,0x4000)); free(gpu);
    puts("PASS: native target/current context, original finish before writes, rect/solid/quad/A8, read lease lifetime, metadata stability, terminal rejection and cleanup");
    return 0;
}
