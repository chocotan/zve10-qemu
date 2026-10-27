#!/usr/bin/env bash
# AP-only original-firmware UI with software rendering and native frame capture.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
work="$root/work"
qemu="$work/qemu-src/build-zve10/qemu-system-arm"
image="$work/kbuild-ui/arch/arm/boot/Image"
cross="${CROSS_COMPILE:-$work/armv7-eabihf--glibc--stable-2020.08-1/bin/arm-linux-}"
[[ -x "$qemu" && -f "$image" ]] || { echo '先按 docs/setup.md 构建 QEMU 和内核' >&2; exit 1; }
[[ -f "$work/initramfs-ui/init" ]] || { echo '先运行 scripts/prepare-initramfs.py，见 docs/setup.md' >&2; exit 1; }
[[ -f "$work/initramfs-ui/usr/kmod/dma330_stub.ko" ]] || { echo '缺少 dma330_stub.ko，请完成 docs/setup.md 的模块编译步骤' >&2; exit 1; }
if [[ ! -f "$work/fakeroot.state" && ! -c "$work/initramfs-ui/dev/console" ]]; then
    echo '缺少 /dev/console 的设备节点信息，请按 docs/setup.md 使用 fakeroot 准备文件系统' >&2
    exit 1
fi
"${cross}gcc" -shared -fPIC -O2 -Wall -Wextra -Werror \
    -o "$work/initramfs-ui/usr/lib/libuiobserve.so" "$root/source/ui/ui-observe.c" -ldl
mkdir -p "$root/evidence/ui-startup"
python3 "$root/scripts/prepare-ui-profile.py" > "$root/evidence/ui-startup/ap-profile.json"
pack=(bash -o pipefail -c 'cd "$1" && find . -print0 | cpio --null -o -H newc --quiet --owner=0:0' bash "$work/initramfs-ui")
if [[ -f "$work/fakeroot.state" ]]; then
    pack=(fakeroot -i "$work/fakeroot.state" -- "${pack[@]}")
fi
"${pack[@]}" > "$work/ui.cpio.part"
mv "$work/ui.cpio.part" "$work/ui.cpio"
exec "$qemu" -M zve10 -cpu cortex-a9 -smp 1 -m 1024 \
    -kernel "$image" -initrd "$work/ui.cpio" \
    -append 'console=ttyAM0,115200n8 cfg.uart=1 mem=1G@0 memrsv=0x1A5E000@0x02E68000 memrsv=128M@0x20000000:uc rdinit=/init loglevel=8' \
    -display none -serial stdio -monitor none -no-reboot "$@"
