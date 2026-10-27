# 准备与编译

仓库提供模拟器代码和补丁。固件、Linux、QEMU 和 ARM 工具链需要自行下载；下载位置见 [README](../README.md)。以下命令在仓库根目录执行，面向 Linux x86_64。`work/` 是本地工作目录，不会提交到 Git。

这是源码项目，第一次使用需要解包固件和编译。三个启动命令不会自动完成这些步骤。

## 1. 安装依赖

Debian / Ubuntu 可先安装：

```bash
sudo apt install build-essential ninja-build meson pkg-config \
  libglib2.0-dev libpixman-1-dev python3 python3-venv python3-pil \
  cpio p7zip-full e2fsprogs fakeroot patch git curl \
  libssl-dev libncurses-dev bc bison flex
mkdir -p work
```

其他发行版安装对应软件包。Python 必须能导入 `PIL`。下载文件的 SHA-256 记录在 [downloads.sha256](../source/downloads.sha256)，可在仓库根目录运行 `sha256sum -c source/downloads.sha256`。

## 2. 解包固件

支持的是 **ZV-E10 2.03 macOS 更新包 `Update_ZVE10V203.dmg`**。它只作为数据文件使用，不需要运行 Sony 更新器。

解包工具 [fwtool.py](https://github.com/DavidBuchanan314/fwtool.py) 及其依赖不包含在本仓库，需要单独安装：

```bash
git clone https://github.com/DavidBuchanan314/fwtool.py work/fwtool
git -C work/fwtool checkout cdba742b73eed5981480c326aeb30033aabf0223
python3 -m venv work/fwtool-venv
work/fwtool-venv/bin/pip install pyyaml pycryptodome
```

然后运行本仓库的解包脚本。它会校验更新包版本、取出固件镜像、解密解包，并把相机文件系统放到 `work/rootfs`、`work/usr`、`work/boot`，设置放到 `work/setting` 和 `work/tmp`：

```bash
python3 scripts/prepare-firmware.py --fwtool-python work/fwtool-venv/bin/python
```

默认读取仓库根目录的 `Update_ZVE10V203.dmg`，并在 `work/fwtool/fwtool.py` 查找 fwtool。如果放在别处，加上 `--dmg` 和 `--fwtool` 参数。上面固定的是已检查过兼容性的 fwtool 版本。中间解包目录默认保留；加 `--keep-intermediate` 会一并保留从 DMG 取出的临时文件。

脚本不覆盖已有的 `work/rootfs`、`work/usr` 等提取目录。需要重新解包时，请先保留或重命名这些目录。

脚本不会执行固件里的任何程序，也不会刷写相机。

固件里的主要内容如下：

| 路径 | 内容 | 本地用途 |
| --- | --- | --- |
| `0700_part_image/dev/nflasha3` | FAT 启动分区，含 `initrd.img` | 提取启动模块到 `work/initrd/` |
| `0700_part_image/dev/nflasha7` | ext2 根文件系统 | 提取到 `work/rootfs/` |
| `0700_part_image/dev/nflasha15` | ext2 `/usr` 文件系统 | 提取到 `work/usr/` |
| `0800_appli/setting` | 内存配置等设置 | 复制到启动文件系统的 `/setting` |
| `0800_appli/tmp` | 字体、配置等运行文件 | 复制到启动文件系统的 `/tmp` |
| `0110_backup/SYSASTRA-DSLR/RK/CX88701_ALLLANG.bin` | 固件自带设置模板 | 复制为 `/setting/Backup.bin` 和 `Backup.bak` |

解包脚本会用 `7z` 解开 FAT 分区、用 `debugfs rdump` 解开 ext2 分区。普通用户无法恢复原始文件所有者，脚本会提示；启动时所需的控制台设备节点在下一节统一生成。根文件系统本身已包含 `/kmod`。如果要单独查看启动分区中的 `initrd.img`，可运行：

```bash
mkdir -p work/initrd
debugfs -R "rdump / work/initrd" work/boot/initrd.img
```

不要在 Windows 文件系统上展开后再直接当作相机根目录，权限和设备节点会丢失。

## 3. 准备工具链和启动文件系统

```bash
tar -xjf work/armv7-toolchain.tar.bz2 -C work
export CROSS_COMPILE="$PWD/work/armv7-eabihf--glibc--stable-2020.08-1/bin/arm-linux-"
```

启动器默认使用上述工具链位置。构建过的内核是 GCC 9.3.0 版本，不建议直接换成宿主机最新的 ARM GCC。

运行启动文件系统组装脚本：

```bash
fakeroot -s work/fakeroot.state python3 scripts/prepare-initramfs.py
```

脚本会编译命令行的 `/init`，从解包结果组装 `work/initramfs-camera/` 和 `work/initramfs-ui/`，准备控制台设备节点，并生成 `work/camera.cpio`。UI 根目录同时包含原厂 `/usr`、启动分区里的 `/system` 文件、设置和临时字体文件。`/kmod` 已包含在提取出的根文件系统中，无需手工再复制。

`fakeroot` 让普通用户也能生成设备节点。`work/fakeroot.state` 记录这些节点的信息；后续 UI 启动时会读取它重新打包。请保留这个文件，也不要只把两个根目录复制到另一处后继续使用旧状态文件。

脚本会拒绝覆盖已有的 `initramfs-camera/` 或 `initramfs-ui/`。重新准备前请先保留或重命名原目录，尤其是自己修改过的固件文件和设置。

此时内核还没编译，所以脚本可能提示缺少 `dma330_stub.ko`。先完成下一节的内核和模块编译，再按说明把模块复制进 UI 根目录即可，不必重新组装整个目录。

UI 使用外部 initramfs，启动脚本会重新打包它。界面加载配置由 `scripts/prepare-ui-profile.py` 从原厂库创建副本，原始 `work/usr/lib/libIMDB.so` 保持不变。

## 4. 编译 Linux

内核补丁位于 `source/kernel/0001-zve10-qemu.patch`，配置位于 `source/kernel/zve10_defconfig`。只对新解压的源码应用一次补丁：

```bash
tar -xzf work/linux-kernel.tar.gz -C work
patch -d work/linux-kernel -p1 < source/kernel/0001-zve10-qemu.patch
rm -f work/linux-kernel/.config
mkdir -p work/kbuild-clean
cp source/kernel/zve10_defconfig work/kbuild-clean/.config
work/linux-kernel/scripts/config --file work/kbuild-clean/.config \
  --set-str INITRAMFS_SOURCE "$PWD/work/camera.cpio"
make -C work/linux-kernel O="$PWD/work/kbuild-clean" ARCH=arm \
  CROSS_COMPILE="$CROSS_COMPILE" oldnoconfig
make -C work/linux-kernel O="$PWD/work/kbuild-clean" ARCH=arm \
  CROSS_COMPILE="$CROSS_COMPILE" -j"$(nproc)" Image modules
```

命令行和 UI 使用相同配置。可将该内核复制到 UI 启动器读取的位置：

```bash
mkdir -p work/kbuild-ui/arch/arm/boot
cp work/kbuild-clean/arch/arm/boot/Image work/kbuild-ui/arch/arm/boot/Image
```

UI 初始化需要 `dma330_stub.ko` 的两个兼容导出；它只用于模块符号兼容，不提供真实 DMA。用同一个内核构建目录编译本地模块：

```bash
cp -a source/modules work/modules
make -C work/linux-kernel O="$PWD/work/kbuild-clean" ARCH=arm \
  CROSS_COMPILE="$CROSS_COMPILE" M="$PWD/work/modules/dma330-stub" modules
cp work/modules/dma330-stub/dma330_stub.ko work/initramfs-ui/usr/kmod/
```

更多内核改动说明见 [source/kernel/README.md](../source/kernel/README.md)。这里的内核仅用于模拟器。

## 5. 编译 QEMU

```bash
tar -xJf work/qemu-11.1.2.tar.xz -C work
mv work/qemu-11.1.2 work/qemu-src
cp source/qemu/hw/arm/zve10.c source/qemu/hw/arm/zve10-gpe-init.h work/qemu-src/hw/arm/
cp source/qemu/hw/timer/sony_hwtimer.c work/qemu-src/hw/timer/
patch -d work/qemu-src -p1 < source/qemu/0001-register-zve10.patch
mkdir -p work/qemu-src/build-zve10
(cd work/qemu-src/build-zve10 && ../configure \
  --target-list=arm-softmmu --disable-docs --disable-werror)
ninja -C work/qemu-src/build-zve10
```

不要把本项目的板级文件直接复制到其他 QEMU 大版本，接口可能不同。

## 6. 启动

```bash
./start-zve10.sh
python3 scripts/capture-menu.py
```

第一条进入命令行，第二条运行原厂应用并保存菜单图片。它们是两个独立的启动方式，无需同时运行。图片路径会打印在终端，默认在 `output/`。

菜单文字和图片需要加载，初始帧可能为空。截图脚本会等待原厂字形和画面完成，不需要给真实相机执行任何升级操作。

## 测试

`tests/` 包含 CPU 绘图、Sony LZ77、图像锁、缓冲复制、截图等测试。大部分测试只需要宿主 GCC 和 Python。例如：

```bash
cc -std=gnu11 -O2 -Wall -Wextra -Werror -fsanitize=address,undefined \
  tests/test-zve10-gemini.c -o /tmp/zve10-gemini-test
/tmp/zve10-gemini-test
python3 tests/test-capture-headless.py
```

`test-zve10-lz77.c` 和 `test-zve10-image-decode.c` 的原厂图片用例需要从使用者自己的固件提取测试数据。这些图片数据不随仓库分发；缺少数据时这两个测试会输出 `SKIP` 并正常退出，有了数据再运行会执行完整用例。`check-runtime-evidence.py` 同样需要本地保存的运行日志。

`thread-join.c` 需用 ARM 交叉工具链编译，并在启动后的相机系统里运行，用于验证线程退出和 `pthread_join`。

准备流程也有独立测试，不需要固件：

```bash
python3 tests/test-prepare-firmware.py
python3 tests/test-prepare-initramfs.py
```

前者检查更新包、DAT 和解包错误处理；后者检查归档包含文件、符号链接和设备节点，验证已有目录不会被清空，并确认保存的 fakeroot 信息能用于后续重新打包。

## 构建验证

本仓库的 QEMU 补丁和内核补丁在官方归档上做过完整验证：

- QEMU 11.1.2 官方源码应用 `source/qemu/0001-register-zve10.patch` 后可以配置和编译，`-M zve10` 正确注册。
- Sony Linux 3.0.27 官方源码应用 `source/kernel/0001-zve10-qemu.patch` 的 40 个文件全部干净应用，用 `zve10_defconfig` 编译得到 `Image` 和 19 个模块。
- `scripts/prepare-firmware.py` 从官方 2.03 更新包解出的 `work/rootfs` 和 `work/usr` 与已验证可启动的版本逐文件一致。
- 用新解包的固件、`prepare-initramfs.py` 新组装的文件系统，以及上述新构建的 QEMU、内核和模块，分别启动到 BusyBox `/ #`，并导出包含图标、文字及设置条目的 640×480 原厂菜单。截图使用普通用户保存的 fakeroot 信息打包，不需要管理员权限。

这些验证使用 GCC 9.3.0 交叉工具链和官方 QEMU 11.1.2，换用其他版本可能需要在 `source/` 的补丁上做调整。
