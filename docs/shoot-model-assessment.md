# 拍摄主页面：实现评估（只读，未实现）

日期 2026-11-09。面向"要不要立项"的决策材料；不含代码改动。

## 1. 目标与现状

目标：ZV-E10 原 `im.elf` 显示拍摄主页面（取景区可黑，但 OSD/控件可见），之后才能验证按键与导航。

现状（全部有证据，见 `shoot-main-plan.md`、`menu-validation.json`）：

| 事实 | 证据 |
| --- | --- |
| 两种模式的绘制宿主都是 `im.elf`（bootin 只负责拉起） | `reg-original3` 的 `/proc/103/cmdline` |
| 拍摄视图 `0xa0` 存在且 state=1，但 `glyph_images=0` | `shoot-observe-v1`：6 帧、`color_samples=[1]` |
| 补模块（input/indctr/keyinject/udate/mcmn_drv/codec_drv）无效 | `shoot-mods-v3`：glyph 仍 0 |
| 合成功能事件 / 真实表 id / trigger 变换 / 尾段注入均不通 | 见 `menu-validation.json` 的 `ruled_out` |
| 直接按 id 开视图会崩 im.elf | `--open-probe`：section permission fault @ `0x80bff6f6` |
| 菜单能显示，是因为我们主动 `openView(0x11)` 触发字体/资源加载 | `0x590f35(1)` + `0x47de26(sel,0)` |

**结论**：`im.elf` 停在"资源/字体初始化之前"，它需要按原逻辑被推进到拍摄视图。

## 2. 两条可能路线

### 路线 A：启动推进（先例 = A7M4）

A7M4 用原 Backup API 预置首设完成（`02cf0014=0`、`01070140=0`、`02cf1701=1`）+ `udate` 日期，让 AP 自然走 `315→355→351→0` 进拍摄 UI。

ZV-E10 现状：
- `0x02cf0014` / `0x02cf1701` 在该固件**不存在**（0 处）；`01070140` 存在 6 处但都在日期/时区函数里。
- 已读出 ZV-E10 自己的 Backup 用法：`0xa10019`（三态 0/1/2）、`0x1700000`（`SystemImpl::initialize_setting`）、`0x1820000`，以及 `0x72b770` 一带的 `0x0107xxxx` 编号表（与 A7M4 同族但编号不同）。

未知：哪几个编号对应"首设完成 / 教学已显示"，且我们**没有** ZV-E10 的 skip-setup 先例可对照。

工作量估计：中（1 个里程碑）。判定方式明确：原屏序列变化 + `glyph_images>0`。

### 路线 B：功能相机模型（AGENTS 的 `virtual-functional-camera-v1`）

按 A7C2 先例，需要：`functional-camera-abi.h`、`-bridge`、`-events`、`capture`、`jpeg/mpr` 编码与内存模型，加虚拟 CMOS 帧源；ZV-E10 是 ARM32 + 不同 CP/UIPC 端点，需重新对齐。

工作量估计：大（多里程碑），且要满足 AGENTS 的成片判据（原 AP 触发 → 虚拟帧 → 编码 → 写虚拟 SD → 读回解码）。

## 2b. 新证据：im.elf 的初始化清单（`shoot-observe-v1`）

`UI_INIT_ENTER` 实际执行的初始化（节选，全部 `result=0`）：

```
Selector_init, uxengine_init, udate_init, mcmn_init, MWF_Init, mpr*,
ObjMedia_Init(×2), ObjCntMgr_Init, odl_init, infra_tp_init,
rsrc_hotshoe_init, udtr_senser_init, udtr_ufp_init, jiritsu_init,
ResourceBluetooth_init, netservice_init, NetConnectionManagerEther_init,
wlanResource_init, WlanAdjust_Init, KikiLogGenerator_init
```

即：UI 引擎、媒体对象、日期、传感器探测、触摸等**都已初始化成功**，没有任何相机/成像模型初始化（也没有 CP 相关）。

这条削弱了"路线 A（首设种子）能救 OSD"的假设：AP 已经跑过首设相关初始化并打开了 UI 引擎，却仍不画拍摄 OSD。更可能的是拍摄 OSD 需要相机状态（路线 B）。

## 2c. 决定性证据：im.elf 并没有卡住，它是在等视频帧

