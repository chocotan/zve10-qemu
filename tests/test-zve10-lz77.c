#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "../source/ui/ui-lz77.h"

/* Firmware-derived fixtures are not distributed; skip the real-asset cases without them. */
static void load(const char *path, unsigned char *data, size_t length)
{
    FILE *f=fopen(path,"rb");
    if (!f) {
        printf("SKIP: firmware-derived fixture %s is absent; synthetic codec cases already passed\n",path);
        exit(0);
    }
    assert(fread(data,1,length,f)==length && fgetc(f)==EOF && !ferror(f));
    assert(!fclose(f));
}
int main(void)
{
    unsigned char target[1030];
    memset(target,0xa5,sizeof target);
    const unsigned char raw[]={0x0f,0,3,0,0xaa,0xbb,0xcc};
    assert(!ui_lz77_decode(raw,sizeof raw,target+2,3));
    assert(!memcmp(target+2,raw+4,3) && target[1]==0xa5 && target[5]==0xa5);
    const unsigned char literals[]={0xf0,0,'A','B','C','D','E','F','G','H',1,0,0};
    assert(!ui_lz77_decode(literals,sizeof literals,target+2,8));
    assert(!memcmp(target+2,"ABCDEFGH",8));
    const unsigned lengths[]={3,4,5,6,7,8,9,10,11,12,13,14,15,16,32,64};
    for (unsigned i=0;i<16;++i) {
        unsigned char stream[]={0xf0,6,'A',(unsigned char)(i<<4),1,0,0};
        memset(target,0xa5,sizeof target);
        assert(!ui_lz77_decode(stream,sizeof stream,target+2,lengths[i]+1));
        for (unsigned j=0;j<=lengths[i];++j) assert(target[j+2]=='A');
        assert(target[1]==0xa5 && target[lengths[i]+3]==0xa5);
        assert(ui_lz77_decode(stream,sizeof stream,target+2,lengths[i])==-5);
        for (size_t n=0;n<sizeof stream;++n)
            assert(ui_lz77_decode(stream,n,target+2,lengths[i]+1)==-5);
    }
    const unsigned char before_history[]={0xf0,1,0,1,0,0};
    const unsigned char early_end[]={0xf0,1,0,0};
    const unsigned char unknown[]={0x11,0,0,0};
    assert(ui_lz77_decode(before_history,sizeof before_history,target+2,8)==-5);
    assert(ui_lz77_decode(early_end,sizeof early_end,target+2,8)==-5);
    assert(ui_lz77_decode(unknown,sizeof unknown,target+2,8)==-5);
    assert(ui_lz77_decode(raw,sizeof raw,target+2,2)==-5);
    assert(ui_lz77_decode(NULL,4,target+2,8)==-5);
    assert(ui_lz77_decode(raw,sizeof raw,(unsigned char *)raw,3)==-5);
    unsigned char compressed[156],reference[1024];
    load("evidence/gemini-assets/border-1a05cb40.lz77",compressed,sizeof compressed);
    load("evidence/gemini-assets/border-sony-reference.raw",reference,sizeof reference);
    memset(target,0xa5,sizeof target);
    assert(!ui_lz77_decode(compressed,sizeof compressed,target+2,sizeof reference));
    assert(!memcmp(target+2,reference,sizeof reference));
    assert(target[0]==0xa5 && target[1]==0xa5 && target[1026]==0xa5 && target[1027]==0xa5);
    for (size_t n=0;n<sizeof compressed;++n)
        assert(ui_lz77_decode(compressed,n,target+2,sizeof reference)==-5);
    assert(ui_lz77_decode(compressed,sizeof compressed,target+2,sizeof reference-1)==-5);
    assert(ui_lz77_decode(compressed,sizeof compressed,target+2,sizeof reference+1)==-5);
    unsigned char icon[2405], decoded[8064], expected[8064];
    load("evidence/gemini-assets/icon-70x55-0.lz77",icon,sizeof icon);
    load("evidence/gemini-assets/icon-70x55-sony-reference.raw",expected,sizeof expected);
    assert(!ui_lz77_decode(icon,sizeof icon,decoded,sizeof decoded));
    assert(!memcmp(decoded,expected,sizeof decoded));
    const unsigned char cross_record[]={0x0f,0,1,0,'A',0xf0,3,0,1,0,0};
    assert(ui_lz77_decode(cross_record,sizeof cross_record,decoded,4)==-5);
    unsigned char pair[sizeof raw+sizeof literals];
    memcpy(pair,raw,sizeof raw);memcpy(pair+sizeof raw,literals,sizeof literals);
    assert(!ui_lz77_decode(pair,sizeof pair,decoded,11));
    assert(!memcmp(decoded,raw+4,3) && !memcmp(decoded+3,"ABCDEFGH",8));
    puts("PASS: Sony LZ77 block histories, all match lengths, exact end/size, bounds, native border and multi-record 70x55 icon");
    return 0;
}
