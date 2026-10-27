#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "../source/ui/ui-raster.h"
#include "../source/ui/ui-gemini-raster.h"
#include "../source/ui/ui-present.h"

static const float identity[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
static const unsigned char white[4] = {255,255,255,255};

static struct ui_gemini_state state_for(unsigned w, unsigned h)
{
    struct ui_gemini_state s = {.viewport={0,0,(int16_t)w,(int16_t)h}, .rgb_write=1, .alpha_write=1};
    return s;
}

static uint16_t pixel(const struct ui_gemini_surface *s, unsigned x, unsigned y)
{
    return ui_u16(s->pixels + (size_t)y * s->stride + x * 2);
}

static void put16(unsigned char *p, uint16_t n) { memcpy(p, &n, 2); }

static void test_geometry(void)
{
    unsigned char bytes[128];
    memset(bytes, 0x5a, sizeof bytes);
    struct ui_gemini_surface d = {bytes+4,120,8,6,20,0,UI_GEMINI_LINEAR};
    struct ui_gemini_state s = state_for(5,4);
    s.viewport.x = s.viewport.y = 1;
    s.scissor_enabled = 1;
    s.scissor = (struct ui_gemini_rect){2,2,3,3}; /* top 1, bottom 4 */
    float m[16]; memcpy(m, identity, sizeof m);
    m[0] = 1.5f; m[12] = 0.5f; m[13] = 1;
    struct ui_gemini_rect r = {-2,-1,6,4};
    unsigned char color[4] = {17,136,238,255};
    assert(!ui_gemini_rect(&d,NULL,&s,m,color,NULL,&r,0));
    for (unsigned y = 0; y < 6; ++y) {
        for (unsigned x = 0; x < 8; ++x)
            assert(pixel(&d,x,y) == (x >= 2 && x < 5 && y >= 1 && y < 4 ? 0x18ef : 0x5a5a));
        for (unsigned x = 16; x < 20; ++x) assert(d.pixels[y*20+x] == 0x5a);
    }
    for (unsigned i = 0; i < 4; ++i) assert(bytes[i] == 0x5a && bytes[124+i] == 0x5a);
    /* Fractional edges use pixel centers and a half-open right/bottom edge. */
    memset(d.pixels,0,120);
    s = state_for(8,6);
    r = (struct ui_gemini_rect){0,0,1,1};
    m[0] = m[5] = 2; m[12] = m[13] = 0.5f;
    assert(!ui_gemini_rect(&d,NULL,&s,m,white,NULL,&r,0));
    for (unsigned y = 0; y < 6; ++y) for (unsigned x = 0; x < 8; ++x)
        assert(pixel(&d,x,y) == (x < 2 && y < 2 ? 0xffff : 0));
    r.x = -32768; r.y = 32767; /* valid signed position, fully clipped */
    unsigned char saved[128]; memcpy(saved,bytes,sizeof bytes);
    assert(!ui_gemini_rect(&d,NULL,&s,m,white,NULL,&r,0));
    assert(!memcmp(bytes,saved,sizeof bytes));
}

static void test_mask_and_quad(void)
{
    unsigned char bytes[8*6*2] = {0}, mask[] = {99,0,85,99, 99,170,255,99};
    struct ui_gemini_surface d = {bytes,sizeof bytes,8,6,16,0,0};
    struct ui_gemini_surface src = {mask,sizeof mask,4,2,4,3,0};
    struct ui_gemini_state s = state_for(8,6);
    struct ui_gemini_rect sr = {1,0,2,2}, dr = {-1,0,4,4};
    unsigned char tint[] = {34,153,238,153};
    /* Left destination clipping retains the original 2x sampling phase;
     * source crop excludes both 99-valued border columns. */
    assert(!ui_gemini_rect(&d,&src,&s,identity,tint,&sr,&dr,UI_GEMINI_ALPHA_MASK));
    for (unsigned y = 0; y < 6; ++y) for (unsigned x = 0; x < 8; ++x) {
        uint16_t expected = 0;
        if (x < 3 && y < 4) {
            static const unsigned alpha[2][2] = {{0,3},{6,9}};
            expected = 0x29e0 | alpha[y/2][(x+1)/2];
        }
        assert(pixel(&d,x,y) == expected);
    }
    unsigned char copy[sizeof bytes]; memcpy(copy,bytes,sizeof bytes);
    memset(bytes,0,sizeof bytes);
    float points[] = {-1,0, -1,4, 3,4, 3,0};
    assert(!ui_gemini_quad(&d,&src,&s,identity,tint,&sr,points,UI_GEMINI_ALPHA_MASK));
    assert(!memcmp(bytes,copy,sizeof bytes));
    points[6] = 4; /* trapezoid is unsupported, without partial output */
    assert(ui_gemini_quad(&d,&src,&s,identity,tint,&sr,points,UI_GEMINI_ALPHA_MASK) == -5);
    assert(!memcmp(bytes,copy,sizeof bytes));
    points[6] = NAN;
    assert(ui_gemini_quad(&d,&src,&s,identity,tint,&sr,points,UI_GEMINI_ALPHA_MASK) == -5);
    assert(!memcmp(bytes,copy,sizeof bytes));
}

static void test_blending(void)
{
    unsigned char bytes[2], texture[2];
    struct ui_gemini_surface d = {bytes,2,1,1,2,0,0}, src = {texture,2,1,1,2,0,0};
    struct ui_gemini_state s = state_for(1,1);
    struct ui_gemini_rect r = {0,0,1,1};
    put16(texture,0xf008); put16(bytes,0x00f4);
    s.blend_enabled = 1;
    s.blend = 0x00170067; /* RGB SRC_ALPHA / ONE_MINUS_SRC_ALPHA, alpha ONE / ONE_MINUS_SRC_ALPHA */
    assert(!ui_gemini_rect(&d,&src,&s,identity,white,&r,&r,UI_GEMINI_TEXTURE));
    assert(pixel(&d,0,0) == 0x807a); /* RGB 136/0/119, alpha 168 */
    put16(bytes,0x00f4); s.alpha_write = 0;
    assert(!ui_gemini_rect(&d,&src,&s,identity,white,&r,&r,UI_GEMINI_TEXTURE));
    assert(pixel(&d,0,0) == 0x8074);
    put16(bytes,0x00f4); s.alpha_write = 1; s.rgb_write = 0;
    assert(!ui_gemini_rect(&d,&src,&s,identity,white,&r,&r,UI_GEMINI_TEXTURE));
    assert(pixel(&d,0,0) == 0x00fa);
    s.rgb_write = 1; s.blend_enabled = 0;
    unsigned char tint[] = {136,255,255,136};
    assert(!ui_gemini_rect(&d,&src,&s,identity,tint,&r,&r,UI_GEMINI_MULTIPLY));
    assert(pixel(&d,0,0) == 0x8004);
    assert(!ui_gemini_rect(&d,&src,&s,identity,tint,&r,&r,UI_GEMINI_TEXTURE));
    assert(pixel(&d,0,0) == 0xf008); /* texture-only ignores current color */

    /* Each native factor with every equation, independently calculated in
     * normalized double precision; test RGB/alpha independently and clamp. */
    unsigned char color[] = {51,102,153,204};
    const unsigned old[] = {204,153,102,51};
    for (unsigned sf = 0; sf < 10; ++sf) for (unsigned df = 0; df < 10; ++df)
        for (unsigned eq = 0; eq < 3; ++eq) {
            unsigned b = (eq << 12) | (sf << 4) | df;
            s.blend_enabled = 1; s.blend = b | b << 16;
            put16(bytes,0xc963);
            assert(!ui_gemini_rect(&d,NULL,&s,identity,color,NULL,&r,0));
            uint16_t expected = 0;
            for (unsigned i = 0; i < 4; ++i) {
                double factors[] = {0,1,color[i]/255.0,1-color[i]/255.0,
                                    old[i]/255.0,1-old[i]/255.0,color[3]/255.0,
                                    1-color[3]/255.0,old[3]/255.0,1-old[3]/255.0};
                double a = color[i]*factors[sf], dval = old[i]*factors[df];
                double v = eq == 0 ? a+dval : (eq == 1 ? a-dval : dval-a);
                unsigned result = v <= 0 ? 0 : (v >= 255 ? 255 : (unsigned)(v+0.5));
                expected |= (result >> 4) << (12-4*i);
            }
            assert(pixel(&d,0,0) == expected);
        }
}

static void test_rejection(void)
{
    unsigned char bytes[136], source[8], saved[sizeof bytes];
    memset(bytes,0x63,sizeof bytes); memset(source,0xff,sizeof source);
    memcpy(saved,bytes,sizeof bytes);
    struct ui_gemini_surface d = {bytes+4,128,8,8,16,0,0};
    struct ui_gemini_surface src = {source,sizeof source,2,2,4,0,0};
    struct ui_gemini_state s = state_for(8,8);
    struct ui_gemini_rect r = {0,0,8,8}, sr = {0,0,2,2};
    float m[16]; memcpy(m,identity,sizeof m);
#define REJECT() do { \
    assert(ui_gemini_rect(&d,&src,&s,m,white,&sr,&r,UI_GEMINI_TEXTURE) == -5); \
    assert(!memcmp(bytes,saved,sizeof bytes)); \
} while (0)
    m[1] = 1; REJECT(); m[1] = 0;
    m[4] = 1; REJECT(); m[4] = 0;
    m[0] = -1; REJECT(); m[0] = 0; REJECT(); m[0] = 1;
    for (unsigned i = 0; i < 16; ++i) {
        float old = m[i]; m[i] = NAN; REJECT(); m[i] = INFINITY; REJECT(); m[i] = old;
    }
    d.capacity--; REJECT(); d.capacity++;
    src.capacity--; REJECT(); src.capacity++;
    d.stride = 15; REJECT(); d.stride = 16;
    d.format = 3; REJECT(); d.format = 0;
    src.format = 1; REJECT(); src.format = 0;
    d.layout = UI_GEMINI_MORTON_TOP_DOWN + 1; REJECT(); d.layout = 0;
    d.width = 8193; REJECT(); d.width = 8;
    d.height = 0; REJECT(); d.height = 8;
    d.pixels = NULL; REJECT(); d.pixels = bytes+4;
    r.w = -1; REJECT(); r.w = 0; REJECT(); r.w = 8;
    sr.x = -1; REJECT(); sr.x = 1; REJECT(); sr.x = 0;
    sr.h = 0; REJECT(); sr.h = 2;
    s.scissor_enabled = 1; s.scissor.w = -1; REJECT(); s.scissor_enabled = 0;
    s.viewport.h = 0; REJECT(); s.viewport.h = 8;
    s.rgb_write = 2; REJECT(); s.rgb_write = 1;
    s.alpha_write = 2; REJECT(); s.alpha_write = 1;
    s.blend_enabled = 2; REJECT(); s.blend_enabled = 0;
    s.scissor_enabled = 2; REJECT(); s.scissor_enabled = 0;
    unsigned bad[] = {0xa,0xa0,0x3000,0x100,0x8000,0x7fff};
    for (unsigned i = 0; i < sizeof bad/sizeof bad[0]; ++i) {
        s.blend = bad[i]; REJECT(); s.blend = bad[i] << 16; REJECT();
    }
    s.blend = 0;
    src.pixels = d.pixels; REJECT(); src.pixels = source;
    src.layout = UI_GEMINI_MORTON_BOTTOM_UP; REJECT(); src.layout = 0;
    assert(ui_gemini_rect(&d,&src,&s,m,white,&sr,&r,UI_GEMINI_ALPHA_MASK) == -5);
    src.format = 3;
    REJECT(); /* A8 requires the proven alpha-mask shader */
    assert(ui_gemini_rect(&d,&src,&s,m,white,&sr,&r,99) == -5);
    assert(ui_gemini_rect(&d,NULL,&s,m,white,NULL,NULL,0) == -5);
    assert(!memcmp(bytes,saved,sizeof bytes));
#undef REJECT
}

