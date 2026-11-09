#ifndef ZVE10_NATIVE_ENTRY_H
#define ZVE10_NATIVE_ENTRY_H
#include <stddef.h>
#include <stdint.h>
#define NE_TITLE UINT32_C(0x02feff01)
struct headless_snapshot;
#include "transport.h"
static void native_entry_modules(void *handle);
#if NE_WITH_A7C2
void native_label_text(void *label, uint32_t id) __asm__("_ZN9GEN_Label7setTextEj");
static uintptr_t native_entry_title(uintptr_t a, uintptr_t b, uintptr_t c, uintptr_t d);
#endif
static void native_entry_after_draw(void);
static int native_entry_present(void *pixels, size_t length, uint32_t physical, uintptr_t caller);
#if NE_SHOOT_PROBE
static void ne_line(const char *format, ...);
#if NE_CAPTURE_TABLE_MODEL
static int ne_capture_table_model_send(uint32_t queue, void *message);
static int ne_capture_table_model_snapshot(void);
void ne_shootreq_dispatch(void);
static int ne_install_remote_stages(void);
static int ne_dump_uipc(void);
static unsigned ne_ioctl_logs;
#endif
void ne_shoot_frame(uint16_t *pixels, size_t count);
static int ne_tiled_fill(const unsigned char *params, uintptr_t mode, uintptr_t caller);
#endif
#endif
