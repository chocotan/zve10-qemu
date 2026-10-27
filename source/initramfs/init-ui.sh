#!/bin/sh
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
export LD_LIBRARY_PATH=/usr/lib:/lib
unset LD_PRELOAD
exec >/dev/kmsg 2>&1
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
echo UI_BOOT_V2
load() {
    echo "MODULE_BEGIN $1"
    insmod "$@"
    result=$?
    echo "MODULE_END $1 status=$result"
    return "$result"
}
load /kmod/devno.ko
load /kmod/dmac.ko
load /usr/kmod/osal_utm.ko
load /usr/kmod/osal_uipc.ko
load /usr/kmod/dma330_stub.ko
load /usr/kmod/backup.ko Backup_load=1 Backup_save=0
load /usr/kmod/utimer.ko
load /usr/kmod/osal_ulogio.ko ulogio_initfile=/setting/ulogio.bin
load /usr/kmod/kikilog.ko
load /usr/kmod/stream.ko
load /usr/kmod/stream2.ko
load /usr/kmod/dmm.ko DmmConfig=/setting/DmmConfig.bin
load /usr/kmod/grm_ma.ko
load /usr/kmod/grm_gles.ko
# Device numbers decoded from devno.ko's UDIF_DEVNODE table.
for spec in 'uipc 251 207' 'backup 251 208' 'dmpgles2 248 29' 'stream 249 7' 'stream2 249 8' 'ldec 251 205'; do
    set -- $spec
    [ -e /dev/"$1" ] || mknod /dev/"$1" c "$2" "$3"
done
cat /proc/uptime
( LD_PRELOAD=/usr/lib/libuiobserve.so /usr/bin/bootin.elf 'target=qemu ' dmode=3 amode=normal; echo "BOOTIN_EXIT=$?" ) &
echo "BOOTIN_PID=$!"
sleep 3
echo UI_AFTER_SLEEP_3
cat /proc/uptime
ps
cat /proc/interrupts
for p in /proc/[0-9]*; do
    echo "PROCESS $p"
    cat "$p/comm" "$p/wchan" 2>/dev/null
    cat "$p/cmdline"
    echo
 done
for task in /proc/[0-9]*/task/[0-9]*; do
    echo "THREAD $task"
    cat "$task/comm" "$task/wchan" 2>/dev/null
    echo
 done
sleep 100000