static void test_source_topdown(void)
{
    unsigned char raw[1028], output[260];
    memset(raw,0xa5,sizeof raw); memset(output,0x5a,sizeof output);
    for (unsigned tile=0;tile<8;++tile) for (unsigned code=0;code<64;++code) {
        unsigned x=tile*8,y=0;
        for (unsigned bit=0;bit<3;++bit) {
            x+=((code>>(bit*2))&1)<<bit;
            y+=((code>>(bit*2+1))&1)<<bit;
        }
        uint16_t value=y<2 ? (uint16_t)(((y+1)<<12)|((x&15)<<8)|15) : 0x9876;
        memcpy(raw+2+(tile*64+code)*2,&value,2);
    }
    struct ui_gemini_surface src={raw+2,1024,64,2,128,0,UI_GEMINI_MORTON_TOP_DOWN};
    struct ui_gemini_surface dst={output+2,256,64,2,128,0,UI_GEMINI_LINEAR};
    struct ui_gemini_state state=state_for(64,2);
    struct ui_gemini_rect rect={0,0,64,2};
    assert(!ui_gemini_rect(&dst,&src,&state,identity,white,&rect,&rect,UI_GEMINI_TEXTURE));
    for (unsigned y=0;y<2;++y) for (unsigned x=0;x<64;++x)
        assert(ui_u16(output+2+(y*64+x)*2)==(((y+1)<<12)|((x&15)<<8)|15));
    assert(output[0]==0x5a && output[1]==0x5a && output[258]==0x5a && output[259]==0x5a);
    assert(raw[0]==0xa5 && raw[1027]==0xa5);
}

