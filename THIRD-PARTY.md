# 源码来源和许可证

本仓库自行编写的启动脚本、宿主工具和文档使用根目录 [MIT 许可证](LICENSE)。第三方源码、内核补丁和派生文件适用各自许可证，不因根目录许可证而变更。

| 内容 | 来源 | 许可证 |
| --- | --- | --- |
| QEMU 板级模型、定时器及接入补丁 | 基于 [QEMU 11.1.2](https://download.qemu.org/qemu-11.1.2.tar.xz) | GPL-2.0-or-later，保留各文件标识，另见 `source/licenses/QEMU-GPL-2.0.txt` |
| Linux 补丁及配置 | [Sony ZV-E10 Ver.2.02 OSS](https://prodgpl.blob.core.windows.net/download/DI/ZV-E10_Ver.2.02/linux-kernel.tar.gz)，Linux 3.0.27 | Linux 源码各文件许可证，见 `source/kernel/COPYING` |
| `source/ui/ui-lz77.h` | 改编自上述 Sony Linux 的 `lib/lz77/lz77_inflate.c`、`include/linux/lz77.h` | Sony 原代码提供的 Dual BSD/GPL；文件保留 Copyright 2006,2007 Sony Corporation 及 BSD 声明 |
| ARM 交叉工具链 | [Bootlin armv7-eabihf glibc stable-2020.08-1](https://toolchains.bootlin.com/downloads/releases/toolchains/armv7-eabihf/tarballs/armv7-eabihf--glibc--stable-2020.08-1.tar.bz2) | 归档中各组件的许可证；工具链不随仓库分发 |
| 固件解包工具（使用者单独下载） | [DavidBuchanan314/fwtool.py](https://github.com/DavidBuchanan314/fwtool.py)，基于 ma1co/fwtool.py | 上游 MIT；不随本仓库分发 |
| 参考项目 | [chocotan/a7c2-qemu](https://github.com/chocotan/a7c2-qemu) | 上游各文件的许可证 |

Sony ZV-E10 固件更新包、解包后的内核镜像、相机程序、字库、图片资源、设置模板和原厂图片测试用例均不包含在 Git 仓库中，由使用者通过 Sony 官方渠道取得。`docs/images/menu.png` 展示本项目运行得到的原厂菜单，不作为本项目自有界面或可单独授权的图标/字体资源。

上游归档的版本、下载位置和摘要见 README 与 `source/downloads.sha256`。修改后的内核只用于模拟器，未用于真实相机。
