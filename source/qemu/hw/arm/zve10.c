/*
 * Sony ZV-E10 (CXD90045) minimal machine for the 3.0.27 firmware kernel.
 *
 * Only the peripherals needed to reach userspace are modelled: DDR at 0,
 * the Cortex-A9 MPCore private region, PL011 UART0, the nine CXD4115
 * timers, and a catch-all register backing for the rest of the SOC map.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "qemu/osdep.h"
#include "qemu/units.h"
#include "qemu/bswap.h"
#include "qapi/error.h"
#include "hw/arm/boot.h"
#include "hw/arm/machines-qom.h"
#include "hw/core/boards.h"
#include "hw/core/irq.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/sysbus.h"
#include "hw/char/pl011.h"
#include "hw/cpu/a9mpcore.h"
#include "hw/misc/unimp.h"
#include "system/system.h"
#include "system/address-spaces.h"
#include "system/cpus.h"
#include "target/arm/cpu-qom.h"
#include "zve10-gpe-init.h"

#define ZVE10_MACHINE_ID    3497
#define ZVE10_MPCORE_BASE   0xf8000000
#define ZVE10_UART0_BASE    0xf2000000
#define ZVE10_UART0_IRQ     150
#define ZVE10_TIMER_BASE    0xf2403000
#define ZVE10_TIMER_IRQ     153
#define ZVE10_NUM_TIMERS    9 /* tick/sched 0..4, Sony UTM 5..8 */
#define ZVE10_RAM_BASE      0x00000000
#define ZVE10_LOADER_START  0x00128000 /* ATAGS below the 0x138000 kernel */


static uint64_t sugi_read(void *opaque, hwaddr off, unsigned size)
{
    /* grm_gles polls 0xf3400080 for the Sugilite power-up acknowledge. */
    return off == 0x80 ? 0x15 : 0;
}


typedef struct Zve10Gpe {
    MemoryRegion mmio;
    uint32_t regs[0x4000 / 4];
    qemu_irq irq;
} Zve10Gpe;

static uint64_t gpe_read(void *opaque, hwaddr off, unsigned size)
{
    Zve10Gpe *s = opaque;
    uint32_t value = s->regs[off / 4];
    return (value >> ((off & 3) * 8)) & (UINT32_MAX >> ((4 - size) * 8));
}

static void gpe_write(void *opaque, hwaddr off, uint64_t value, unsigned size)
{
    Zve10Gpe *s = opaque;
    unsigned shift = (off & 3) * 8;
    uint32_t mask = (UINT32_MAX >> ((4 - size) * 8)) << shift;
    s->regs[off / 4] = (s->regs[off / 4] & ~mask) | ((value << shift) & mask);
    if (off == 0x1000 && value == 0) {
        s->regs[0x34 / 4] &= ~0x80000000u;
        qemu_set_irq(s->irq, s->regs[0x34 / 4] != 0);
    }
    if (off == 0x1800 && value == 4) {
        uint8_t packet[128];
        uint32_t pointer = s->regs[0x1804 / 4];
        if (address_space_read(&address_space_memory, pointer,
                               MEMTXATTRS_UNSPECIFIED, packet, sizeof(packet)) == MEMTX_OK) {
            fprintf(stderr, "ZVE10_GPE_PACKET address=%08x", pointer);
            for (unsigned i = 0; i < sizeof(packet); i += 4) {
                fprintf(stderr, " %08x", ldl_le_p(packet + i));
            }
            fprintf(stderr, "\n");
            uint32_t words[8];
            for (unsigned i = 0; i < ARRAY_SIZE(words); ++i) words[i] = ldl_le_p(packet + i * 4);
            /* shortcut: only this captured startup fence completes; other GPU packets need a verified decoder. */
            if (zve10_gpe_init_packet(words)) {
                s->regs[0x1080 / 4] = words[7];
                s->regs[0x34 / 4] |= 0x80000000u;
                qemu_irq_raise(s->irq);
                fprintf(stderr, "ZVE10_GPE_INIT_FENCE irq=76 token=%08x\n", words[7]);
            }
        }
    }
    fprintf(stderr, "ZVE10_GPE off=%04" HWADDR_PRIx " val=%" PRIx64 " size=%u\n",
            off, value, size);
}

static const MemoryRegionOps gpe_ops = {
    .read = gpe_read,
    .write = gpe_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid.min_access_size = 1,
    .valid.max_access_size = 4,
};

static void sugi_write(void *opaque, hwaddr off, uint64_t value, unsigned size)
{
}

static const MemoryRegionOps sugi_ops = {
    .read = sugi_read,
    .write = sugi_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid.min_access_size = 1,
    .valid.max_access_size = 4,
};