static void test_alpha_tiles(void)
{
    unsigned char source[16*8],output[14*2*2];
    memset(source,0x96,sizeof source);memset(output,0,sizeof output);
    for (unsigned tile=0;tile<2;++tile) for (unsigned code=0;code<64;++code) {
        unsigned x=tile*8,y=0;
        for (unsigned bit=0;bit<3;++bit) {
            x+=((code>>(bit*2))&1)<<bit;
            y+=((code>>(bit*2+1))&1)<<bit;
        }
        source[tile*64+code]=(unsigned char)(y<2 ? (x+y)*17 : 0x96);
    }
    struct ui_gemini_surface src={source,sizeof source,14,2,16,3,UI_GEMINI_MORTON_TOP_DOWN};
    struct ui_gemini_surface dst={output,sizeof output,14,2,28,0,UI_GEMINI_LINEAR};
    struct ui_gemini_state state=state_for(14,2);
    struct ui_gemini_rect rect={0,0,14,2};
    const unsigned char color[4]={255,34,51,255};
    assert(!ui_gemini_rect(&dst,&src,&state,identity,color,&rect,&rect,UI_GEMINI_ALPHA_MASK));
    for (unsigned y=0;y<2;++y) for (unsigned x=0;x<14;++x)
        assert(ui_u16(output+(y*14+x)*2)==(0xf230u|((x+y)&15)));
}

