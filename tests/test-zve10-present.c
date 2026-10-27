#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "../source/ui/ui-present.h"

int main(void)
{
    uint32_t p[14] = {0x20312200,0x22bb2000,0,4,0,0x4401,640,480,640,480,0,0,640,480};
    size_t span = UI_PRESENT_BYTES;
    unsigned char *source = malloc(span + 4), *destination = malloc(span + 4);
    assert(source && destination);
    memset(source,0xa3,span + 4);
    memset(destination,0xcc,span + 4);
    /* Independent tile-major fixture decodes interleaved coordinates, including every edge row. */
    for (unsigned ty = 0; ty < 60; ++ty)
        for (unsigned tx = 0; tx < 80; ++tx)
            for (unsigned code = 0; code < 64; ++code) {
                unsigned x = tx * 8, y = ty * 8;
                for (unsigned bit = 0; bit < 3; ++bit) {
                    x += ((code >> (2 * bit)) & 1) << bit;
                    y += ((code >> (2 * bit + 1)) & 1) << bit;
                }
                unsigned pixel = (y * 640 + x) % 65535 + 1;
                size_t offset = 2 + ((ty * 80 + tx) * 64 + code) * 2;
                source[offset] = pixel & 255;
                source[offset + 1] = pixel >> 8;
            }
    assert(ui_present_span(p) == span);
    assert(ui_present_copy(destination + 2,span,source + 2,span,p) == 0);
    for (unsigned y = 0; y < 480; ++y)
        for (unsigned x = 0; x < 640; ++x) {
            size_t offset = 2 + (y * 640 + x) * 2;
            unsigned pixel = destination[offset] | (unsigned)destination[offset + 1] << 8;
            assert(pixel == ((479 - y) * 640 + x) % 65535 + 1);
        }
    assert(destination[0] == 0xcc && destination[1] == 0xcc);
    assert(destination[span + 2] == 0xcc && destination[span + 3] == 0xcc);
    assert(source[0] == 0xa3 && source[span + 3] == 0xa3);
    memset(destination,0xcc,span + 4);
    for (unsigned i = 2; i < 14; ++i) {
        p[i] ^= 1;
        assert(!ui_present_span(p));
        assert(ui_present_copy(destination + 2,span,source + 2,span,p) == -5);
        p[i] ^= 1;
    }
    assert(ui_present_copy(destination + 2,span - 1,source + 2,span,p) == -5);
    assert(ui_present_copy(destination + 2,span,source + 2,span - 1,p) == -5);
    assert(ui_present_copy(source + 2,span,source + 3,span,p) == -5);
    for (size_t i = 0; i < span + 4; ++i) assert(destination[i] == 0xcc);
    p[1] = p[0] + 2;
    assert(!ui_present_span(p));
    p[1] = 0x28000000u - UI_PRESENT_BYTES;
    assert(ui_present_span(p) == span);
    ++p[1];
    assert(!ui_present_span(p));
    assert(!ui_present_span(NULL));
    uint32_t clear[32] = {0};
    clear[1] = 3;
    clear[15] = 0x20312200;
    clear[16] = clear[15] + UI_PRESENT_BYTES;
    clear[18] = 0x0f100001;
    assert(ui_range_clear_span(clear) == span);
    assert(ui_range_clear(destination + 2,span,clear) == 0);
    for (size_t i = 2; i < span + 2; ++i) assert(!destination[i]);
    assert(destination[0] == 0xcc && destination[1] == 0xcc);
    assert(destination[span + 2] == 0xcc && destination[span + 3] == 0xcc);
    memset(destination,0xcc,span + 4);
    clear[17] = 1;
    assert(ui_range_clear(destination + 2,span,clear) == -5);
    clear[17] = 0;
    clear[18] ^= 0x100;
    assert(ui_range_clear(destination + 2,span,clear) == -5);
    clear[18] ^= 0x100;
    assert(ui_range_clear(destination + 2,span - 1,clear) == -5);
    ++clear[15];
    assert(!ui_range_clear_span(clear));
    --clear[15];
    ++clear[16];
    assert(!ui_range_clear_span(clear));
    assert(!ui_range_clear_span(NULL));
    for (size_t i = 0; i < span + 4; ++i) assert(destination[i] == 0xcc);
    long pending = 186;
    assert(!ui_present_take_completion(&pending,182,2) && pending == 186);
    assert(!ui_present_take_completion(&pending,186,1) && pending == 186);
    assert(ui_present_take_completion(&pending,186,2) == 0x40000000u && !pending);
    assert(!ui_present_take_completion(&pending,186,2));
    assert(!ui_present_take_completion(&pending,0,2));
    free(source);
    free(destination);
    puts("PASS: full RGBA4444 Morton/flip present, exclusive-end clear, bounds, rejected fields, overlap and one-shot engine/thread completion");
    return 0;
}
