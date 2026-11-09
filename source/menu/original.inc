/* Original Sony menu: observe native function events without adding any rows. */
#include <pthread.h>
#include <stdarg.h>
#if NE_SHOOT_PROBE
#include <dirent.h>
#endif
#include "native_pins.h"
static void ne_line(const char *format, ...);

typedef void (*ne_main_fn)(void *, int *, int *);
typedef void (*ne_base_main_fn)(void *, int *, int *);
#if NE_SHOOT_PROBE
static ne_base_main_fn ne_original_base_main;
typedef int (*ne_model_query_fn)(int, int, void *, const void *);
static ne_model_query_fn ne_original_model_query;
typedef uintptr_t (*ne_request_model_fn)(void *, int);
static ne_request_model_fn ne_original_request_model;
typedef uintptr_t (*ne_model_event_fn)(void *, void *);
static ne_model_event_fn ne_original_model_event;
typedef void (*ne_media_config_fn)(void *, int, void *, uint32_t);
static ne_media_config_fn ne_original_media_config;
static void ne_media_config_wrapper(void *packet, int size, void *context, uint32_t cookie)
{
    uint32_t opcode = packet && size >= 24 ? ui_u32(packet) : 0;
    uint32_t media = packet && size >= 28 ? ui_u32((unsigned char *)packet + 24) : 0;
    uint32_t semaphore = context ? ui_u32((unsigned char *)context + 12) : 0;
    static unsigned calls;
    unsigned sequence = __sync_add_and_fetch(&calls, 1);
    int trace = sequence <= 32 || !(sequence % 256);
    if (trace) ne_line("NE_MEDIA_CONFIG {\"edge\":\"enter\",\"sequence\":%u,\"opcode\":%u,\"size\":%d,\"media\":%u,\"cookie\":%u,\"semaphore\":%u}\n",
                       sequence, opcode, size, media, cookie, semaphore);
    ne_original_media_config(packet, size, context, cookie);
    uint32_t status = packet && size >= 24 ? ui_u32((unsigned char *)packet + 20) : UINT32_MAX;
    if (trace || status) ne_line("NE_MEDIA_CONFIG {\"edge\":\"return\",\"sequence\":%u,\"opcode\":%u,\"media\":%u,\"cookie\":%u,\"status\":%u}\n",
                                 sequence, opcode, media, cookie, status);
}
static ne_main_fn ne_original_media_main;
typedef uintptr_t (*ne_manager_init_fn)(void *, uint32_t, uint32_t);
static ne_manager_init_fn ne_original_manager_init;
static uintptr_t ne_manager_init_wrapper(void *manager, uint32_t media, uint32_t argument)
{
    ne_line("NE_MANAGER_INIT {\"edge\":\"enter\",\"manager\":%lu,\"media\":%u,\"argument\":%u,\"tid\":%ld}\n",
            (unsigned long)(uintptr_t)manager, media, argument, syscall(224));
    uintptr_t result = ne_original_manager_init(manager, media, argument);
    ne_line("NE_MANAGER_INIT {\"edge\":\"return\",\"media\":%u,\"result\":%lu,\"tid\":%ld}\n",
            media, (unsigned long)result, syscall(224));
    return result;
}
typedef uintptr_t (*ne_media_action_fn)(void *);
static ne_media_action_fn ne_original_media_scan, ne_original_media_policy;
static uintptr_t ne_content_loop_wrapper(void *object, void *message)
{
    int incoming_errno = errno;
    uintptr_t vtable = ui_u32(object);
    uintptr_t native;
    if (vtable == object_base + 0x13c2c18) native = object_base + 0x8e3711;
    else if (vtable == object_base + 0x13c3258 || vtable == object_base + 0x13c3330) native = object_base + 0x8f3591;
#if NE_CAPTURE_TABLE_MODEL
    else if (vtable == object_base + 0x13a7530) native = object_base + 0x345421;
    else if (vtable == object_base + 0x13aa890) native = object_base + 0x398a3d;
#endif
    else { ne_line("NE_ERROR phase=content_processor_identity\n"); _exit(71); }
    static uint32_t (*message_id)(const void *);
    if (!message_id) message_id = dlsym(RTLD_NEXT, "_ZNK3MWF6ObjMsg12GetMessageIdEv");
    uint32_t id = message && message_id ? message_id(message) : 0;
    if (message) ne_line("NE_CONTENT_CMD {\"edge\":\"enter\",\"object\":%lu,\"vtable_offset\":%lu,\"id\":%u}\n",
                         (unsigned long)(uintptr_t)object, (unsigned long)(vtable - object_base), id);
    errno = incoming_errno;
    uintptr_t result = ((uintptr_t (*)(void *, void *))native)(object, message);
    int original_errno = errno;
    if (message) ne_line("NE_CONTENT_CMD {\"edge\":\"return\",\"object\":%lu,\"id\":%u}\n",
                         (unsigned long)(uintptr_t)object, id);
    errno = original_errno;
    return result;
}
static uintptr_t ne_content_start_wrapper(void *object)
{
    int incoming_errno = errno;
    uintptr_t vtable = ui_u32(object), native;
    if (vtable == object_base + 0x13c2c18) native = object_base + 0x907aa9;
    else if (vtable == object_base + 0x13c3258) native = object_base + 0x90dc99;
    else if (vtable == object_base + 0x13c3330) native = object_base + 0x91a733;
#if NE_CAPTURE_TABLE_MODEL
    else if (vtable == object_base + 0x13a7530) native = object_base + 0x344d31;
    else if (vtable == object_base + 0x13aa890) native = object_base + 0x398777;
#endif
    else { ne_line("NE_ERROR phase=content_start_identity\n"); _exit(71); }
    ne_line("NE_CONTENT_START {\"edge\":\"enter\",\"object\":%lu,\"vtable_offset\":%lu,\"tid\":%ld}\n",
            (unsigned long)(uintptr_t)object, (unsigned long)(vtable - object_base), syscall(224));
    errno = incoming_errno;
    uintptr_t result = ((uintptr_t (*)(void *))native)(object);
    int original_errno = errno;
    ne_line("NE_CONTENT_START {\"edge\":\"return\",\"object\":%lu,\"result\":%lu}\n",
            (unsigned long)(uintptr_t)object, (unsigned long)result);
    errno = original_errno;
    return result;
}
static int ne_install_content_observers(void)
{
    /* Pinned original writable vtables: two-argument processors and one-argument starts. */
    static const struct { uint32_t table, processor, start; } bindings[] = {
        {0x13c2c18, 0x8e3711, 0x907aa9}, {0x13c3258, 0x8f3591, 0x90dc99},
        {0x13c3330, 0x8f3591, 0x91a733},
#if NE_CAPTURE_TABLE_MODEL
        {0x13a7530, 0x345421, 0x344d31},
        {0x13aa890, 0x398a3d, 0x398777},
#endif
    };
    for (unsigned i = 0; i < sizeof bindings / sizeof bindings[0]; ++i) {
        uint32_t *slot = (void *)(object_base + bindings[i].table + 0x38);
        uint32_t native = (uint32_t)(object_base + bindings[i].processor);
        if (!__sync_bool_compare_and_swap(slot, native, (uint32_t)(uintptr_t)ne_content_loop_wrapper)) return -1;
        if (*slot != (uint32_t)(uintptr_t)ne_content_loop_wrapper) return -1;
        uint32_t *start = slot + 1;
        if (!__sync_bool_compare_and_swap(start, (uint32_t)(object_base + bindings[i].start),
                                          (uint32_t)(uintptr_t)ne_content_start_wrapper) ||
            *start != (uint32_t)(uintptr_t)ne_content_start_wrapper) return -1;
    }
    return 0;
}
typedef void *(*ne_content_create_fn)(const void *, void *);
static ne_content_create_fn ne_original_content_create;
static void *ne_content_create_wrapper(const void *parameters, void *error)
{
    void *object = ne_original_content_create(parameters, error);
    ne_line("NE_CONTENT_CREATE {\"object\":%lu,\"vtable_offset\":%lu,\"error\":%u}\n",
            (unsigned long)(uintptr_t)object, object ? (unsigned long)(ui_u32(object) - object_base) : 0,
            error ? ui_u32(error) : UINT32_MAX);
    return object;
}
typedef uintptr_t (*ne_batch_fn)(uint32_t, uint32_t, const uint32_t *, const void *, uint32_t);
static ne_batch_fn ne_original_batch;
static uintptr_t ne_batch_wrapper(uint32_t model, uint32_t function, const uint32_t *ids,
                                  const void *messages, uint32_t option)
{
    int incoming_errno = errno;
    int trace = (model == 0xa && function == 0x41) ||
                (model == 0xf5 && function == 0x2c) || (model == 0x126 && function == 0x11);
    const char *label = model == 0xa ? "NE_MEDIA_BATCH" : "NE_REMOTE_BATCH";
    if (trace) {
        ne_line("%s {\"edge\":\"enter\",\"model\":%u,\"function\":%u,\"option\":%u}\n", label, model, function, option);
        if (ids) for (unsigned i = 0; i < 16 && ids[i]; ++i)
            ne_line("%s_ID {\"index\":%u,\"id\":%u}\n", label, i, ids[i]);
    }
    errno = incoming_errno;
    uintptr_t result = ne_original_batch(model, function, ids, messages, option);
    int original_errno = errno;
    if (trace) ne_line("%s {\"edge\":\"return\",\"model\":%u,\"result\":%lu}\n", label, model, (unsigned long)result);
    errno = original_errno;
    return result;
}
static uintptr_t ne_media_scan_wrapper(void *model)
{
    ne_line("NE_MEDIA_ACTION {\"step\":\"scan\",\"edge\":\"enter\"}\n");
    uintptr_t result = ne_original_media_scan(model);
    ne_line("NE_MEDIA_ACTION {\"step\":\"scan\",\"edge\":\"return\"}\n");
    return result;
}
static uintptr_t ne_media_policy_wrapper(void *model)
{
    ne_line("NE_MEDIA_ACTION {\"step\":\"policy\",\"edge\":\"enter\"}\n");
    uintptr_t result = ne_original_media_policy(model);
    ne_line("NE_MEDIA_ACTION {\"step\":\"policy\",\"edge\":\"return\"}\n");
    return result;
}
static void ne_media_main_wrapper(void *model, int *next, int *action)
{
    uint32_t event = ((uint32_t (*)(void *))(object_base + 0x14c653))(model);
    uint32_t before = ui_u32((unsigned char *)model + 4);
    ne_original_media_main(model, next, action);
    ne_line("NE_MEDIA_MAIN {\"event\":%u,\"state\":%u,\"next\":%d,\"action\":%d,\"flags\":%u}\n",
            event, before, *next, *action, ui_u32((unsigned char *)model + 0x64));
}
static void ne_trace_pending_batch(void)
{
    uintptr_t context = ui_u32((void *)(object_base + 0x145b048));
    if (!context) return;
    uint32_t mode = ui_u32((void *)(context + 0xc)), step = ui_u32((void *)(context + 0x14));
    uint32_t event = ui_u32((void *)(context + 0x18));
    uintptr_t first = ui_u32((void *)(context + 0x70)), last = ui_u32((void *)(context + 0x74));
    if (last < first || (last - first) % 4 || last - first > 32u * 4u) return;
    uint32_t rows[32][9] = {{0}};
    unsigned count = (unsigned)((last - first) / 4);
    uint64_t fingerprint = ((uint64_t)mode << 32) ^ step ^ event;
    for (unsigned i = 0; i < count; ++i) {
        uintptr_t node = ui_u32((void *)(first + i * 4)), commands = node ? ui_u32((void *)(node + 0x10)) : 0;
        if (!node) return;
        rows[i][0] = ui_u32((void *)(node + 0xc));
        rows[i][1] = ui_u32((void *)(node + 4));
        if (commands) for (unsigned j = 0; j < 2; ++j) {
            rows[i][2 + j] = ((const unsigned char *)commands)[8 + j];
            uintptr_t command = ui_u32((void *)(commands + 0xc + j * 4));
            rows[i][4 + j] = command ? ui_u32((void *)(command + 4)) : 0;
            rows[i][7 + j] = command ? ui_u32((void *)(command + 0x10)) : 0;
        }
        rows[i][6] = (uint32_t)node;
        for (unsigned j = 0; j < 9; ++j) fingerprint = fingerprint * 33u + rows[i][j];
    }
    static uint64_t previous;
    if (previous == fingerprint) return;
    previous = fingerprint;
    ne_line("NE_BATCH_CONTEXT {\"mode\":%u,\"step\":%u,\"event\":%u,\"nodes\":%u}\n", mode, step, event, count);
    for (unsigned i = 0; i < count; ++i)
        ne_line("NE_PENDING_RESOURCE {\"resource\":%u,\"state\":%u,\"pending0\":%u,\"pending1\":%u,"
                "\"command_state0\":%u,\"command_state1\":%u,\"node\":%u,\"object_id0\":%u,\"object_id1\":%u}\n",
                rows[i][0], rows[i][1], rows[i][2], rows[i][3], rows[i][4], rows[i][5], rows[i][6], rows[i][7], rows[i][8]);
}
static uintptr_t ne_model_event_wrapper(void *manager, void *event)
{
    uint32_t id = ui_u32((unsigned char *)event + 4);
    int trace = (id & 0xffffff00u) == 0x11004000u;
    if (trace) ne_line("NE_MODEL_EVENT {\"edge\":\"enter\",\"id\":%u,\"state\":%u,\"substate\":%u,\"tree\":%u}\n",
                       id, ui_u32((unsigned char *)manager + 0xa4), ui_u32((unsigned char *)manager + 0xa8),
                       ui_u32((unsigned char *)manager + 0x34));
    uintptr_t result = ne_original_model_event(manager, event);
    ne_trace_pending_batch();
    if (trace) {
        ne_line("NE_MODEL_EVENT {\"edge\":\"return\",\"id\":%u,\"state\":%u,\"substate\":%u,\"tree\":%u}\n",
                id, ui_u32((unsigned char *)manager + 0xa4), ui_u32((unsigned char *)manager + 0xa8),
                ui_u32((unsigned char *)manager + 0x34));
        uintptr_t node = ui_u32((unsigned char *)manager + 0x2c);
        if (!node) node = ui_u32((unsigned char *)manager + 0x20);
        uint32_t model = node ? ui_u32((void *)(node + 8)) : UINT32_MAX;
        uintptr_t record = node ? ((uintptr_t (*)(void *, int))(object_base + 0x8a8793))(manager, (int)model) : 0;
        uintptr_t object = record ? ui_u32((void *)(record + 0x1c)) : 0;
        uintptr_t vtable = object ? ui_u32((void *)object) : 0;
        ne_line("NE_MODEL_NODE {\"id\":%u,\"model\":%u,\"record\":%lu,\"state\":%u,\"object\":%lu,\"vtable_offset\":%lu,\"model_state\":%u,\"flags\":%u}\n",
                id, model, (unsigned long)record, record ? ui_u32((void *)(record + 8)) : 0,
                (unsigned long)object, vtable ? (unsigned long)(vtable - object_base) : 0,
                object ? ui_u32((void *)(object + 4)) : 0,
                object && model == 0xa ? ui_u32((void *)(object + 0x64)) : 0);
    }
    return result;
}
static uintptr_t ne_request_model_wrapper(void *view, int tree)
{
    uintptr_t manager = ui_u32((unsigned char *)view + 0x24);
    ne_line("NE_MODEL_REQUEST {\"view_id\":%u,\"tree\":%d,\"control_view\":%u}\n",
            ui_u32((unsigned char *)view + 0x18), tree, manager ? ui_u32((void *)(manager + 0x5c)) : 0);
    return ne_original_request_model(view, tree);
}
static int ne_model_query_wrapper(int model, int request, void *output, const void *input)
{
    int result = ne_original_model_query(model, request, output, input);
    static unsigned logged;
    if (model == 0x96 && __sync_fetch_and_add(&logged, 1) < 16) {
        uintptr_t manager = ui_u32((void *)(object_base + 0x149221c));
        uintptr_t models = manager ? ui_u32((void *)(manager + 0x18)) : 0;
        uintptr_t record = models ? ((uintptr_t (*)(uintptr_t, int))(object_base + 0x8a8793))(models, model) : 0;
        ne_line("NE_MODEL_QUERY {\"model\":%d,\"request\":%d,\"result\":%d,\"record\":%lu,"
                "\"native_state\":%u,\"native_object\":%u}\n", model, request, result,
                (unsigned long)record, record ? ui_u32((void *)(record + 8)) : 0,
                record ? ui_u32((void *)(record + 0x1c)) : 0);
    }
    return result;
}
#endif
#if NE_SHOOT_PROBE
static void ne_base_main_wrapper(void *view, int *next, int *action)
{
    unsigned id = view ? ui_u32(view) : 0;
    unsigned fn = view ? ((uint32_t (*)(void *))(object_base + 0x13a695))(view) : 0;
    ne_line("NE_BASEMAIN {\"view\":%u,\"vptr\":%u,\"func\":%u}\n", (unsigned)(uintptr_t)view, id, fn);
    ne_original_base_main(view, next, action);
    static unsigned edges;
    if (!(++edges % 32u) && headless_native_frames >= 3) {
        uintptr_t manager = ui_u32((void *)(object_base + 0x149221c));
        uintptr_t models = manager ? ui_u32((void *)(manager + 0x18)) : 0;
        uintptr_t record = models ? ((uintptr_t (*)(uintptr_t, int))(object_base + 0x8a8793))(models, 0x96) : 0;
        ne_line("NE_MODEL_LATE {\"edge\":%u,\"frame\":%llu,\"record\":%lu,\"state\":%u}\n",
                edges, (unsigned long long)headless_native_frames, (unsigned long)record,
                record ? ui_u32((void *)(record + 8)) : 0);
    }
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
    if (ne_hook(object_base + 0x13bc80, ne_pin_base_main, ne_base_main_wrapper, &ne_original_base_main) ||
        ne_hook(object_base + 0x140ef0, ne_pin_model_query, ne_model_query_wrapper, &ne_original_model_query) ||
        ne_hook(object_base + 0x139b88, ne_pin_request_model, ne_request_model_wrapper, &ne_original_request_model) ||
        ne_hook(object_base + 0x8a9f84, ne_pin_model_event, ne_model_event_wrapper, &ne_original_model_event) ||
        ne_hook(object_base + 0x633560, ne_pin_media_main, ne_media_main_wrapper, &ne_original_media_main) ||
        ne_hook(object_base + 0x6341a8, ne_pin_media_scan, ne_media_scan_wrapper, &ne_original_media_scan) ||
        ne_hook(object_base + 0x634350, ne_pin_media_policy, ne_media_policy_wrapper, &ne_original_media_policy) ||
        ne_hook(object_base + 0x3c74b6, ne_pin_media_batch, ne_batch_wrapper, &ne_original_batch) ||
        ne_hook(object_base + 0x8f41d8, ne_pin_content_create, ne_content_create_wrapper, &ne_original_content_create) ||
        ne_hook(object_base + 0x1712f2, ne_pin_media_config, ne_media_config_wrapper, &ne_original_media_config) ||
        ne_hook(object_base + 0x8d0c76, ne_pin_manager_init, ne_manager_init_wrapper, &ne_original_manager_init) ||
        ne_install_content_observers()) {
        ne_line("NE_ERROR phase=shoot_observer_hook\n"); return;
    }
#endif
#if NE_CAPTURE_TABLE_MODEL
    if (ne_install_remote_stages()) {
        ne_line("NE_ERROR phase=remote_stage_observer_hook\n"); return;
    }
#endif
    ne_modules_installed = 1;
    ne_line("NE_MODULES {\"pid\":%d,\"hooks\":%s}\n", getpid(),
#if NE_SHOOT_PROBE
#if NE_CAPTURE_TABLE_MODEL
            "27"
#else
            "18"
#endif
#else
            "1"
#endif
    );
}
static int native_entry_present(void *pixels, size_t length, uint32_t physical, uintptr_t caller)
{
    (void)caller;
#if NE_SHOOT_PROBE && NE_TEST_PATTERN
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
    uint32_t id = ((uint32_t (*)(uint32_t, uint32_t, uint32_t))(object_base + 0x117789))(0x13000000u, 0xc3u, function);
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
#if NE_CAPTURE_TABLE_MODEL
#include "capture_table_model.h"
static uintptr_t (*ne_original_remote_sinks)(void *);
static uintptr_t ne_remote_sinks_wrapper(void *object)
{
    int incoming_errno = errno;
    ne_line("NE_REMOTE_STAGE {\"phase\":\"sinks\",\"edge\":\"enter\",\"object\":%lu,\"tid\":%ld}\n", (unsigned long)(uintptr_t)object, syscall(224));
    errno = incoming_errno;
    uintptr_t result = ne_original_remote_sinks(object);
    int original_errno = errno;
    ne_line("NE_REMOTE_STAGE {\"phase\":\"sinks\",\"edge\":\"return\",\"tid\":%ld}\n", syscall(224));
    errno = original_errno; return result;
}
static uintptr_t (*ne_original_remote_config)(void *, uint32_t);
static uintptr_t ne_remote_config_wrapper(void *object, uint32_t option)
{
    int incoming_errno = errno;
    ne_line("NE_REMOTE_STAGE {\"phase\":\"config\",\"edge\":\"enter\",\"option\":%u,\"tid\":%ld}\n", option, syscall(224));
    errno = incoming_errno;
    uintptr_t result = ne_original_remote_config(object, option);
    int original_errno = errno;
    ne_line("NE_REMOTE_STAGE {\"phase\":\"config\",\"edge\":\"return\",\"tid\":%ld}\n", syscall(224));
    errno = original_errno; return result;
}
static uintptr_t (*ne_original_remote_infra)(void *, uint32_t);
static uintptr_t ne_remote_infra_wrapper(void *object, uint32_t option)
{
    int incoming_errno = errno;
    ne_line("NE_REMOTE_STAGE {\"phase\":\"infra\",\"edge\":\"enter\",\"option\":%u,\"tid\":%ld}\n", option, syscall(224));
    errno = incoming_errno;
    uintptr_t result = ne_original_remote_infra(object, option);
    int original_errno = errno;
    ne_line("NE_REMOTE_STAGE {\"phase\":\"infra\",\"edge\":\"return\",\"tid\":%ld}\n", syscall(224));
    errno = original_errno; return result;
}
static uintptr_t (*ne_original_remote_module)(uint32_t, uint32_t, uint32_t, void *, uint32_t);
static uintptr_t ne_remote_module_wrapper(uint32_t request, uint32_t module, uint32_t reply, void *output, uint32_t cookie)
{
    int incoming_errno = errno;
    ne_line("NE_REMOTE_STAGE {\"phase\":\"module\",\"edge\":\"enter\",\"request\":%u,\"module\":%u,\"reply\":%u,\"cookie\":%u,\"tid\":%ld}\n",
            request, module, reply, cookie, syscall(224));
    errno = incoming_errno;
    uintptr_t result = ne_original_remote_module(request, module, reply, output, cookie);
    int original_errno = errno;
    ne_line("NE_REMOTE_STAGE {\"phase\":\"module\",\"edge\":\"return\",\"result\":%lu,\"tid\":%ld}\n", (unsigned long)result, syscall(224));
    errno = original_errno; return result;
}
static uintptr_t (*ne_original_im_load)(uint32_t, uint32_t, uint32_t);
static uintptr_t ne_im_load_wrapper(uint32_t module, uint32_t mode, uint32_t cookie)
{
    int incoming_errno = errno;
    ne_line("NE_IM_LOAD {\"edge\":\"enter\",\"module\":%u,\"mode\":%u,\"cookie\":%u,\"tid\":%ld}\n", module, mode, cookie, syscall(224));
    errno = incoming_errno;
    uintptr_t result = ne_original_im_load(module, mode, cookie);
    int original_errno = errno;
    ne_line("NE_IM_LOAD {\"edge\":\"return\",\"module\":%u,\"result\":%lu,\"tid\":%ld}\n", module, (unsigned long)result, syscall(224));
    errno = original_errno; return result;
}
static int ne_install_remote_stages(void)
{
    return ne_hook(0xb7dc, ne_pin_im_load, ne_im_load_wrapper, &ne_original_im_load) ||
           ne_hook(object_base + 0x39f63e, ne_pin_remote_sinks, ne_remote_sinks_wrapper, &ne_original_remote_sinks) ||
           ne_hook(object_base + 0x395f40, ne_pin_remote_config, ne_remote_config_wrapper, &ne_original_remote_config) ||
           ne_hook(object_base + 0x3a2a60, ne_pin_remote_infra, ne_remote_infra_wrapper, &ne_original_remote_infra) ||
           ne_hook(object_base + 0x3a1c90, ne_pin_remote_module, ne_remote_module_wrapper, &ne_original_remote_module);
}
int osal_snd_sync_msg(uint32_t queue, void *message)
{
    int incoming_errno = errno;
    static int (*native)(uint32_t, void *);
    if (!native) native = dlsym(RTLD_NEXT, "osal_snd_sync_msg");
    if (!native) _exit(71);
    int trace = queue == 0x94016a;
    if (trace) ne_line("NE_IM_SEND {\"edge\":\"enter\",\"queue\":%u,\"tid\":%ld}\n", queue, syscall(224));
    errno = incoming_errno;
    int result = native(queue, message);
    int original_errno = errno;
    if (trace) ne_line("NE_IM_SEND {\"edge\":\"return\",\"queue\":%u,\"result\":%d,\"tid\":%ld}\n", queue, result, syscall(224));
    errno = original_errno; return result;
}
int osal_dynamic_id(uint32_t operation, uint32_t property, uint32_t *output)
{
    int incoming_errno = errno;
    static int (*native)(uint32_t, uint32_t, uint32_t *);
    if (!native) native = dlsym(RTLD_NEXT, "osal_dynamic_id");
    if (!native) _exit(71);
    uintptr_t caller = (uintptr_t)__builtin_return_address(0) - object_base;
    int trace = (caller & ~(uintptr_t)1) == 0x3a2a7c;
    if (trace) ne_line("NE_REMOTE_DID {\"edge\":\"enter\",\"operation\":%u,\"property\":%u,\"tid\":%ld}\n",
                        operation, property, syscall(224));
    errno = incoming_errno;
    int result = native(operation, property, output);
    int original_errno = errno;
    if (trace) ne_line("NE_REMOTE_DID {\"edge\":\"return\",\"result\":%d,\"id\":%u,\"tid\":%ld}\n",
                        result, !result && output ? *output : 0, syscall(224));
    errno = original_errno; return result;
}
#include <stdarg.h>
int ioctl(int fd, unsigned long request, ...)
{
    va_list arguments; va_start(arguments, request);
    void *argument = va_arg(arguments, void *);
    va_end(arguments);
    int incoming_errno = errno;
    static int (*native)(int, unsigned long, void *);
    if (!native) native = dlvsym(RTLD_NEXT, "ioctl", "GLIBC_2.4");
    if (!native) _exit(71);
    unsigned sub = (unsigned)(request & 0xffu);
    int trace = (request & 0xffffff00u) == 0x80000000u && sub >= 5 && sub <= 0xc;
    unsigned sequence = trace ? __sync_fetch_and_add(&ne_ioctl_logs, 1) : 0;
    if (trace && sequence < 240)
        ne_line("NE_UIPC_IOCTL {\"edge\":\"enter\",\"sub\":%u,\"tid\":%ld,\"seq\":%u}\n", sub, syscall(224), sequence);
    errno = incoming_errno;
    int result = native(fd, request, argument);
    int original_errno = errno;
    if (trace && sequence < 240)
        ne_line("NE_UIPC_IOCTL {\"edge\":\"return\",\"sub\":%u,\"result\":%d,\"errno\":%d,\"tid\":%ld,\"seq\":%u}\n",
                sub, result, original_errno, syscall(224), sequence);
    errno = original_errno;
    return result;
}
uintptr_t _ZN3MWF9ObjSignal9GetSignalEj(void *signal, uint32_t mask)
{
    int incoming_errno = errno;
    static uintptr_t (*native)(void *, uint32_t);
    if (!native) native = dlsym(RTLD_NEXT, "_ZN3MWF9ObjSignal9GetSignalEj");
    if (!native) _exit(71);
    uintptr_t offset = (uintptr_t)__builtin_return_address(0) - object_base;
    int trace = (offset & ~(uintptr_t)1) == 0x3984a4;
    if (trace) ne_line("NE_REMOTE_SIGNAL {\"edge\":\"enter\",\"signal\":%lu,\"mask\":%u,\"caller\":%lu,\"tid\":%ld}\n",
                        (unsigned long)(uintptr_t)signal, mask, (unsigned long)offset, syscall(224));
    errno = incoming_errno;
    uintptr_t result = native(signal, mask);
    int original_errno = errno;
    if (trace) ne_line("NE_REMOTE_SIGNAL {\"edge\":\"return\",\"signal\":%lu,\"mask\":%u,\"result\":%lu,\"tid\":%ld}\n",
                        (unsigned long)(uintptr_t)signal, mask, (unsigned long)result, syscall(224));
    errno = original_errno;
    return result;
}
static struct {
    pthread_mutex_t mutex;
    void *table;
    uint32_t owner;
} ne_capture_table_state = { .mutex = PTHREAD_MUTEX_INITIALIZER };
static int ne_dump_uipc(void)
{
    int fd = open("/proc/osal/uipc", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    unsigned offset = 0;
    for (; offset < 65536;) {
        unsigned char bytes[64];
        ssize_t n = read(fd, bytes, sizeof bytes);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) { close(fd); return -1; }
        if (!n) break;
        char hex[129];
        for (ssize_t i = 0; i < n; ++i) { hex[i*2]="0123456789abcdef"[bytes[i]>>4]; hex[i*2+1]="0123456789abcdef"[bytes[i]&15]; }
        hex[n*2]=0;
        ne_line("NE_UIPC {\"offset\":%u,\"hex\":\"%s\"}\n", offset, hex);
        offset += (unsigned)n;
    }
    close(fd);
    ne_line("NE_UIPC_DONE {\"bytes\":%u,\"capped\":%s}\n", offset, offset==65536?"true":"false");
    return 0;
}
static int ne_capture_table_model_snapshot(void)
{
    pthread_mutex_lock(&ne_capture_table_state.mutex);
    unsigned char *table = ne_capture_table_state.table;
    if (!table || ne_capture_table_state.owner) {
        pthread_mutex_unlock(&ne_capture_table_state.mutex); return -1;
    }
    ne_line("NE_CAPTURE_TABLE_STATE {\"physical\":%u,\"bytes\":%u,\"header\":[%u,%u,%u,%u,%u],\"fingerprint\":\"%016llx\",\"checkpoint_fingerprint\":\"%016llx\"}\n",
            NE_CAPTURE_TABLE_PHYSICAL, NE_CAPTURE_TABLE_BYTES,
            ui_u32(table), ui_u32(table+4), ui_u32(table+8), ui_u32(table+12), ui_u32(table+16),
            (unsigned long long)headless_fingerprint(table, NE_CAPTURE_TABLE_BYTES),
            (unsigned long long)headless_fingerprint(table + NE_CAPTURE_TABLE_CHECKPOINT, NE_CAPTURE_TABLE_BYTES));
    pthread_mutex_unlock(&ne_capture_table_state.mutex);
    return 0;
}
static int ne_capture_table_model_send(uint32_t queue, void *message)
{
    static int (*size_of)(void *);
    static int (*send_original)(uint32_t, void *);
    static int (*free_original)(uint32_t, void *);
    if (!size_of) size_of = dlsym(RTLD_NEXT, "osal_msg_size");
    if (!send_original) send_original = dlsym(RTLD_NEXT, "osal_snd_msg");
    if (!free_original) free_original = dlsym(RTLD_NEXT, "osal_free_msg");
    if (!message || !size_of || !send_original || !free_original) {
        ne_line("NE_ERROR phase=capture_table_model_api\n"); return -1;
    }
    int length = size_of(message);
    uint32_t reply = ui_u32((unsigned char *)message - 4);
    uint32_t opcode = length >= 8 ? ui_u32((unsigned char *)message + 4) : 0;
    if (length < 0 || ne_capture_table_request(message, (size_t)length, reply)) {
        ne_line("NE_ERROR phase=capture_table_model_request\n");
        free_original(queue, message); return -1;
    }
    pthread_mutex_lock(&ne_capture_table_state.mutex);
    void *table = ne_capture_table_state.table;
    uint32_t owner = ne_capture_table_state.owner;
    int error = 0;
    if (!table) {
        char command_line[4096];
        int command_fd = open("/proc/cmdline", O_RDONLY | O_CLOEXEC);
        ssize_t command_size = command_fd < 0 ? -1 : read(command_fd, command_line, sizeof command_line - 1);
        if (command_fd >= 0) close(command_fd);
        if (command_size <= 0 || command_size >= (ssize_t)sizeof command_line - 1) error = EINVAL;
        else {
            command_line[command_size] = 0;
            if (!strstr(command_line, " memrsv=128K@0x1ff00000 ")) error = EINVAL;
        }
        int fd = error ? -1 : open("/dev/mem", O_RDWR | O_SYNC | O_CLOEXEC);
        if (fd < 0) { if (!error) error = errno; }
        else {
            table = mmap(NULL, NE_CAPTURE_TABLE_MAPPING, PROT_READ | PROT_WRITE,
                         MAP_SHARED, fd, NE_CAPTURE_TABLE_PHYSICAL);
            if (table == MAP_FAILED) { table = NULL; error = errno; }
            close(fd);
        }
        if (table && ne_capture_table_initialize(table, NE_CAPTURE_TABLE_MAPPING)) error = EIO;
    }
    if (!error && opcode != 0x1000 &&
        ne_capture_table_access(table, NE_CAPTURE_TABLE_MAPPING, opcode, (uint32_t)syscall(224), &owner)) error = EBUSY;
    if (!error) {
        uint32_t response[6] = {1, opcode, 0, opcode == 0x1000 ? NE_CAPTURE_TABLE_PHYSICAL : 0, 0, 0};
        memcpy(message, response, sizeof response);
        __sync_synchronize();
        if (memcmp(message, response, sizeof response)) error = EIO;
    }
    ne_capture_table_state.table = table;
    ne_capture_table_state.owner = owner;
    pthread_mutex_unlock(&ne_capture_table_state.mutex);
    if (error) {
        ne_line("NE_ERROR phase=capture_table_model_memory errno=%d\n", error);
        free_original(queue, message); return -1;
    }
    /* The original receiver maps this real table, consumes the packet and frees it. */
    int result = send_original(reply, message);
    ne_line("NE_CAPTURE_TABLE_MODEL {\"opcode\":%u,\"reply_queue\":%u,\"physical\":%u,\"bytes\":%u,\"send_result\":%d}\n",
            opcode, reply, NE_CAPTURE_TABLE_PHYSICAL, NE_CAPTURE_TABLE_BYTES, result);
    if (result) free_original(queue, message);
    return result;
}
#endif
#if NE_SHOOT_PROBE
#include "shoot_fill.h"
static int ne_tiled_fill(const unsigned char *params, uintptr_t mode, uintptr_t caller)
{
    if (!params || ui_u32(params + 20) != 1) return -5;
    static unsigned calls;
    if (__sync_fetch_and_add(&calls, 1) < 3)
        ne_line("NE_FILL_CALL {\"mode\":%lu,\"caller\":%lu,\"token\":%u}\n",
                (unsigned long)mode, (unsigned long)((caller & ~(uintptr_t)1) - object_base), ui_u32(params));
    if (mode != 2 || (caller & ~(uintptr_t)1) != object_base + 0x6837d0) return -5;
    uintptr_t bitmap = ui_u32(params + 48);
    if (bitmap < 4096 || bitmap > UINT32_MAX - 12 ||
        ui_u32((void *)bitmap) != object_base + 0x13ba5a0) return -5;
    uintptr_t meta = ui_u32((void *)(bitmap + 4));
    uint32_t bits = ui_u32((void *)(bitmap + 8));
    if (meta < 4096 || meta > UINT32_MAX - 52 || bits != ui_u32(params)) return -5;
    unsigned char before[52]; memcpy(before, (void *)meta, sizeof before);
    static unsigned traced;
    if (!traced++) ne_line("NE_FILL_META {\"width\":%u,\"height\":%u,\"aw\":%u,\"ah\":%u,\"format\":%u,"
                          "\"physical\":%u,\"sorting\":%u,\"start\":%u,\"origin\":%u,\"offset\":%u}\n",
                          ui_u16(before + 8), ui_u16(before + 10), ui_u16(before + 24), ui_u16(before + 26),
                          ui_u32(before + 28), ui_u32(before + 36), ui_u32(before + 44), ui_u32(before + 48),
                          ui_u32(before + 4), ui_u32(before + 20));
    if (ui_u32(before + 4) || ui_u32(before + 20) ||
        ui_u16(before + 8) != 640 || ui_u16(before + 10) != 480 ||
        ui_u16(before + 24) != 640 || ui_u16(before + 26) != 480 ||
        ui_u32(before + 28) != 1 || ui_u32(before + 44) != 1 || ui_u32(before + 48)) return -5;
    struct surface_mapping mapping;
    if (map_surface(ui_u32(before + 36), HEADLESS_BYTES, &mapping)) return -5;
    int result = ne_full_tiled_fill(mapping.pixels, HEADLESS_BYTES, params);
    __sync_synchronize();
    int changed = memcmp(before, (void *)meta, sizeof before) ||
                  ui_u32((void *)(bitmap + 8)) != bits;
    if (munmap(mapping.base, mapping.length) || changed) result = -5;
    ne_line("NE_FILL_RESULT {\"result\":%d,\"changed\":%d}\n", result, changed != 0);
    if (!result) ne_line("NE_DMP_FILL {\"pixels\":307200,\"bitmap\":%lu,\"physical\":%u}\n",
                         (unsigned long)bitmap, ui_u32(before + 36));
    return result;
}
uint32_t ne_capture_id_enabled(uintptr_t argument) __asm__("_ZN7MprCtrl16IsCaptureIdTableEv");
uint32_t ne_capture_id_enabled(uintptr_t argument)
{
    int incoming_errno = errno;
    static uint32_t (*native)(uintptr_t);
    if (!native) native = dlsym(RTLD_NEXT, "_ZN7MprCtrl16IsCaptureIdTableEv");
    if (!native) { ne_line("NE_ERROR phase=original_capture_id_enable_symbol\n"); _exit(71); }
    ne_line("NE_CAPTURE_ID_ENABLE {\"edge\":\"enter\",\"tid\":%ld}\n", syscall(224));
    errno = incoming_errno;
    uint32_t enabled = native(argument);
    int original_errno = errno;
    ne_line("NE_CAPTURE_ID_ENABLE {\"edge\":\"return\",\"value\":%u,\"tid\":%ld}\n", enabled, syscall(224));
    errno = original_errno;
    return enabled;
}
uint32_t ne_capture_id_max(uintptr_t argument) __asm__("_ZN7MprCtrl25GetCaptureIdTableMaxCountEv");
uint32_t ne_capture_id_max(uintptr_t argument)
{
    int incoming_errno = errno;
    static uint32_t (*native)(uintptr_t);
    if (!native) native = dlsym(RTLD_NEXT, "_ZN7MprCtrl25GetCaptureIdTableMaxCountEv");
    if (!native) { ne_line("NE_ERROR phase=original_capture_id_max_symbol\n"); _exit(71); }
    ne_line("NE_CAPTURE_ID_MAX {\"edge\":\"enter\",\"tid\":%ld}\n", syscall(224));
    errno = incoming_errno;
    uint32_t count = native(argument);
    int original_errno = errno;
    ne_line("NE_CAPTURE_ID_MAX {\"edge\":\"return\",\"count\":%u,\"tid\":%ld}\n", count, syscall(224));
    errno = original_errno;
    return count;
}
static int ne_trace_sync_wrapper(void *wrapper, int size, uintptr_t caller, const char *api)
{
    uint32_t queue = wrapper ? ui_u32((unsigned char *)wrapper + 4) : 0;
    static unsigned count;
    if (queue == 0xcf016d && (caller < object_base + 0x91cf74 || caller >= object_base + 0x91d020)) return 0;
    if ((queue != 0xcf016d && queue != 0x37807c) || __sync_fetch_and_add(&count, 1) >= 160) return 0;
    ne_line("NE_SYNC_CALL {\"edge\":\"enter\",\"api\":\"%s\",\"queue\":%u,\"size\":%d,\"caller_offset\":%lu,\"tid\":%ld}\n",
            api, queue, size, (unsigned long)(caller - object_base), syscall(224));
    return 1;
}
int ne_event_send(void *, const void *, int, void *, int) __asm__("_ZN3MWF12EventWrapper4SendEPKviPvi");
int ne_event_send(void *wrapper, const void *input, int input_size, void *output, int output_size)
{
    int before_errno = errno;
    static int (*native)(void *, const void *, int, void *, int);
    if (!native) native = dlsym(RTLD_NEXT, "_ZN3MWF12EventWrapper4SendEPKviPvi");
    if (!native) { ne_line("NE_ERROR phase=original_event_send_symbol\n"); _exit(71); }
    int trace = ne_trace_sync_wrapper(wrapper, input_size, (uintptr_t)__builtin_return_address(0), "Send");
    errno = before_errno;
    int result = native(wrapper, input, input_size, output, output_size);
    int after_errno = errno;
    if (trace) ne_line("NE_SYNC_CALL {\"edge\":\"return\",\"api\":\"Send\",\"queue\":%u,\"result\":%d,\"tid\":%ld}\n",
                       ui_u32((unsigned char *)wrapper + 4), result, syscall(224));
    errno = after_errno;
    return result;
}
int ne_event_send_recv(void *, void *, int, void *, int) __asm__("_ZN3MWF12EventWrapper11SendAndRecvEPviS1_i");
int ne_event_send_recv(void *wrapper, void *input, int input_size, void *output, int output_size)
{
    int before_errno = errno;
    static int (*native)(void *, void *, int, void *, int);
    if (!native) native = dlsym(RTLD_NEXT, "_ZN3MWF12EventWrapper11SendAndRecvEPviS1_i");
    if (!native) { ne_line("NE_ERROR phase=original_event_send_recv_symbol\n"); _exit(71); }
    int trace = ne_trace_sync_wrapper(wrapper, input_size, (uintptr_t)__builtin_return_address(0), "SendAndRecv");
    errno = before_errno;
    int result = native(wrapper, input, input_size, output, output_size);
    int after_errno = errno;
    if (trace) ne_line("NE_SYNC_CALL {\"edge\":\"return\",\"api\":\"SendAndRecv\",\"queue\":%u,\"result\":%d,\"tid\":%ld}\n",
                       ui_u32((unsigned char *)wrapper + 4), result, syscall(224));
    errno = after_errno;
    return result;
}
/* The receiver owns the returned OSAL allocation until its original free. */
static unsigned ne_rcv_logs;
int osal_rcv_msg_tmo(uint32_t queue, void **message, uint32_t timeout)
{
    static int (*native)(uint32_t, void **, uint32_t);
    static int (*native_size)(void *);
    if (!native) native = dlsym(RTLD_NEXT, "osal_rcv_msg_tmo");
    if (!native_size) native_size = dlsym(RTLD_NEXT, "osal_msg_size");
    if (!native) return -1;
    uintptr_t caller = (uintptr_t)__builtin_return_address(0);
    int capture_wait = (caller & ~(uintptr_t)1) == object_base + 0x8f2792 ||
                       (caller & ~(uintptr_t)1) == object_base + 0x9026ae;
    if (capture_wait) ne_line("NE_CAPTURE_TABLE_WAIT {\"edge\":\"enter\",\"queue\":%u,\"timeout\":%u,\"caller\":%lu,\"tid\":%ld}\n",
                              queue, timeout, (unsigned long)(caller - object_base), syscall(224));
    int result = native(queue, message, timeout);
    if (capture_wait) ne_line("NE_CAPTURE_TABLE_WAIT {\"edge\":\"return\",\"queue\":%u,\"rc\":%d,\"tid\":%ld}\n",
                              queue, result, syscall(224));
    if (__sync_fetch_and_add(&ne_rcv_logs, 1) < 600) {
        Dl_info info;
        void *caller = __builtin_return_address(0);
        unsigned long offset = 0; const char *module = "?";
        if (dladdr(caller, &info) && info.dli_fbase && info.dli_fname) {
            module = info.dli_fname;
            offset = (unsigned long)((uintptr_t)caller - (uintptr_t)info.dli_fbase);
        }
        void *payload = result == 0 && message ? *message : NULL;
        int size = payload && native_size ? native_size(payload) : 0;
        unsigned count = size > 0 && size <= 4096 ? (unsigned)size : 0;
        if (count > 64) count = 64;
        char hex[129] = {0};
        for (unsigned i = 0; i < count; ++i)
            snprintf(hex + i * 2, 3, "%02x", ((const unsigned char *)payload)[i]);
        ne_line("NE_RCV {\"queue\":%u,\"rc\":%d,\"tid\":%ld,\"module\":\"%s\",\"off\":%lu,"
                "\"pointer\":%lu,\"size\":%d,\"hex\":\"%s\"}\n",
                queue, result, syscall(224), module, offset,
                (unsigned long)(uintptr_t)payload, size, hex);
    }
    return result;
}
#endif
#if NE_SHOOT_PROBE
/* Diagnostic underlay on the copied linear output; original nontransparent pixels win. */
static unsigned ne_shoot_frames;
void ne_shoot_frame(uint16_t *pixels, size_t count)
{
    static const uint16_t bars[8] = {0x0fff,0xf0ff,0xf00f,0x888f,0x111f,0xff0f,0x000f,0xffff};
    if (!pixels || count < 640u * 480u) return;
    unsigned marker = (ne_shoot_frames * 8u) % 640u;
    for (unsigned y = 0; y < 480; ++y) {
        unsigned band = (y < 400) ? (y / 50) : 7;
        for (unsigned x = 0; x < 640; ++x) {
            uint16_t *pixel = &pixels[y * 640u + x];
            if (!(*pixel & 15u))
                *pixel = y >= 420 && y < 460 && x >= marker && x < marker + 24 ? 0x000f : bars[band];
        }
    }
    if (++ne_shoot_frames <= 12)
        ne_line("NEFRAME {\"n\":%u,\"count\":%u}\n", ne_shoot_frames, (unsigned)count);
}
#endif
#if NE_SHOOT_VIEW
static void ne_request_shooting_view(void)
{
    static int submitted;
    if (submitted || syscall(224) != ui_tid) return;
    uintptr_t manager = ne_pointer(object_base + 0x149221c);
    if (!manager || ui_u32((void *)manager) != 43) return;
    uint32_t *slots = (void *)ne_pointer(manager + 0x20);
    if (!slots) return;
    uintptr_t root = 0;
    for (unsigned i = 0; i < 43; ++i) {
        if (slots[i * 4 + 1] && slots[i * 4 + 2] == 0xc3) { submitted = 1; return; }
        if (slots[i * 4 + 2] == 0xa3) root = slots[i * 4 + 1];
    }
    if (!root || ui_u32((void *)root) != views_base + 0xbacc50 ||
        ne_pointer(root + 0x154) != views_base + 0xbace80 ||
        ne_pointer(root + 0x24) != manager ||
        memcmp((void *)(views_base + 0x41a794), ne_pin_shoot_open, sizeof ne_pin_shoot_open) ||
        memcmp((void *)(views_base + 0x8f9474), ne_pin_shoot_boot_pair, sizeof ne_pin_shoot_boot_pair) ||
        memcmp((void *)(views_base + 0x414350), ne_pin_shoot_boot_open, sizeof ne_pin_shoot_boot_open)) return;
    submitted = 1;
    /* Preserve ActionOpenBootRecMode's native auxiliary/black/shoot request order. */
    ((void (*)(void *, int))(views_base + 0x41a7d9))((void *)(root + 0x154), 0xa4);
    ((void (*)(void *, int))(views_base + 0x41a7d9))((void *)(root + 0x154), 0x34);
    ((void (*)(void *, int, int))(views_base + 0x41a7b1))((void *)(root + 0x154), 0xc3, 3);
    ne_line("NE_SHOOT_REQUEST {\"prefix\":[164,52],\"view_id\":195,\"option\":3,\"tid\":%ld,\"root\":%lu}\n",
            syscall(224), (unsigned long)root);
}
#endif
#if NE_SHOOT_VIEW
static volatile unsigned ne_shoot_pending = !NE_SHOOT_REQ_ON_DEMAND;
#endif
void ne_shootreq_dispatch(void)
{
    /* Transport thread: only marks the request; the UI thread performs it on
     * its next after_draw so the original guards (ui_tid) stay intact. */
#if NE_SHOOT_VIEW
    ne_shoot_pending = 1;
#endif
}
static void native_entry_after_draw(void)
{
    if (!ne_modules_installed || headless_native_frames < ne_required_frame) return;
#if NE_SHOOT_VIEW
    if (ne_shoot_pending) {
        ne_shoot_pending = 0;
        ne_request_shooting_view();
    }
#endif
    struct ne_observation state = {0};
    state.pid = (uint32_t)getpid(); state.ui_tid = (uint32_t)ui_tid;
    state.last_input = __sync_fetch_and_add(&ne_last_input, 0);
    uintptr_t manager = ne_pointer(object_base + 0x149221c);
    if (manager && ui_u32((void *)manager) == 43) {
        uint32_t *slots = (void *)ne_pointer(manager + 0x20);
#if NE_SHOOT_PROBE
        static unsigned view_dumps;
        if (slots && view_dumps++ < 3) for (unsigned i = 0; i < 43; ++i) if (slots[i * 4 + 1]) {
            uintptr_t view = slots[i * 4 + 1], vtable = ui_u32((void *)view);
            uintptr_t main = vtable >= 0x1000 ? ne_pointer(vtable + 8) : 0;
            Dl_info info; const char *module = "?"; unsigned long offset = 0;
            if (main && dladdr((void *)main, &info) && info.dli_fbase && info.dli_fname) {
                module = info.dli_fname; offset = (unsigned long)(main - (uintptr_t)info.dli_fbase);
            }
            ne_line("NE_VIEW {\"frame\":%llu,\"slot\":%u,\"view\":%lu,\"vtable\":%lu,\"state\":%u,"
                    "\"main_module\":\"%s\",\"main_offset\":%lu}\n",
                    (unsigned long long)headless_native_frames, slots[i * 4 + 2],
                    (unsigned long)view, (unsigned long)vtable, ui_u32((void *)(view + 4)), module, offset);
        }
#endif
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
            if (state.entries == 0xc3) break;
        }
#endif
    }
    ne_transport_ui(&state, headless_native_frames);
    ne_transport_start();
}
#if NE_SHOOT_PROBE
static void ne_dump_thread_file(unsigned long tid, const char *field)
{
    char path[96];
    int n = snprintf(path, sizeof path, "/proc/self/task/%lu/%s", tid, field);
    if (n <= 0 || n >= (int)sizeof path) return;
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        ne_line("NE_THREAD {\"tid\":%lu,\"file\":\"%s\",\"errno\":%d}\n", tid, field, errno);
        return;
    }
    size_t total = 0;
    while (total < 2048) {
        unsigned char bytes[128]; char hex[257];
        ssize_t count = read(fd, bytes, sizeof bytes);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) {
            if (count < 0) ne_line("NE_THREAD {\"tid\":%lu,\"file\":\"%s\",\"errno\":%d}\n", tid, field, errno);
            break;
        }
        for (ssize_t i = 0; i < count; ++i) snprintf(hex + i * 2, 3, "%02x", bytes[i]);
        ne_line("NE_THREAD {\"tid\":%lu,\"file\":\"%s\",\"offset\":%u,\"hex\":\"%s\"}\n",
                tid, field, (unsigned)total, hex);
        total += (size_t)count;
    }
    close(fd);
}
static void ne_dump_threads(void)
{
    DIR *tasks = opendir("/proc/self/task");
    if (!tasks) { ne_line("NE_THREADS_DONE {\"errno\":%d}\n", errno); return; }
    struct dirent *entry; unsigned count = 0;
    while (count < 256 && (entry = readdir(tasks))) {
        const char *name = entry->d_name;
        if (!*name) continue;
        const char *p = name;
        while (*p >= '0' && *p <= '9') ++p;
        if (*p) continue;
        unsigned long tid = strtoul(name, NULL, 10);
        ne_dump_thread_file(tid, "comm");
        ne_dump_thread_file(tid, "wchan");
        if (tid == (unsigned long)ui_tid || tid == (unsigned long)rm_tid || tid == (unsigned long)getpid())
            { ne_dump_thread_file(tid, "stack"); ne_dump_thread_file(tid, "syscall"); }
        ++count;
    }
    closedir(tasks);
    ne_line("NE_THREADS_DONE {\"pid\":%d,\"count\":%u}\n", getpid(), count);
}
#endif
#include "transport.inc"