static void test_present_roundtrip(void)
{
    size_t n = UI_PRESENT_BYTES;
    unsigned char *linear = malloc(n+4), *tiled = malloc(n+4), *out = malloc(n+4);
    assert(linear && tiled && out);
    memset(linear,0x39,n+4); memset(tiled,0x39,n+4); memset(out,0x72,n+4);
    struct ui_gemini_surface d = {linear+2,n,640,480,1280,0,UI_GEMINI_LINEAR};
    struct ui_gemini_surface t = {tiled+2,n,640,480,1280,0,UI_GEMINI_MORTON_BOTTOM_UP};
    struct ui_gemini_state s = state_for(640,480);
    struct ui_gemini_rect r = {0,0,640,480};
    assert(!ui_gemini_rect(&d,NULL,&s,identity,white,NULL,&r,0));
    assert(!ui_gemini_rect(&t,NULL,&s,identity,white,NULL,&r,0));
    for (int y = 0; y < 480; y += 7) {
        unsigned char color[] = {(unsigned char)y,(unsigned char)(y*3),51,(unsigned char)(255-y)};
        r = (struct ui_gemini_rect){(int16_t)(y%19-3),(int16_t)y,640,5};
        assert(!ui_gemini_rect(&d,NULL,&s,identity,color,NULL,&r,0));
        assert(!ui_gemini_rect(&t,NULL,&s,identity,color,NULL,&r,0));
    }
    uint32_t p[14] = {0x20312200,0x22bb2000,0,4,0,0x4401,640,480,640,480,0,0,640,480};
    assert(!ui_present_copy(out+2,n,t.pixels,n,p));
    assert(!memcmp(d.pixels,out+2,n));
    /* Texture across every tile and edge also exercises reading tile storage. */
    struct ui_gemini_rect sr = {0,0,640,480};
    r = (struct ui_gemini_rect){-17,-13,660,500};
    s.blend_enabled = 1; s.blend = 0x00170067;
    assert(!ui_gemini_rect(&d,&t,&s,identity,white,&sr,&r,UI_GEMINI_TEXTURE));
    s.blend_enabled = 0;
    assert(!ui_gemini_rect(&t,&d,&s,identity,white,&sr,&sr,UI_GEMINI_TEXTURE));
    assert(!ui_present_copy(out+2,n,t.pixels,n,p));
    assert(!memcmp(d.pixels,out+2,n));
    for (unsigned i = 0; i < 2; ++i) {
        assert(linear[i] == 0x39 && linear[n+2+i] == 0x39);
        assert(tiled[i] == 0x39 && tiled[n+2+i] == 0x39);
        assert(out[i] == 0x72 && out[n+2+i] == 0x72);
    }
    free(linear); free(tiled); free(out);
}

