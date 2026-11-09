/* Original Sony menu: observe native function events without adding any rows. */
#include <pthread.h>
#include <stdarg.h>
#include "native_pins.h"

typedef void (*ne_main_fn)(void *, int *, int *);
typedef void (*ne_base_main_fn)(void *, int *, int *);
#if NE_SHOOT_PROBE
static ne_base_main_fn ne_original_base_main;
#endif
static void ne_line(const char *format, ...);
#if NE_SHOOT_PROBE
static void ne_base_main_wrapper(void *view, int *next, int *action)
{
    unsigned id = view ? ui_u32(view) : 0;
    unsigned fn = view ? ((uint32_t (*)(void *))(object_base + 0x13a695))(view) : 0;
    ne_line("NE_BASEMAIN {\"view\":%u,\"vptr\":%u,\"func\":%u}\n", (unsigned)(uintptr_t)view, id, fn);
    ne_original_base_main(view, next, action);
}
#endif
static ne_main_fn ne_original_main;
static int ne_modules_installed;
static volatile uint32_t ne_last_input, ne_pending_input, ne_pending_function;
static uint64_t ne_required_frame;
static pthread_mutex_t ne_present_mutex = PTHREAD_MUTEX_INITIALIZER;
static uint32_t ne_present_physical;
static uint64_t ne_present_fingerprint;

static void ne_line(const char *format, ...)
{
    char line[512];
    va_list args;
    va_start(args, format);
    int size = vsnprintf(line, sizeof line, format, args);
    va_end(args);
    if (size <= 0 || size >= (int)sizeof line) return;
    int output = __sync_fetch_and_add(&ne_transport_fd, 0);
    if (output < 0) output = 2;
    for (int offset = 0; offset < size;) {
        ssize_t n = write(output, line + offset, (size_t)(size - offset));
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return;
        offset += (int)n;
    }
}
static uintptr_t ne_pointer(uintptr_t address)
{
    uintptr_t value;
    memcpy(&value, (void *)address, sizeof value);
    return value;
}
static void ne_main_wrapper(void *view, int *next_state, int *action)
{
    uint32_t function = ((uint32_t (*)(void *))(object_base + 0x13a695))(view);
    if (function >= 1 && function <= 6 && function == ne_pending_function &&
            ne_pending_input != ne_last_input)
        ne_required_frame = headless_native_frames + 1;
    ne_original_main(view, next_state, action);
    if (function >= 1 && function <= 6 && function == ne_pending_function) {
        __sync_lock_test_and_set(&ne_last_input, ne_pending_input);
        ne_line("NE_INPUT_CONSUMED {\"sequence\":%u,\"function\":%u,\"tid\":%ld,\"overlay\":0,\"native_action\":%d}\n",
                ne_last_input, function, syscall(224), *action);
    }
}
#include "menu_hooks.inc"
static void native_entry_modules(void *handle)
{
    (void)handle;
    if (ne_modules_installed || !object_base || !views_base || draw_count) return;
    if (ne_hook(views_base + 0x2fccc0, ne_pin_main, ne_main_wrapper, &ne_original_main)) {
        ne_line("NE_ERROR phase=original_observer_hook\n"); return;
    }
#if NE_SHOOT_PROBE
    if (ne_hook(object_base + 0x13bc80, ne_pin_base_main, ne_base_main_wrapper, &ne_original_base_main)) {
        ne_line("NE_ERROR phase=shoot_base_main_hook\n"); return;
    }
#endif
    ne_modules_installed = 1;
    ne_line("NE_MODULES {\"pid\":%d,\"hooks\":%s}\n", getpid(),
#if NE_SHOOT_PROBE
            "2"
#else
            "1"
#endif
    );
}
static int native_entry_present(void *pixels, size_t length, uint32_t physical, uintptr_t caller)
{
    (void)caller;
#if NE_SHOOT_PROBE
    if (length == HEADLESS_BYTES)
        ne_shoot_frame((uint16_t *)pixels, length / 2u);
#endif
    if (length == HEADLESS_BYTES) {
        pthread_mutex_lock(&ne_present_mutex);
        ne_present_physical = physical;
        ne_present_fingerprint = headless_fingerprint(pixels, length);
        pthread_mutex_unlock(&ne_present_mutex);
    }
    return 0;
}
static uint64_t ne_present_hash(uint32_t physical)
{
    uint64_t value = 0;
    pthread_mutex_lock(&ne_present_mutex);
    if (physical == ne_present_physical) value = ne_present_fingerprint;
    pthread_mutex_unlock(&ne_present_mutex);
    return value;
}
static uint64_t ne_overlay_hash(uint32_t physical)
{
    (void)physical;
    return 0;
}
static int ne_post_function(uint32_t sequence, uint32_t function)
{
    /* This preview only exposes original direction navigation, not business actions. */
#if NE_SHOOT_PROBE
    if (function < 1 || function > 6 || !sequence || !ne_modules_installed) return -1;
#else
    if (function < 1 || function > 4 || !sequence || !ne_modules_installed) return -1;
#endif
    uintptr_t manager = ne_pointer(object_base + 0x149221c);
    if (!manager || ui_u32((void *)manager) != 43) return -2;
    uintptr_t events = ne_pointer(manager + 0x10);
    if (!events) return -3;
    void *(*allocate)(size_t) = dlsym(RTLD_NEXT, "_Znwj");
    if (!allocate) return -4;
    void *event = allocate(16);
    if (!event) return -5;
#if NE_SHOOT_PROBE
    uint32_t id = ((uint32_t (*)(uint32_t, uint32_t, uint32_t))(object_base + 0x117789))(0x13000000u, 0xa0u, function);
#else
    uint32_t id = ((uint32_t (*)(uint32_t, uint32_t, uint32_t))(object_base + 0x117789))(0x13000000u, 0xbau, function);
#endif
    ne_pending_function = function;
    __sync_lock_test_and_set(&ne_pending_input, sequence);
    ((void (*)(void *, uint32_t, unsigned, unsigned))(object_base + 0x8a01e9))(event, id, 4, 1);
    /* The original queue retains Event* and the original consumer destroys it. */
    ((int (*)(void *, void *, int))(object_base + 0x8a1795))((void *)events, event, 1);
    return 0;
}
static volatile uintptr_t ne_probe_view;
static uint32_t ne_transform(uint32_t id)
{
    uintptr_t view = __sync_fetch_and_add(&ne_probe_view, 0);
    if (!view) return 0;
    return ((uint32_t (*)(void *, uint32_t))(object_base + 0x139121))((void *)view, id);
}
/* Inject a 24-byte _InfraInputEvent through the original InputService path.
   sub_11fbbc builds the key event from the original input table and pushes it. */
