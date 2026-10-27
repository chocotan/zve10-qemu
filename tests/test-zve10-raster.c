#include <assert.h>
#include <stdio.h>
#include "../source/ui/ui-raster.h"
static void p16(unsigned char *p, int n) { uint16_t v=n; memcpy(p,&v,2); }
static void p32(unsigned char *p, uint32_t n) { memcpy(p,&n,4); }
int main(void)
{
    unsigned char fill[48]={0}, pixels[128], source[64], blit[156]={0};
    memset(pixels,0x5a,sizeof pixels);
    p16(fill+4,8); p16(fill+6,8); p16(fill+8,1); p16(fill+10,2);
    p16(fill+12,3); p16(fill+14,2); fill[28]=255; fill[31]=255; fill[32]=255;
    assert(!ui_fill(pixels,sizeof pixels,fill));
    assert(ui_u16(pixels+(2*8+1)*2)==0xf00f);
    assert(ui_u16(pixels+(3*8+3)*2)==0xf00f);
    assert(ui_u16(pixels+(3*8+4)*2)==0x5a5a);
    assert(ui_fill(pixels,4,fill)==-5);
    p32(fill+20,1); assert(ui_fill(pixels,sizeof pixels,fill)==-5); p32(fill+20,0);
    memset(pixels,0,sizeof pixels); memset(source,255,sizeof source);
    p16(blit+4,8); p16(blit+6,8); p16(blit+12,8); p16(blit+14,8); p32(blit+16,3);
    p16(blit+28,8); p16(blit+30,8); p16(blit+36,8); p16(blit+38,8);
    p16(blit+44,8); p16(blit+46,8); blit[60]=255; p32(blit+68,1); p32(blit+140,0x3f800000);
    assert(!ui_blit(pixels,sizeof pixels,source,sizeof source,blit));
    assert(ui_u16(pixels)==0xffff && ui_u16(pixels+126)==0xffff);
    memset(source,0,sizeof source);
    assert(!ui_blit(pixels,sizeof pixels,source,sizeof source,blit));
    assert(ui_u16(pixels)==0xffff);
    p16(blit+8,7); assert(ui_blit(pixels,sizeof pixels,source,sizeof source,blit)==-5); p16(blit+8,0);
    p32(blit+144,0x20); assert(ui_blit(pixels,sizeof pixels,source,sizeof source,blit)==-5);
    puts("PASS: ARM32 fill, clipping, alpha8 source-over, capacity and unsupported-layout checks");
}
