#ifndef ZVE10_SHOOT_FILL_H
#define ZVE10_SHOOT_FILL_H
/* A uniform whole-surface fill has the same bytes in linear and tiled storage. */
static int ne_full_tiled_fill(unsigned char *pixels, size_t capacity, const unsigned char *params)
{
    if (!pixels || !params || ui_u16(params + 4) != 640 || ui_u16(params + 6) != 480 ||
        ui_u32(params + 8) || ui_u16(params + 12) != 640 || ui_u16(params + 14) != 480 ||
        ui_u32(params + 16) || ui_u32(params + 20) != 1 || ui_u32(params + 24) ||
        params[32] != 255 || ui_u32(params + 36)) return -5;
    unsigned char linear[48];
    memcpy(linear, params, sizeof linear);
    memset(linear + 20, 0, 4);
    return ui_fill(pixels, capacity, linear);
}
#endif
