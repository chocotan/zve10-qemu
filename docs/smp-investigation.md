# ZV-E10 QEMU 双核（SMP）调查

日期：2026-11-09。动机：原机内核为 SMP PREEMPT RT（真机多核），单 vCPU 下 UIPC 同步回调路径出现非确定性卡死（v53 模块同步发送、v54 动态 ID ioctl、v55 完全不同的模型树分支），假设副核上线可解除竞态。

## 已完成：副核释放机制（成功）

- **QEMU 侧**（`source/qemu/hw/arm/zve10.c`）：0xfe000000 增设 32KiB eSRAM RAM 窗口（保存 BOOTRAM 工作区）；`arm_boot_info` 设 `smp_loader_start=0x110000`、`smp_bootreg_addr=0xfe005010`（BOOTRAM_VEC 的 CPU1 槽）、`gic_cpu_if_addr=0xf8000100`。QEMU 默认 SMP stub 在副核上轮询 bootreg，`boot_secondary()` 发 GIC 软中断唤醒后跳转。
- **内核侧**（`work/linux-kernel/platsmp.c`）：`platform_smp_prepare_cpus` 把 `cxd900x0_secondary_entry` 物理地址发布到 0xfe005010。必须由 platsmp 发布，因为 defconfig 的 `CXD900X0_QEMU=y` select 了 `SIMPLE_LOADER`，boot.S 里 `cxd900x0_smp_init` 的 BOOTRAM 发布被编译掉（真机由 bootMonitor 承接）。
- **实证**：v59/v67 串口出现 `qemu smp: secondary pen published` → `CPU1: Booted secondary processor` → `Brought up 2 CPUs`。副核机制本身工作。

## 新阻塞：CPU1 执行即内存覆写（确定性）

双核在线时 `sched_init_smp → build_sched_domains → get_group` 读到 `sd->child==1 / parent==0x7d / groups==2`（slab 对象被小整数覆写）→ 0x65 翻译错误 → panic。与 cpu_map 无关（dom0-only hack 同样崩）。

二分实验（early_param `qemu_park1` 控制 CPU1 上线后停机点）：

| 实验 | CPU1 停机点 | 结果 |
| --- | --- | --- |
| v64 | `platform_secondary_init`（中断未开） | **干净**：完整启动到 UI，CaptureId 模型正常跑，ok=true |
| v66 | `cpu_active` 等待后、开中断前 | Sony `__cpu_up` 握手挂死（等待 CPU1 的 FIQ/定时器应答） |
| v68 | 开中断后、percpu 定时器设置前 | 同样握手挂死 |
| v67 | `calibrate_delay` 后、`cpu_idle` 前 | `Brought up 2 CPUs` + **覆写复现** |

结论：覆写源在 CPU1 执行的 `[platform_secondary_init .. cpu_idle)` 区间，首要嫌疑是**每 CPU 本地定时器路径**（TWD tick / Sony hwtimer / EJ hrtimer）在本构建（gcc 9.3）或 QEMU 模型下的缺陷。

已排除：per-cpu 区域别名（两单元在直接映射 0x60030000/0x60038000，独立）；trace-clock 32-to-64（其定时器 131104 jiffies 才触发，启动期不可能）；EJ 配置（全套关闭无法编译——`outer_clean_all` 依赖被破坏，说明该树绑定 EJ 环境）。

## 对主线的影响

- **单核路径完全无回归**：v69 最终回归 ok、12 帧、host 15 项检查通过；最终帧黑/图标交替是既有非确定性（v48/v51 黑 vs v49/52/53/54 图标），先于 SMP 工作存在。
- 产品默认 `-smp 1` 不变；`--smp 2` 为实验选项。
- 诊断/hack 均由 `early_param`（`qemu_dom0`/`qemu_park1`）门控；canonical `source/kernel/zve10_defconfig` 未动；旧验证内核备份在 `work/Image.backup-smp1`。

## 后续选项

1. 定点修 CPU1 定时器路径：先试 `CONFIG_LOCAL_TIMERS` 关闭或 TWD 在 QEMU a9mpcore 下的 per-CPU bank 行为核对；再查 Sony hwtimer 驱动的每 CPU 基址。
2. 或回归单核主线，转攻 ObjRemote 的 uipc 链（`__osal_snd_sync_msg` 两级查找返回 -1020 的瞬态条件；tid 182 内联回调成功 vs ObjRemote 工作线程失败的差异）。

收据：`evidence/shoot-startup/validation.json` 的 `smp_investigation` 与 15 条实验记录（v56–v69、v55）。
