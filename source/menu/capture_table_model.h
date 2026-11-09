#ifndef ZVE10_CAPTURE_TABLE_MODEL_H
#define ZVE10_CAPTURE_TABLE_MODEL_H
#define NE_CAPTURE_TABLE_PHYSICAL UINT32_C(0x1ff00000)
#define NE_CAPTURE_TABLE_BYTES (20u + 1024u * 16u)
#define NE_CAPTURE_TABLE_MAPPING 0x10000u
#define NE_CAPTURE_TABLE_CHECKPOINT 0x8000u
/* Explicit functional model: one shared empty 1024-row table, owned reserved guest RAM. */
static int ne_capture_table_request(const void *packet, size_t length, uint32_t reply_queue)
{
    if (!packet || length < 24 || length > 64 || !reply_queue || reply_queue == 0x4015e) return -1;
    const unsigned char *p = packet;
    if (ui_u32(p) || ui_u32(p + 4) < 0x1000 || ui_u32(p + 4) > 0x1002) return -1;
    for (unsigned i = 8; i < 24; i += 4) if (ui_u32(p + i)) return -1;
    return 0;
}
static int ne_capture_table_initialize(void *memory, size_t capacity)
{
    if (!memory || capacity < NE_CAPTURE_TABLE_BYTES) return -1;
    memset(memory, 0, NE_CAPTURE_TABLE_BYTES);
    uint32_t header[5] = {1024, 1023, 1023, 1023, 0};
    memcpy(memory, header, sizeof header);
    return memcmp(memory, header, sizeof header) ? -1 : 0;
}
/* Local contract for the observed paired access commands; physical CP semantics unverified. */
static int ne_capture_table_access(void *memory, size_t capacity, uint32_t opcode,
                                   uint32_t tid, uint32_t *owner)
{
    if (!memory || !owner || !tid || capacity < NE_CAPTURE_TABLE_CHECKPOINT + NE_CAPTURE_TABLE_BYTES) return -1;
    if (opcode == 0x1001) {
        if (*owner) return -1;
        *owner = tid;
        return 0;
    }
    if (opcode != 0x1002 || *owner != tid) return -1;
    unsigned char *checkpoint = (unsigned char *)memory + NE_CAPTURE_TABLE_CHECKPOINT;
    memcpy(checkpoint, memory, NE_CAPTURE_TABLE_BYTES);
    if (memcmp(checkpoint, memory, NE_CAPTURE_TABLE_BYTES)) return -1;
    *owner = 0;
    return 0;
}
#endif