新增 `osal_rcv_msg_tmo` 观测（`shoot-rcv-v1`，104 次接收）：

| 次数 | 队列 | 来源模块 |
| --- | --- | --- |
| 50 | 9371961 | `libosal_ulogio.so`（日志） |
| **14** | 8388667 | **`dataflowInfraFramework.so`**（数据流/成像框架） |
| 6 / 6 / 6 / 4 / 4 / 2 / 2 / 1 | — | `libObj.so`、`libRsrcHotshoe.so`、`libgps_rsrc.so`、`libJiritsu.so` |

`rc` 分布：93 次 `0`（收到消息）、11 次 `-1022`（空/超时）。

**结论修正**：im.elf 不是"卡死"，它一直在收发消息、空闲循环；它只是**没有拿到视频帧**。ZV-E10 的拍摄 OSD 是与取景画面一起合成的——没有帧就没有任何可见内容（连 OSD 也不单独画）。这解释了"纯色 + `glyph_images=0`"，也解释了为什么 A7M4 能显示 OSD 而 ZV-E10 不能（A7M4 的显示模型会在无帧时单独合成 OSD）。

因此：**必须提供取景帧源**（Route B），没有别的捷径。

## 2d. 虚拟帧已实现（拍摄模式，默认关闭）

实现：在**原提交目标（线性 RGBA4444）**上做"底衬合成"——只填充原 AP 仍为底色的像素，并用像素归属表保证下一帧能继续刷新，因此原 AP 若绘制 OSD 不会被覆盖。

- 代码：`source/menu/original.inc` 的 `ne_shoot_frame()`，仅在 `NE_SHOOT_PROBE`（`--start-page shoot`）编译；
- 调用点：`native_entry_present()`，长度 640×480×2 时；
- 实测 `output/shoot-frame-v4`：`ok=true`、`qemu_rc=0`、`color_samples=[8]`，截图 `evidence/virtual-frame-test-pattern.png` 为 8 条彩条；
- 早期在清屏目标写入会出现斜向撕裂（Morton 分块），因此改在提交目标上写。

**同轮结论**：虚拟帧可见，但 `GEMINI.cpu.glyph_draw=0 / glyph_images=0`，原 AP **仍未绘制 OSD**；且帧序列摘要只有两个值——AP 只在内容变化时才 present，所以虚拟帧静止（移动标记不会前进）。这说明虚拟帧只解决"取景区有画面"，不解决 OSD/主页面。

## 2e. 数据流消息内容（`output/shoot-rcv-v2`）

拦截 `osal_rcv_msg_tmo` 并读出消息前 4 个字后，`dataflowInfraFramework`（队列 8388667）的 14 条消息为：

| 字段 | 观测 |
| --- | --- |
| `w0` | 74865228 → 74866188，**步长主要为 32**（约 31.25 fps 的帧节拍） |
| `w1` | 0 或 243596060 |
| `w2` / `w3` | 恒定 182856064 / 182856072（指针样值） |

结论：**AP 一直在按帧率收到数据流节拍**，但没有携带像素缓冲。因此"取景区没内容 / OSD 不画"不是"没收到节拍"，而是**缺少真正的图像缓冲**（这与 A7C2 走 `yc_inject` 往 AV-cam 送 5 MiB 缓冲的做法吻合）。

要往下走，需要实现同一条数据流通道的**缓冲提交**（对齐 ZV-E10 的 DMM/VDT 协议），属于 Route B 的核心工作量。

## 3. 建议顺序

1. （建议降级）先做路线 A 的定点调查：从 `Backup_write`(162 处) 中筛出与"开机完成/教学"相关的写入函数，确定 ZV-E10 的首设编号；再在 guest 内经原 API 种子 + 读回。
2. 若路线 A 能让 `glyph_images>0` 且出现 OSD，则拍摄页与按键导航都在同一条链上，成本可控。
3. 只有当 A 走不通时，才进入路线 B（功能相机模型）。

## 4. 风险与边界

- 任何种子只写本次虚拟机的独立副本/内存（`Backup_save=0`），不改原 `Backup.bin`、不接真机。
- 取景区仍为黑：本评估不承诺 CMOS/镜头/AF/成片；`capture_verified` 保持 false。
- 直开视图已证明会崩，不做为捷径。
