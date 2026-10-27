static long sc(long n, long a, long b, long c) {
    register long r0 asm("r0") = a; register long r1 asm("r1") = b;
    register long r2 asm("r2") = c; register long r7 asm("r7") = n;
    asm volatile("svc 0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}
static void wr(long fd, const char *s, long n) { sc(4, fd, (long)s, n); }
static void node(const char *p, long dev) { sc(14, (long)p, 020600, dev); }
void _start(void) {
    node("/dev/ttyAM0", (204 << 8) | 16);
    node("/dev/ttyAMA0", (204 << 8) | 64);
    node("/dev/console", (5 << 8) | 1);
    node("/dev/kmsg", (1 << 8) | 11);
    long k = sc(5, (long)"/dev/kmsg", 1, 0);
    wr(k, "ZVE10_EXEC_SHELL\n", 17);
    long t = sc(5, (long)"/dev/ttyAM0", 2, 0);
    sc(63, t, 0, 0);
    sc(63, k, 1, 0);
    sc(63, k, 2, 0);
    char *argv[] = { "sh", "-i", 0 };
    char *envp[] = { "PATH=/bin:/sbin:/usr/bin:/usr/sbin", "HOME=/", "TERM=linux", 0 };
    sc(11, (long)"/bin/sh", (long)argv, (long)envp);
    wr(k, "ZVE10_EXEC_FAILED\n", 18);
    for (;;) sc(29, 1000, 0, 0);
}
