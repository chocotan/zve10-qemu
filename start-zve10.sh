#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
work="$root/work"
qemu="$work/qemu-src/build-zve10/qemu-system-arm"
image="$work/kbuild-clean/arch/arm/boot/Image"
[[ -x "$qemu" ]] || { echo "缺少 QEMU: $qemu（先构建 work/qemu-src/build-zve10）" >&2; exit 1; }
[[ -f "$image" ]] || { echo "缺少内核: $image（先构建 work/kbuild-clean）" >&2; exit 1; }
exec "$qemu" -M zve10 -cpu cortex-a9 -smp 1 -m 1024 \
    -kernel "$image" -display none -serial stdio -monitor none -no-reboot "$@"
