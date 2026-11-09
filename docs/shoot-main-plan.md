# 拍摄主页面：按 A7M4 方法接入（进行中）

## A7M4 的可行做法（已读其报告）

`final/a7m4-qemu/report/2026-11-03-a7m4-qemu-bringup/2026-11-04-skip-first-setup.md`：

- 不补 UI、不画 OSD；用 **原 Backup API** 在 guest 启动前预置首设状态：
  - `02cf0014`（首设请求）= 0
  - `01070140`（镜像记录）= 0
  - `02cf1701`（触摸教学已显示）= 1
- 再用原 `udate` 准备日期（类型 UTC、boot 原因 4），保留固件默认 `2021-01-01`。
- 结果：原开机控制器自然走 `315 → 355 → 351 → 0`，直接进拍摄 UI，原 bitmap 出现 `NO CARD`、`J-FINE 14M`、`AF-S` 等 OSD；取景区仍黑。
- 限制照旧：CMOS/镜头/AF、按键、拍照录像、虚拟卡均未因此通过，`capture_verified=false`。

## ZV-E10 现状与已核事实

- 拍摄页探测：view slot `0xa0`，3 次 framebuffer 绘制、**0 次字形**、纯色帧；UI 线程停在 `osal_wai_sem_tmo`（sem `0x170604c`）。
- 合成功能事件、真实输入表 id、`transformByTriggerTable`（235 个候选恒返回 `0x11012005`）三条路已排除。
- 尾段注入（`createEvent + pushFilterEvent`，单例 `object_base+0x13dba70`）能进入原分派（`NE_BASEMAIN` 0→53），但 `pushFilterEvent` 不返回。
- 结论：拍摄页在取景/首设完成前，连输入分派都不会走完；因此“只做按键”不可行，必须先让 AP 自然进入拍摄 UI。
- 模块对照：ZV-E10 固件里存在 `input/indctr/upm/mcmn_drv/codec_drv/keyinject`；加载 `input`、`indctr`、`keyinject` 成功（`upm.ko` 会卡住启动，已排除）。
- Backup ID：`01070140` 在 `libObj.so` 出现 6 次（与 A7M4 同名同值），但 `02cf0014`/`02cf1701` 未以字面量或 `movt #0x2cf/#0x107` 出现，说明 ZV-E10 的对应 ID 编码/编号不同。

## 已知 ZV-E10 的 Backup 用法（2026-11-09）

`kuna xrefs` 可直接给出调用点（比手写 PLT 扫描可靠）：`Backup_nread` 13 处、`Backup_write` 162 处，桩在 `0x10da50` / `0x10827c`。

已读出的调用与 ID：

| 函数 | 调用 | 含义线索 |
| --- | --- | --- |
| `sub_87ccac` / `sub_881db0` / `sub_88362c` | `Backup_nread(0xa10019, &byte, 1)`，取值 0/1/2 | 某模式字节（0/1/2 三态） |
| `sub_6f4c74` | `Backup_nread(0x1700000, setting, 4)` | `dmpNative::SystemImpl::initialize_setting()` |
| `sub_3a3e08` | `Backup_nread(0x1820000, &byte, 1)` → `sub_3a3dea(0x800,0x447,…)` | 单字节开关 |

ZV-E10 的编号体系与 A7M4（`02cf0014/01070140/02cf1701`）不同；`01070140` 在 libObj 出现 6 次但属于日期/时区函数，不是首设镜像写入。

## 2026-11-09 长窗口探针（关键）

`--start-page shoot` 运行 68 帧后统计：

| 指标 | 拍摄模式 | 菜单模式（对照） |
| --- | --- | --- |
| drawFramebuffer | 14 | 15 |
| GEMINI.cpu.glyph_draw / glyph_images | **0 / 0** | 37 / 7–13 |
| GPE.clear | 3 | 9 |
| 存在的视图 | 0xa3 / 0xa1 / **0xa0** | 同左 + 0x11(BaseMenu) / 0xba(SettingMenu) |

结论：拍摄主视图形（0xa0）从开机就存在，但**字体子系统从未初始化**（glyph_images=0），因此不可能画出任何 OSD。菜单模式能画，是因为我们主动调 `0x590f35(1)` + `0x47de27(sel,0)` 打开 BaseMenu，连带触发 UI/字体加载。

另确认 `sub_47de26(node,a1)`：`a1!=0` 时什么都不做；`a1==0` 才 `openView(0x11)`。所以它不是拍摄入口。

日志显示 `/usr/bin/im.elf` 确实在运行；拍摄侧只有等待（`osal_rcv_msg_tmo`）与 ulogio 写满（`cat: write error: No space left on device`，发生在 12 MiB 的 kmsg/日志分区）。

## 2026-11-09 关键更正：拍摄 UI 的宿主进程是 im.elf

日志按 pid 统计（`output/shoot-long-v1`）：

| pid | 角色 | UI_OBSERVE 行数 | drawFramebuffer | native.view.id |
| --- | --- | --- | --- | --- |
| 108 | **im.elf** | 3463 | 14 | 21（0xa3/0xa1/0xa0） |
| 103 | bootin.elf | 仅启动早期 | 0 | 0 |

`im.elf` 的 `DT_NEEDED` 不含 libObj，它 `dlopen("/usr/lib/libObj.o")`，所以视图系统在 im.elf 进程里。**开机后 bootin 退出、im.elf 接管并进入拍摄流程**——之前所有视图/事件探测都跑在 pid 108 上，这没错，但“0xa0 是拍摄主视图”这个对应关系此前未确认。