static int ne_inject_key(uint32_t key, uint32_t status)
{
    if (!ne_modules_installed || !key) return -1;
    uint32_t event[6] = {0};
    event[0] = key;
    event[2] = status;
    ((void (*)(void *, void *, int))(object_base + 0x11fbbc))(NULL, event, 1);
    return 0;
}
/* Tail of the original key path, skipping the InputServant handshake. */
static int ne_inject_tail(uint32_t id)
{
    if (!ne_modules_installed || !id) return -1;
    void *service = (void *)ne_pointer(object_base + 0x13dba70);
    if (!service) return -2;
    void *event = ((void *(*)(void *, unsigned long, unsigned char))(object_base + 0x11c89b))(NULL, id, 4);
    if (!event) return -3;
    ((void (*)(void *, void *))(object_base + 0x11e5d5))(service, event);
    return 0;
}
static int ne_post_raw_event(uint32_t id, uint32_t dest)
{
    if (!ne_modules_installed || !id || dest > 0xff) return -1;
    uintptr_t manager = ne_pointer(object_base + 0x149221c);
    if (!manager || ui_u32((void *)manager) != 43) return -2;
    uintptr_t events = ne_pointer(manager + 0x10);
    if (!events) return -3;
    void *(*allocate)(size_t) = dlsym(RTLD_NEXT, "_Znwj");
    if (!allocate) return -4;
    void *event = allocate(16);
    if (!event) return -5;
    ((void (*)(void *, uint32_t, unsigned, unsigned))(object_base + 0x8a01e9))(event, id, dest, 1);
    ((int (*)(void *, void *, int))(object_base + 0x8a1795))((void *)events, event, 1);
    return 0;
}
/* Open a view through the original root-selector node's vtable slot +0x90. */
static int ne_open_view(uint32_t id, uint32_t flag)
{
    if (!ne_modules_installed || !id) return -1;
    uintptr_t manager = ne_pointer(object_base + 0x149221c);
    if (!manager || ui_u32((void *)manager) != 43) return -2;
    uint32_t *slots = (void *)ne_pointer(manager + 0x20);
    if (!slots) return -3;
    uintptr_t root = 0;
    for (unsigned i = 0; i < 43; ++i)
        if (slots[i * 4 + 2] == 0xa3 && slots[i * 4 + 1]) { root = slots[i * 4 + 1]; break; }
    if (!root) return -4;
    uintptr_t node = ne_pointer(root + 0x154);
    if (!node) return -5;
    uintptr_t vptr = ui_u32((void *)node);
    if (vptr < 0x1000) return -6;
    void (*open_view)(void *, uint32_t, uint32_t) = (void *)ne_pointer(vptr + 0x90);
    if ((uintptr_t)open_view < 0x1000) return -7;
    open_view((void *)node, id, flag);
    return 0;
}
#if NE_SHOOT_PROBE
/* Observe message receives so an unanswered service can be identified. */
static unsigned ne_rcv_logs;
int osal_rcv_msg_tmo(uint32_t queue, void *message, uint32_t timeout)
{
    static int (*native)(uint32_t, void *, uint32_t);
    if (!native) native = dlsym(RTLD_NEXT, "osal_rcv_msg_tmo");
    if (!native) return -1;
    int result = native(queue, message, timeout);
    if (ne_rcv_logs++ < 400) {
        Dl_info info;
        void *caller = __builtin_return_address(0);
        unsigned long offset = 0; const char *module = "?";
        if (dladdr(caller, &info) && info.dli_fbase && info.dli_fname) {
            module = info.dli_fname;
            offset = (unsigned long)((uintptr_t)caller - (uintptr_t)info.dli_fbase);
        }
        unsigned w0 = 0, w1 = 0, w2 = 0, w3 = 0;
        if (result == 0 && message) {
            memcpy(&w0, (unsigned char *)message + 0, 4);
            memcpy(&w1, (unsigned char *)message + 4, 4);
            memcpy(&w2, (unsigned char *)message + 8, 4);
            memcpy(&w3, (unsigned char *)message + 12, 4);
        }
        ne_line("RCV {\"queue\":%u,\"rc\":%d,\"module\":\"%s\",\"off\":%lu,"
                "\"w0\":%u,\"w1\":%u,\"w2\":%u,\"w3\":%u}\n",
                queue, result, module, offset, w0, w1, w2, w3);
    }
    return result;
}
#endif
#if NE_SHOOT_PROBE
/* Virtual frame: deterministic colour bars + moving marker, written right after the
   original clear so any later original OSD draw still composites on top. */
