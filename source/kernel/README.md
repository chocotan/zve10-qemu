# ZV-E10 kernel source changes

The source base is Sony's ZV-E10 Ver.2.02 OSS `linux-kernel.tar.gz`
(Linux 3.0.27), used with the ZV-E10 2.03 firmware in this project.
Download it separately and place it at `work/linux-kernel.tar.gz`:

- URL: https://prodgpl.blob.core.windows.net/download/DI/ZV-E10_Ver.2.02/linux-kernel.tar.gz
- SHA-256: `2a5f29bd10da6bad1636641820c7b32ab7d8977f76b7220a1594c4b18bf44428`
- License: the original archive's `COPYING`, copied here without modification.

`0001-zve10-qemu.patch` captures all 39 modified source files found by
comparing the existing working kernel against every regular file in that
archive, plus the added `include/linux/compiler-gcc9.h` compatibility header.
It contains no build outputs or generated files. The unused local GCC 16
compatibility header is omitted; the ARM cross compiler used here is GCC 9.3.0.
The archive's `.config` is deliberately replaced with a separate output config.

The patch preserves the existing assembler syntax fixes, bootloader ATAGS
pointer, initramfs linker placement, MMCI registration, DDR alias handling,
procfs workarounds and `put_user` register fix. The procfs and DDR changes are
existing emulator workarounds, with limitations documented in the patch;
this is not a kernel intended for installation on a physical camera.

`zve10_defconfig` was generated with `make savedefconfig` from the identical
verified `work/kbuild-clean/.config` and `work/kbuild-ui/.config`. Its machine
specific absolute initramfs path has been cleared; set it before building.
The embedded `work/camera.cpio` must be prepared separately. The bootloader
ATAGS fix also allows a separate external initramfs through QEMU's `-initrd`.

## Manual build

Run from the repository root on Linux with GNU make, patch, a host C compiler,
and the ARM GCC 9.3.0 cross toolchain available. These commands use a fresh
source directory and leave an existing `work/linux-kernel` unchanged.
Do not repeat extraction over an existing source directory.

```sh
printf '%s  %s\n' \
  2a5f29bd10da6bad1636641820c7b32ab7d8977f76b7220a1594c4b18bf44428 \
  work/linux-kernel.tar.gz | sha256sum --check -

mkdir -p work/sources
# Require an unused directory; remove nothing from an existing checkout.
test ! -e work/sources/linux-kernel || exit 1
tar -xzf work/linux-kernel.tar.gz -C work/sources
src="$PWD/work/sources/linux-kernel"
out="$PWD/work/build/kernel"
cross="$PWD/work/armv7-eabihf--glibc--stable-2020.08-1/bin/arm-linux-"
patch --batch --forward -d "$src" -p1 < source/kernel/0001-zve10-qemu.patch
# The archive includes an in-tree .config, which prevents an O= build.
rm "$src/.config"
mkdir -p "$out"
cp source/kernel/zve10_defconfig "$out/.config"
test -s "$PWD/work/camera.cpio" || exit 1
"$src/scripts/config" --file "$out/.config" \
  --set-str INITRAMFS_SOURCE "$PWD/work/camera.cpio"
make -C "$src" O="$out" ARCH=arm CROSS_COMPILE="$cross" oldnoconfig
make -C "$src" O="$out" ARCH=arm CROSS_COMPILE="$cross" \
  KBUILD_BUILD_USER=zve10 KBUILD_BUILD_HOST=builder KBUILD_BUILD_VERSION=1 \
  KBUILD_BUILD_TIMESTAMP='Thu Jan 1 00:00:00 UTC 1970' \
  -j"$(getconf _NPROCESSORS_ONLN)" Image
```

The resulting image is `work/build/kernel/arch/arm/boot/Image`. Existing launchers
may still reference `work/kbuild-clean/arch/arm/boot/Image` or
`work/kbuild-ui/arch/arm/boot/Image`; use the new image path explicitly when
launching a manually rebuilt kernel. Fixed build metadata alone does not
establish byte-for-byte reproducibility across different hosts or initramfs
archives.

Validation performed for this source package: the patch dry-run and application
both passed against a fresh extraction of the pinned archive. All 19,720 regular
archive files other than `.config` then matched the existing working kernel,
as did the added GCC 9 header. `savedefconfig` and `oldnoconfig` completed using
that patched extraction; restoring the initramfs path reproduced the original
verified full config byte-for-byte. A full rebuild of this packaged source has
not been run. Existing kernel build directories were not modified.
