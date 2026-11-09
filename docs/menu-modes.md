# 原版启动与可选 A7C2 菜单

本产品默认运行 ZV-E10 2.03 原 AP 和原菜单。不需要 A7C2 BODYDATA、字体或资源。窗口为原 guest 完成帧的预览，方向操作经原 EventManager 和 UI 线程消费，不是 host 绘制的相似界面。

## 两种模式

| 模式 | 入口 | A7C2输入 | 原菜单树 |
|---|---|---|---|
| 原版（默认） | `./start.sh` 或 `./start-zve10-menu.sh` | 不读取 | 保持原树，不追加入口 |
| 可选菜单 | `./start-a7c2.sh`，或显式 `--a7c2-assets <ZIP>` | 固定版本最小资源包 | 设置5追加New Menu，确认进入，MENU返回 |
| 原系统串口 | `./start-zve10.sh` | 不读取 | 不运行窗口适配 |

源码checkout第一次需要按 [setup.md](setup.md) 准备ZV-E10运行环境；一键包已包含准备好的启动CPIO、内核、编译QEMU、工具链和官方ZV-E10更新包。`./start.sh`检查Linux x86_64、Python3.11+和普通Python/Tk依赖；没有桌面显示时自动使用headless检查。它不是Windows原生可执行文件。

## 实现边界

- `scripts/menu_build.py`从本目录 `source/ui/` 的原观察器派生候选。原CPIO、原3个ELF和原观察器身份守卫不放宽，原件不写入。
- 原版只加入原UserMain观测和UART/帧捕获；编译 `source/menu/original.inc`，不导入 `original_assets.py`、不编译 `menu_shell.c`、不加入A7C2标题符号hook。
- 可选模式编译 `native_entry.inc` 和同目录原资源C核心；版本ABI与业务布局保持分离。采用已核原clone/init追加节点，不直接写原设置值。
- `source/menu/menu_hooks.inc`共享已验Thumb跳转器。2mod4入口的字对齐literal和跨页保护保持，原12字节窗口必须完整且PC独立。
- `transport.inc`缓存实际完成帧，保留ACK生命周期。**只选择本次真实present的物理目标及匹配摘要**，避免双缓冲中的旧原页配新状态。
- 运行期构建和捕获只访问本产品目录与本次临时socket。没有 `a7c2-re`、历史run或旧外部ZVE10目录的导入依赖。

原版方向预览不开放设置确认/MENU退出业务，避免将尚未验证的全部原设置行为暴露成产品能力。可选模式的确认只允许新增入口，其余原条目确认仍受限。

## 新增行的文字

原 AP 只绘制“资源布局存在”的标签，因此给新增行一个自有 ID 时，原标签管线不会产生可见文字（实测：钩子命中但像素为空，且给该行借用已有 ID 会连带改写同 ID 的其它行）。

当前做法：在原提交路径（`native_entry_present`）里，用 **A7C2 原字体** 生成的 alpha，把新增行文案绘制到该行标签框（`x=24,y=332`，对应 Setup5 页第 5 行）。这由本适配在 guest 内完成，不是 host 侧合成，也不改写其它行；但它是**我们的渲染器**，不是原 AP 的标签管线，故不宣称原标签路径已通。若页面行位/滚动改变，需同步调整该定位常量。

为避免原标签的异步绘制偶尔叠出一份重复文字，该行的原标签被置为空串，只保留上述确定性绘制。验收同时要求该框内存在真实字形像素与橙色选中条，两者缺一即失败。

## 资源包导入

`menu_resources.py`只接受固定版本包中的10项Sony资源和2份公开解码器。ZIP必须有固定前缀，逐项核尺寸和SHA，拒绝路径穿越、别名、重复、symlink、加密、超限及未知成员。归档自身的manifest不是信任来源。新目录经私有staging校验后原子安装，已有目录不覆盖。

```bash
python3 scripts/menu_resources.py \
  --bundle incoming/a7c2-menu-resources-2.01-v1.zip \
  --destination work/a7c2-menu-assets
./start-zve10-menu.sh --a7c2-menu
```

也可直接 `./start-zve10-menu.sh --a7c2-assets incoming/a7c2-menu-resources-2.01-v1.zip`。按ZIP摘要缓存的目录位于 `work/a7c2-import-<sha前缀>/`，复用前仍核全部原资源摘要。目录输入只接受已整理的最小十文件根，不接受完整系统dump或未提取的BODYDATA。

A7C2图标、文案和字体仅在可选模式构建时读取，由guest内C核心合成。不会执行A7C2的64位程序；新菜单仍为空内容页，不是完整SDK。

## 检查

```bash
python3 tests/test-native-menu.py
python3 tests/test-menu-resources.py
./start.sh --headless
```

菜单入口的自动验收同时要求 **New Menu 实际字形** 与 **橙色选中条实际像素** 均命中。只检查内部 `selected_own`/`title_sets`、或“返回前后都是空白”都不算通过；判定区域与期望字形来自已人工看过的原帧，不从新输出自动更新期望。

实资源导入用例可通过 `A7C2_RESOURCE_ZIP` 指定本地ZIP；未给原件时对应检查明确skip，不冒称实资源通过。可见窗口检查使用 `xvfb-run -a ./start.sh --self-test`；可选模式同样加资源参数。