`sub_47de26(node, a1)` 已核：`a1 != 0` 时不做任何事，只有 `a1 == 0` 才 `openView(0x11)`；它是“打开设置菜单”，不是拍摄入口。

## 由此得到的判断

ZV-E10 的拍摄 OSD 依赖相机/成像模型先给状态；A7M4 的 OSD 不依赖，所以两者不同。要让 ZV-E10 出现拍摄页 OSD，需要**功能相机模型**（AGENTS 中 `virtual-functional-camera-v1` 已授权），而不是继续在 Backup 种子上打转。

## 2026-11-09 队列观测（600 条消息）

放宽派生观察器的 `osal_snd_msg` 记录后（仅构建产物，原文件不改），拍摄模式 600 条消息按队列统计：

| 队列 | 条数 | 判断 |
| --- | --- | --- |
| `0x8f013a` | 564 | ulogio 日志通道（`testmode_debugPrint`），非模型请求 |
| `0x7a804c` / `0x7a0020` | 15 / 5 | 少量事件 |
| `0x9c015b` / `0x630130` / `0x5700f9` | 3 / 3 / 2 | 少量事件 |
| `0x11006e9` | 1 | 单条 |

**结论**：im.elf 在拍摄页几乎不发模型请求，绝大部分是自诊断日志。也就是说它并不是“在等某个我们没回的请求”，而是**停在一个更早的状态**（字体与资源从未加载）。这排除了“补一个应答就能出 OSD”的假设。

## 2026-11-09 模块补充试验（否定）

在共享启动脚本上临时追加 `input indctr keyinject udate mcmn_drv codec_drv`（全部 `status=0` 加载成功）后重跑拍摄模式：

- `GEMINI.cpu.glyph_images` 仍为 **0**，`glyph_draw` 0，framebuffer 绘制 15；
- 即补模块**不会**让字体/资源初始化。

试验已回退，共享 `init-ui.sh` 恢复到已验证基线（不含该模块循环）；随后重新回归两种交付模式均通过（见 `docs/menu-validation.json` 的 `regression_after_shoot_probe`）。

同轮发现并修掉一个**验收脚本 bug**：拍摄模式此前仍执行菜单导航（DOWN/UP），而拍摄页帧是纯色不变的，导致 `No fresh native frame after DOWN` 超时。现改为 `shoot_observe()`：只连续抓帧并记录颜色多样性，不再要求帧变化。修复后拍摄模式 `ok=true`、`qemu_rc=0`，采样 `color_samples=[1]`（纯色），再次确认没有 OSD。

## 2026-11-09 决定性更正：两种模式的绘制进程都是 im.elf

按 `/proc` 命令行核对：菜单模式（`reg-original3`）里 **pid=103 就是 `im.elf`**，不是 bootin。
即 `bootin.elf` 只负责把 `im.elf` 拉起来，之后所有视图与绘制都在 `im.elf` 内（`im.elf` 自己 `dlopen("/usr/lib/libObj.so")`）。

这解释了全部现象：菜单能显示，是因为我们主动调用 `try_original_menu()`（`0x590f35(1)` + `0x47de26(sel,0)` → `openView(0x11)`）让 im.elf 打开了 BaseMenu，连带触发字体/资源加载（`glyph_images` 13）。拍摄模式不调用它，im.elf 就停在开机后的初始视图（0xa0）上，`glyph_images=0`。

信号量等待解析（`SEMWAIT`，按 dladdr 取模块）只显示调用点在 `im.elf+0x380d/0x3865`（它的等待包装函数），无法定位子系统；实际等待的 sem id 主要是 `0x9401c3`（46 次）、`0x83e03f`、`0x7a008d`、`0x830451`、`0xcfe012`、`0x170604c/4d`。

## 2026-11-09 打开视图试验（崩溃，否定）

用根选择器（slot 0xa3）节点的 `vtable+0x90`（`0x47de26` 里用来打开 view 0x11 的那条路）按 id 打开候选视图（0xa0/0xa1/0xa2/0xa4/0xa5/0xb0/0x11）：

```
program: /usr/bin/im.elf(Appframework)
address: 80bff6f6, trap 0x0e, section permission fault (0x8000002d)
→ Entering exception monitor
```

即 `root+0x154` 取到的节点指针/该槽语义与假设不符，直接打崩 im.elf。该试验保留为 `--open-probe`（默认关闭，不影响两种交付模式；随后回归 `reg-original4` 通过：14 帧 / ok）。

结论：**不能靠“按 id 直开视图”绕过启动推进**。要出拍摄页，必须让 im.elf 按原逻辑走到拍摄视图，也就是补它缺的启动/资源推进（功能相机模型方向）。

## 下一步（未完成）

1. 在 ZV-E10 中定位首设相关的 Backup 读写调用点：从 `BackupManager::Bkup_Read/Bkup_Write` 或 `Backup_read/Backup_nread` 的 PLT 调用点回溯，取第一参数（ID）。
2. 与 `01070140` 并列的镜像写入处（6 处之一）通常同一函数内还有主记录写入，可作为定位锚点。
3. guest 内用原 Backup API 写入并读回（仅本次虚拟机副本/内存，`Backup_save=0`，不改原 `Backup.bin`）。
4. 复核原屏序列是否到达拍摄 UI；抓原 bitmap 像素确认 OSD 出现。
5. 之后才是按键/导航与取景源。

## 边界

只在本机隔离 QEMU；不接真机、不写真实 SD；原固件只读；`capture_verified` 在取景链路未通前保持 false。
