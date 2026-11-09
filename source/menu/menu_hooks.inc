/* Fixed original Thumb prologues are checked before relocation. */
static unsigned ne_jump(unsigned char *where, uintptr_t target)
{
    uintptr_t literal = ((uintptr_t)where + 7u) & ~(uintptr_t)3u;
    uintptr_t pc = ((uintptr_t)where + 4u) & ~(uintptr_t)3u;
    uint16_t instruction[2] = {0xf8df, (uint16_t)(0xf000u | (literal - pc))};
    uint16_t nop = 0xbf00;
    uint32_t address = (uint32_t)target;
    memcpy(where, instruction, 4);
    if (literal != (uintptr_t)where + 4u) memcpy(where + 4, &nop, 2);
    memcpy((void *)literal, &address, 4);
    return (unsigned)(literal + 4u - (uintptr_t)where);
}
static int ne_hook(uintptr_t address, const unsigned char expected[12], void *replacement, void *original)
{
    if (memcmp((void *)address, expected, 12)) return -1;
    unsigned char *code = mmap(NULL, 4096, PROT_READ | PROT_WRITE | PROT_EXEC,
                                MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (code == MAP_FAILED) return -2;
    memcpy(code, (void *)address, 12);
    ne_jump(code + 12, (address + 12) | 1u);
    __builtin___clear_cache((char *)code, (char *)code + 20);
    uintptr_t callable = (uintptr_t)code | 1u;
    memcpy(original, &callable, sizeof callable);
    uintptr_t page = address & ~(uintptr_t)4095;
    unsigned bytes = (address & 3u) ? 10u : 8u;
    size_t protection_span = ((address + bytes + 4095u) & ~(uintptr_t)4095u) - page;
    if (mprotect((void *)page, protection_span, PROT_READ | PROT_WRITE | PROT_EXEC)) return -3;
    unsigned written = ne_jump((void *)address, (uintptr_t)replacement);
    __builtin___clear_cache((char *)address, (char *)address + written);
    if (mprotect((void *)page, protection_span, PROT_READ | PROT_EXEC)) return -4;
    return 0;
}