验收按源码、host、原UI输入、实际帧内容、可见窗口及正常QMP退出分账，见 [menu-validation.json](menu-validation.json)。原版和可选模式分别记账，不把原版通过当新菜单通过，也不把旧报告的成功直接回填产品新运行。

## 当前未完成

可用拍摄主页面、实时取景、传感器/镜头/AF、拍照/录像和全部原设置后端均未完成。没有物理相机/SD测试，没有真机部署。所有功能检查仅在本机隔离QEMU进行，`query-block`必须为空。

一键包中的官方固件、已提取原件、内核/工具链/动态库不进入Git；源码可公开，原厂资源包只按本机交付授权提供。随包QEMU库由其manifest逐项核验，专属loader只用于QEMU，不全局改变 `LD_LIBRARY_PATH`。

## 本机一键包

```bash
python3 scripts/package-ready.py --out release/zve10-qemu-linux-x86_64-v1.tar.gz
```

构建器只从本目录已验证的运行文件与官方更新包取材，逐文件读回摘要，在私有 staging 目录生成 tar.gz，并写出同名 `.sha256` 与 `.json` 收据。`release/`、`work/`、`incoming/`、`output/` 均被 Git 忽略。包内 `start.sh` 为原版默认，`start-a7c2.sh` 为可选菜单；两者都先检查主机架构、Python 版本和依赖。

包不包含 Windows/macOS 可执行文件；Linux x86_64 仍是唯一目标平台，且包含原厂固件，按本机研究用途分发。

## 拍摄主页面（未完成，已有探测结论）

用户目标是拍摄主页面，不是菜单入口。当前探测（`--start-page shoot`）：

- AP 会进入拍摄页状态（view slot `0xa0`），但只清屏：3 次 framebuffer 绘制、**0 次字形绘制**，最终帧为纯色，UI 线程停在 `osal_wai_sem_tmo`（sem `0x170604c`）。说明它在等取景/成像数据，才会绘制 OSD。
- 合成功能事件（`0x13000000|(0xa0<<12)|f`）会被触发表重映射为 `0x11012001` 等通用 trigger，**原 AP 消费次数为 0**，页面不跳转。
- 改投真实输入表 id（`0x150100f0/0x15010040/...`）时，`ViewBase::Main` 确实被调用（59 次），但 view 与像素均不变，说明这些 id 不在拍摄页的可用映射里。

补充探测（`--map-probe`）：调用原 `ViewBase::transformByTriggerTable` 对输入表里的 235 个候选 id 做映射，**全部返回同一个常量 trigger `0x11012005`**，说明拍摄页的这个视图根本不做 trigger 变换（变换函数的前置守卫返回 0，直接走常量分支）。

因此拍摄页的按键不能靠“合成 trigger 表 id”实现，必须在更下层用原 `InputService` 的 24 字节 `_InfraInputEvent`。

反编译 `sub_11fbbc(service, _InfraInputEvent*, mode)` 已给出完整路径：它先 `snd_InfraInputEvent_to_InputServant(evt)` 做 keymode/repeat 记账，再 `InputService::createEvent(evt->+0, 4)` 查输入表生成事件、附加参数 `0x1b/0x1c/0x20`，最后 `pushFilterEvent`。`service` 参数在函数体内未被使用（单例取自全局）。

**但仍未打通**：调用该函数会阻塞在 `snd_InfraInputEvent_to_InputServant`（等 InputServant 握手），导致后续不再产生帧、探测超时（从控制线程投递同样阻塞，因此不是线程归属问题）。

尾段绕过尝试的取证：
- `InputService::createEvent(0x11c89b)` **不使用 this**（入口即 `movs r0,#0x10`），可以直接调用建事件；
- `InputService::pushFilterEvent(0x11e5d5)` **使用 this**（`this+0x10` 作锁），因此仍需真正的 InputService 单例；
- 该单例在 `sub_11fbbc` 中取自 libObj 全局（`*dat_13db2ac`），尚无稳定取法。

已找到单例：libObj 全局 `object_base+0x13dba70`（由 `sub_11fbbc` 的字面量基址换算）。用该单例直接调用 `createEvent(0x11c89b, id, 4)` + `pushFilterEvent(0x11e5d5, ev)` 的尾段注入实测：

- 事件确实进入了原分派（`NE_BASEMAIN` 从 0 跳到 53 次），
- 但注入调用本身**不返回**（无 `NE_TAIL_INJECTED`），控制线程卡在 `pushFilterEvent` 内，
- 期间只发生 5 次 framebuffer 绘制。

结合早先“UI 线程停在 `osal_wai_sem_tmo` 等取景数据”，可以判定：**拍摄页在取景数据到达前，连输入分派都不会完成**。因此“只做按键与页面导航、不接取景源”在拍摄页上不可行——两者被同一个等待绑在一起。

结论：要么接入最小功能取景源（`virtual-functional-camera-v1`，用户在 AGENTS 中已授权过该模式的边界），要么接受拍摄页按键/导航暂不可验。

取景源仍按用户选择暂不实现，所以即使按键接通，拍摄页背景仍为纯色。

探测开关：`--start-page shoot`、`--key-probe`、`--id-probe`。它们只用于取证，不改变默认启动行为。