static void test_partial_tile(void)
{
    unsigned char bytes[132]; memset(bytes,0x5a,sizeof bytes);
    struct ui_gemini_surface d = {bytes+2,128,5,5,16,0,UI_GEMINI_MORTON_BOTTOM_UP};
    struct ui_gemini_state s = state_for(5,5);
    struct ui_gemini_rect r = {0,0,5,1};
    d.capacity = 80; /* Logical rows alone do not cover the final whole tile. */
    assert(ui_gemini_rect(&d,NULL,&s,identity,white,NULL,&r,0) == -5);
    for (unsigned i = 0; i < sizeof bytes; ++i) assert(bytes[i] == 0x5a);
    d.capacity = 128;
    assert(!ui_gemini_rect(&d,NULL,&s,identity,white,NULL,&r,0));
    for (unsigned code = 0; code < 64; ++code) {
        unsigned x = 0, y = 0;
        for (unsigned bit = 0; bit < 3; ++bit) {
            x |= ((code >> (bit*2)) & 1) << bit;
            y |= ((code >> (bit*2+1)) & 1) << bit;
        }
        assert(ui_u16(d.pixels+code*2) == (x < 5 && y == 4 ? 0xffff : 0x5a5a));
    }
    assert(bytes[0] == 0x5a && bytes[1] == 0x5a && bytes[130] == 0x5a && bytes[131] == 0x5a);
}

static void test_slow_clear(void)
{
    unsigned char *tiled=malloc(UI_PRESENT_BYTES+4), *linear=malloc(UI_PRESENT_BYTES);
    assert(tiled && linear);
    uint32_t present[14]={0x20312200,0x22bb2000,0,4,0,0x4401,640,480,640,480,0,0,640,480};
    const uint32_t regions[][4]={{0,414,640,66},{17,104,50,2}};
    for (unsigned r=0;r<2;++r) {
        memset(tiled,0x5a,UI_PRESENT_BYTES+4);
        assert(!ui_slow_clear_pixels(tiled+2,UI_PRESENT_BYTES,regions[r]));
        assert(!ui_present_copy(linear,UI_PRESENT_BYTES,tiled+2,UI_PRESENT_BYTES,present));
        for (unsigned y=0;y<480;++y) for (unsigned x=0;x<640;++x) {
            int inside=x>=regions[r][0] && x<regions[r][0]+regions[r][2] &&
                y>=480-regions[r][1]-regions[r][3] && y<480-regions[r][1];
            assert(ui_u16(linear+(y*640+x)*2)==(inside ? 0 : 0x5a5a));
        }
        assert(tiled[0]==0x5a && tiled[1]==0x5a && tiled[UI_PRESENT_BYTES+2]==0x5a);
    }
    memset(tiled,0x5a,UI_PRESENT_BYTES+4);
    const uint32_t outside[4]={639,0,2,1};
    assert(ui_slow_clear_pixels(tiled+2,UI_PRESENT_BYTES,outside)==-5);
    assert(ui_slow_clear_pixels(tiled+2,UI_PRESENT_BYTES-1,regions[0])==-5);
    for (size_t i=0;i<UI_PRESENT_BYTES+4;++i) assert(tiled[i]==0x5a);
    free(tiled);free(linear);
}

int main(void)
{
    (void)ui_fill; (void)ui_blit; (void)ui_surface;
    test_geometry();
    test_mask_and_quad();
    test_blending();
    test_rejection();
    test_source_topdown();
    test_alpha_tiles();
    test_present_roundtrip();
    test_partial_tile();
    test_slow_clear();
    puts("PASS: original Gemini rect/quad affine, viewport/scissor, A8/RGBA4444, native blend/masks, atomic rejection, Morton-bottom-up present and bounds");
    return 0;
}
