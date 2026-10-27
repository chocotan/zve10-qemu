#!/usr/bin/env bash
# AP-only original-firmware UI with software rendering and native frame capture.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
work="$root/work"
qemu="$work/qemu-src/build-zve10/qemu-system-arm"
image="$work/kbuild-ui/arch/arm/boot/Image"
cross="${CROSS_COMPILE:-$work/armv7-eabihf--glibc--stable-2020.08-1/bin/arm-linux-}"
[[ -x "$qemu" && -f "$image" ]] || { echo '先构建 QEMU 和 work/kbuild-ui 的 Image' >&2; exit 1; }
"${cross}gcc" -shared -fPIC -O2 -Wall -Wextra -Werror \
    -o "$work/initramfs-ui/usr/lib/libuiobserve.so" "$root/source/ui/ui-observe.c" -ldl
mkdir -p "$root/evidence/ui-startup"
python3 "$root/scripts/prepare-ui-profile.py" > "$root/evidence/ui-startup/ap-profile.json"
(cd "$work/initramfs-ui" && find . -print0 | cpio --null -o -H newc --quiet) > "$work/ui.cpio"
exec "$qemu" -M zve10 -cpu cortex-a9 -smp 1 -m 1024 \
    -kernel "$image" -initrd "$work/ui.cpio" \
    -append 'console=ttyAM0,115200n8 cfg.uart=1 mem=1G@0 memrsv=0x1A5E000@0x02E68000 memrsv=128M@0x20000000:uc rdinit=/init loglevel=8' \
    -display none -serial stdio -monitor none -no-reboot "$@"
