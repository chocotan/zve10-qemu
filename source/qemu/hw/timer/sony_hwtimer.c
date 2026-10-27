/*
 * Sony BIONZ timer register model for the local CXD90057 firmware experiment.
 * Based on ma1co/qemu hw/timer/bionz_hwtimer.c, updated for QEMU 11.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "qemu/osdep.h"
#include "hw/core/irq.h"
#include "hw/core/sysbus.h"
#include "qemu/module.h"
#include "qemu/log.h"
#include "qemu/timer.h"
#include "qom/object.h"

#define TYPE_SONY_HWTIMER "sony-hwtimer"
OBJECT_DECLARE_SIMPLE_TYPE(SonyHwtimerState, SONY_HWTIMER)

struct SonyHwtimerState {
    SysBusDevice parent_obj;
    MemoryRegion mmio;
    qemu_irq irq;
    QEMUTimer *timer;
    int64_t epoch;
    uint32_t count, control, compare;
};

static int64_t period_ns(SonyHwtimerState *s)
{
    return 250LL << (s->control & 7); /* 4 MHz input clock */
}

static uint32_t counter(SonyHwtimerState *s)
{
    if (!(s->control & 0x1000)) {
        return s->count;
    }
    return s->count + (qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) - s->epoch) /
                     period_ns(s);
}

static void reschedule(SonyHwtimerState *s)
{
    if (s->control & 0x1000) {
        uint32_t remaining = s->compare - counter(s);
        timer_mod(s->timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
                  (remaining ? remaining : 1) * period_ns(s));
    } else {
        timer_del(s->timer);
    }
}

static void tick(void *opaque)
{
    SonyHwtimerState *s = opaque;
    s->count = counter(s);
    s->epoch = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    switch (s->control & 0x30) {
    case 0x10: /* one shot */
        s->control &= ~0x1000;
        break;
    case 0: /* periodic */
        s->count = 0;
        break;
    default: /* free running: next compare is after the 32-bit wrap */
        break;
    }
    if (s->control & 0x100) {
        qemu_irq_raise(s->irq);
    }
    /* Do not immediately retrigger a free-running comparator at the same tick. */
    if ((s->control & 0x1030) == 0x1030) {
        timer_mod(s->timer, s->epoch + (1ULL << 32) * period_ns(s));
    } else {
        reschedule(s);
    }
}

static uint64_t timer_read(void *opaque, hwaddr offset, unsigned size)
{
    SonyHwtimerState *s = opaque;
    switch (offset) {
    case 0: return s->control;
    case 8: return s->compare;
    case 12: return counter(s);
    default: return 0;
    }
}

static void timer_write(void *opaque, hwaddr offset, uint64_t value, unsigned size)
{
    SonyHwtimerState *s = opaque;
    switch (offset) {
    case 0:
        s->count = counter(s);
        s->epoch = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        if (value & 0x80000000) {
            s->count = 0;
            s->compare = UINT32_MAX;
            qemu_irq_lower(s->irq);
        }
        s->control = value & 0xffff;
        break;
    case 4:
        if (value & 0x10) {
            s->count = 0;
            s->epoch = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        }
        if (value & 1) {
            qemu_irq_lower(s->irq);
        }
        break;
    case 8: s->compare = value; break;
    case 16:
        s->count = value;
        s->epoch = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        break;
    default:
        qemu_log_mask(LOG_UNIMP, "Sony timer write offset 0x%" HWADDR_PRIx "\n", offset);
        return;
    }
    reschedule(s);
}

static const MemoryRegionOps timer_ops = {
    .read = timer_read,
    .write = timer_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid.min_access_size = 4,
    .valid.max_access_size = 4,
};

static void timer_realize(DeviceState *dev, Error **errp)
{
    SonyHwtimerState *s = SONY_HWTIMER(dev);
    s->compare = UINT32_MAX;
    s->timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, tick, s);
    memory_region_init_io(&s->mmio, OBJECT(s), &timer_ops, s, TYPE_SONY_HWTIMER, 0x100);
    sysbus_init_mmio(SYS_BUS_DEVICE(s), &s->mmio);
    sysbus_init_irq(SYS_BUS_DEVICE(s), &s->irq);
}

static void timer_class_init(ObjectClass *klass, const void *data)
{
    DEVICE_CLASS(klass)->realize = timer_realize;
}

static const TypeInfo timer_info = {
    .name = TYPE_SONY_HWTIMER,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(SonyHwtimerState),
    .class_init = timer_class_init,
};

static void register_types(void)
{
    type_register_static(&timer_info);
}
type_init(register_types)