static void zve10_init(MachineState *machine)
{
    MemoryRegion *sysmem = get_system_memory();
    DeviceState *mpcore;
    qemu_irq pic[256 - 32];
    int i;

    memory_region_add_subregion(sysmem, ZVE10_RAM_BASE, machine->ram);

    for (i = 0; i < machine->smp.cpus; i++) {
        Object *cpuobj = object_new(machine->cpu_type);

        object_property_set_bool(cpuobj, "has_el3", false, NULL);
        if (object_property_find(cpuobj, "has_el2")) {
            object_property_set_bool(cpuobj, "has_el2", false, NULL);
        }
        if (object_property_find(cpuobj, "reset-cbar")) {
            object_property_set_int(cpuobj, "reset-cbar", ZVE10_MPCORE_BASE,
                                    &error_abort);
        }
        qdev_realize(DEVICE(cpuobj), NULL, &error_fatal);
    }

    mpcore = qdev_new(TYPE_A9MPCORE_PRIV);
    qdev_prop_set_uint32(mpcore, "num-cpu", machine->smp.cpus);
    qdev_prop_set_uint32(mpcore, "num-irq", 256);
    sysbus_realize_and_unref(SYS_BUS_DEVICE(mpcore), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(mpcore), 0, ZVE10_MPCORE_BASE);

    for (i = 0; i < machine->smp.cpus; i++) {
        CPUState *cs = qemu_get_cpu(i);
        DeviceState *cpudev = DEVICE(cs);

        sysbus_connect_irq(SYS_BUS_DEVICE(mpcore), i,
                           qdev_get_gpio_in(cpudev, ARM_CPU_IRQ));
        sysbus_connect_irq(SYS_BUS_DEVICE(mpcore), i + machine->smp.cpus,
                           qdev_get_gpio_in(cpudev, ARM_CPU_FIQ));
        sysbus_connect_irq(SYS_BUS_DEVICE(mpcore), i + 2 * machine->smp.cpus,
                           qdev_get_gpio_in(cpudev, ARM_CPU_VIRQ));
        sysbus_connect_irq(SYS_BUS_DEVICE(mpcore), i + 3 * machine->smp.cpus,
                           qdev_get_gpio_in(cpudev, ARM_CPU_VFIQ));
    }
    for (i = 0; i < ARRAY_SIZE(pic); i++) {
        pic[i] = qdev_get_gpio_in(mpcore, i);
    }

    /* PL181 SD card: used to supply the camera /usr and /system tree. */
    sysbus_create_varargs("pl181", 0xf1005000, pic[9], pic[10], NULL);

    /* CXD900X0_PL310_BASE */
    sysbus_create_simple("l2x0", ZVE10_MPCORE_BASE + 0x2000, NULL);

    pl011_create(ZVE10_UART0_BASE,
                 g_getenv("ZVE10_NO_UART_IRQ") ? NULL : pic[ZVE10_UART0_IRQ - 32],
                 serial_hd(0));

    for (i = 0; i < ZVE10_NUM_TIMERS; i++) {
        DeviceState *timer = qdev_new("sony-hwtimer");
        SysBusDevice *sbd = SYS_BUS_DEVICE(timer);

        sysbus_realize_and_unref(sbd, &error_fatal);
        sysbus_mmio_map(sbd, 0, ZVE10_TIMER_BASE + i * 0x100);
        sysbus_connect_irq(sbd, 0, g_getenv("ZVE10_NO_TIMER_IRQ") ? NULL : pic[ZVE10_TIMER_IRQ + i - 32]);
    }

    {
        MemoryRegion *sugi = g_new0(MemoryRegion, 1);
        memory_region_init_io(sugi, NULL, &sugi_ops, NULL, "zve10-sugi", 0x1000);
        memory_region_add_subregion_overlap(sysmem, 0xf3400000, sugi, 1);
    }

    {
        Zve10Gpe *gpe = g_new0(Zve10Gpe, 1);
        gpe->irq = pic[76 - 32];
        memory_region_init_io(&gpe->mmio, NULL, &gpe_ops, gpe, "zve10-gpe", 0x4000);
        memory_region_add_subregion_overlap(sysmem, 0xf1000000, &gpe->mmio, 1);
    }
    /* Clock/reset/GPIO/misc register backing; real devices above win. */
    create_unimplemented_device("zve10-soc", 0xf0000000, 0x10000000);

    {
        static struct arm_boot_info binfo;

        binfo.ram_size = machine->ram_size;
        binfo.loader_start = ZVE10_LOADER_START;
        binfo.board_id = ZVE10_MACHINE_ID;
        binfo.kernel_filename = machine->kernel_filename;
        binfo.kernel_cmdline = machine->kernel_cmdline;
        binfo.initrd_filename = machine->initrd_filename;
        arm_load_kernel(ARM_CPU(first_cpu), machine, &binfo);
    }
}

static void zve10_class_init(ObjectClass *oc, const void *data)
{
    static const char * const valid_cpu_types[] = {
        ARM_CPU_TYPE_NAME("cortex-a9"),
        NULL
    };
    MachineClass *mc = MACHINE_CLASS(oc);

    mc->desc = "Sony ZV-E10 (CXD90045)";
    mc->init = zve10_init;
    mc->max_cpus = 4;
    mc->valid_cpu_types = valid_cpu_types;
    mc->default_ram_size = 1 * GiB;
    mc->default_ram_id = "zve10.ram";
    mc->ignore_memory_transaction_failures = true;
}

static const TypeInfo zve10_info = {
    .name = MACHINE_TYPE_NAME("zve10"),
    .parent = TYPE_MACHINE,
    .class_init = zve10_class_init,
    .interfaces = arm_machine_interfaces,
};

static void zve10_machine_init(void)
{
    type_register_static(&zve10_info);
}
type_init(zve10_machine_init);