static unsigned ne_shoot_frames;
static unsigned char ne_frame_owner[640u * 480u];
void ne_shoot_frame(uint16_t *pixels, size_t count)
{
    static const uint16_t bars[8] = {0x0fff,0xf0ff,0xf00f,0x888f,0x111f,0xff0f,0xfff0,0xffff};
    if (!pixels || count < 640u * 480u) return;
    for (unsigned y = 0; y < 480; ++y) {
        unsigned band = (y < 400) ? (y / 50) : 7;
        for (unsigned x = 0; x < 640; ++x) {
            uint16_t *pixel = &pixels[y * 640u + x];
            unsigned char *owner = &ne_frame_owner[y * 640u + x];
            /* Own a pixel only while the original leaves it as background, so a real
               OSD drawn by the AP is never overwritten. */
            if ((*pixel & 0xfff0u) == 0x0000u || *owner) {
                *pixel = bars[band];
                *owner = 1;
            }
        }
    }
    unsigned marker = (ne_shoot_frames * 8u) % 640u;
    for (unsigned y = 420; y < 460; ++y)
        for (unsigned x = marker; x < marker + 24 && x < 640; ++x)
            pixels[y * 640u + x] = 0x000f;
    if (++ne_shoot_frames <= 12)
        ne_line("NEFRAME {\"n\":%u,\"count\":%u}\n", ne_shoot_frames, (unsigned)count);
}
#endif
static void native_entry_after_draw(void)
{
    if (!ne_modules_installed || headless_native_frames < ne_required_frame) return;
    struct ne_observation state = {0};
    state.pid = (uint32_t)getpid(); state.ui_tid = (uint32_t)ui_tid;
    state.last_input = __sync_fetch_and_add(&ne_last_input, 0);
    uintptr_t manager = ne_pointer(object_base + 0x149221c);
    if (manager && ui_u32((void *)manager) == 43) {
        uint32_t *slots = (void *)ne_pointer(manager + 0x20);
        if (slots) for (unsigned i = 0; i < 43; ++i) if (slots[i * 4 + 2] == 0xba && slots[i * 4 + 1]) {
            uintptr_t view = slots[i * 4 + 1];
            if (ui_u32((void *)view) != views_base + 0xbaabb0) continue;
            state.view = (uint32_t)view;
            state.view_state = ui_u32((void *)(view + 4));
            state.submode = ui_u32((void *)(view + 0x164));
            __sync_lock_test_and_set(&ne_probe_view, view);
            break;
        }
#if NE_SHOOT_PROBE
        if (!state.view) for (unsigned i = 0; i < 43; ++i) if (slots[i * 4 + 1]) {
            uintptr_t view = slots[i * 4 + 1];
            state.view = (uint32_t)view;
            state.view_state = ui_u32((void *)(view + 4));
            state.submode = ui_u32((void *)(view + 0x164));
            state.entries = slots[i * 4 + 2]; /* slot id, reused for probe reporting */
            __sync_lock_test_and_set(&ne_probe_view, view);
            state.parent = ui_u32((void *)view);                       /* vptr, probe only */
            if (state.parent >= 0x1000) state.count = ui_u32((void *)(state.parent + 8)); /* Main */
            break;
        }
#endif
    }
    ne_transport_ui(&state, headless_native_frames);
    ne_transport_start();
}
#include "transport.inc"
