# 拍摄主页面：原视图启动与绘制后端

日期：2026-11-09。本文件取代旧版对“帧节拍”和“必须先注入视频帧”的推断。目标仍是原 `im.elf` 创建并绘制拍摄 HUD，允许取景区为空；成片、录像和物理 ASIC 兼容性不在本轮通过范围。

范围与授权：[本产品约定](../AGENTS.md)。仅隔离 QEMU，原 ELF/CPIO 只读，`query-block=[]`，正常 QMP quit。默认原菜单与可选 A7C2 菜单保持独立。

## 当前事实

**收尾复验**：v84与全服务v80均显示无镜头警示的原拍摄页；全服务v76独立通过原菜单模式。拍摄页MENU闭环仍未通过，函数6/36、面板键扫描及直接RootSelector打开均未形成正常切页；导致AP异常的实验代码已移除。最终安全DSO与v84 SHA完全相同（`6dba7aa1…e6c2e89c87`），v101/v102的同DSO黑帧按非确定性失败保留。README两张截图不是同次切换证据。

**此前v47/v48**：显式 [CaptureId表模型](capture-table-model.md) 已实际解除四个原内容管理OnStart等待，原0x96创建、镜头警示自然消失，原相机/P、XAVC S HD、曝光图标显示。v48表/提交副本经guest/QMP读回exact，SHA b468e816…cca7。原NetInfo后继也实际继续初始化；需延长观察以定位最终状态，完整HUD/MENU/取景仍false。以下v16–v36为保留的原阶段证据，不能当作模型启用后仍停同处。

- 原来报告为“拍摄视图”的 `0xa0` 实际是 `ViewRoot`。原运行还加载 `0xa3=ViewRootSelector` 和 `0xa1=ViewRootPowerSw`；仅看到这些根视图，不能称拍摄页已打开。
- 原注册表确认 `0xc3=ViewStlrec`，注册指令在 `viewUnified2+0x6dcc24`。`0xbc=ViewShootingInfoDisp` 是另一个原视图，不能混用。
- 显式 `--shoot-view` 在原 UI 线程、第一笔原帧完成后，通过真实 RootSelector 次级接口 thunk `+0x41a7d9` 请求 `0xc3`。该 thunk 调整 `this-0x154`，原 `+0x41a7b8` 根据 `root+0x180` 选择保留 mute 语义的原 `openView` 分支；原代码自己创建、移交和消费 Event。没有直接调用视图工厂、改状态或填 ready。
- `shoot-stlrec-v7` 已实际进入原页绘制，但 CPU DMP 后端拒绝布局 1 的整面清屏；后续 `shoot-entry-v10` 已实际创建原 `ViewStlrec`，又遇到原资源 144×28→448×28 的 GL_LINEAR 拉伸拒绝。创建、Entry、绘制和实际显示必须分开记账。
- **普通完整拍摄 HUD 与导航仍未通过**。原警示/部分HUD的正内容和实际窗口已通过；后续透传观测证实抑制模型 `0x96` 的查询返回0、原map记录不存在，因此“镜头收纳”文字不能当真实镜头状态读回。原双参数 `WrapperSettingUtil::isInhOn` 在查询失败分支 `+0x6e26ac` 返回1。
- 原 `ActionOpenBootRecMode` 默认参数是 `(0xc3,3)`，helper `+0x414350` 先请求 `0xa4=ViewRootUtility`、`0x34=ViewDummyBlack`，再按同一参数组合请求拍摄页。当前显式模式复用这三次原请求，不强制模型状态；v18/v19仍复现同一警示。
- 原 `requestModel()` 已观察到 `ViewRoot(0xa0)→tree0x100`、`ViewStlrec(0xc3)→tree0xe3`，调用时具有原模型控制权。原接收器也消费了请求，manager持续state0x40000/substate0x40301，等待当前叶模型 `0x0a=ModelMedia`（record0x30000、业务state1）；其准备动作60两个子步骤均返回。
- 批事件 `0x1200a041` 包含原资源18/25/196/249。v30/v31读回四组命令：`ObjMedia` 均已回复，`ObjCntMgr` 均pending，原批处理停在step13。v32真实创建类型为普通ObjCntMgr、两个ObjCntMgrForSimulatedRec和一个ObjCntMgrForPcRemote，不能仅凭名称判断初始化实现。
- v29通过原ARM32 syscall263实际记录了82,046ms guest时间，仍未完成上述批请求。不是基于宿主睡眠推断相机时间。
- v33/v34确认四个ObjCntMgr均进入原onStarting但不返回，业务命令循环未见非空命令；v35又证其媒体配置端点0xcf016d查询callback能正常消费、返回，不能继续称该端点阻塞。v36同步采样额度被更早的其它媒体查询用完，未看到后续0x37807c不能当作它未调用的证据。v37后已证相关调用返回，等待最终定位到0x4015e CaptureId表；显式模型实测见上方最新结果，不再重复已排除端点。新代码和后续运行结果见 [shoot-startup](../evidence/shoot-startup/)。

## 已撤回的旧推断

| 旧说法 | 纠正与证据 |
| --- | --- |
| 队列 8388667 的 `w0` 每次约加 32，代表约 31.25 fps | `osal_rcv_msg_tmo(queue, void **out, timeout)` 输出消息指针。旧探针读了指针输出槽和相邻栈字；32 是地址差，不能用于频率计算。原 Dataflow 接收器 `+0x228f6` 把 `&local` 传给 OSAL，`+0x2290c` 解引用，随后调用 `osal_msg_size`。 |
| 成功收消息证明 AP 在等视频帧 | 只能证明部分接收成功。修正后的 `shoot-abi-v6` 收到 20 字节控制包，例如 `020000004100220a...`，没有证明它是视频时钟或成像缓冲。 |
| 相同 `0x10000102` 常量证明与 A7C2 AV-cam 协议兼容 | 常量字节出现不足以建立协议或 ABI。`+0x77c5f0` 被属性读取函数当键使用，尚无帧提交证据。 |
| `SendASync` PLT 是 `0x108378`，无调用者 | PLT 含 Thumb veneer，不能按重定位序号乘固定 12 字节求地址。实际 ARM 入口为 `0x1083a8`，GOT `0x13d7d64`，发现 22 处真实 Thumb BLX 调用。 |
| 直开视图崩溃证明所有原视图请求都不可行 | 旧 `vtable+0x90` 探针的 ABI 和候选 ID 不成立；不是对正确原 `openView` 路径的否定。新请求使用已有原菜单闭环验证过的 selector `+0x18` thunk。 |
| 初始化日志中的成功返回证明全部相机服务就绪 | 需要核对真实返回类型、阶段、异步完成和消费。初始化日志不足以证明相机/成像状态。 |

原失败记录与旧推断的 Git 历史保留，不把旧运行回填成新版本成功。`shoot-stlrec-v7` 的 transport `ok=true` 只表示捕获/收尾完成；其 DMP 拒绝使拍摄显示验收失败。

## 原切页与绘制边界

原链为：UI 线程收到首帧完成 → 校验真实 manager / RootSelector / 原字节 → 原 selector 依次请求 `0xa4`、`0x34`、`(0xc3,3)` → 原 EventManager / ViewManager → 原工厂、Entry、原布局和资源 → CPU 后端实际消费 → 原 present / 完成 → 独立 RAM 读回像素。

`ne_request_shooting_view()` 校验 43 槽 manager、RootSelector 主 vptr、次级接口 vptr、manager 归属、原三参数 thunk 的36字节、原开机参数8字节和三次open的32字节窗口，且只提交一次组合。`--shoot-view` 不启用测试图案。

DMP 整面填充只接受已观测的 640×480 RGBA4444、布局 1、整面无混合操作。原 GRM 命令中的 bitmap 具有真实 native vptr，地址 token 必须与 bitmap 的 CPU 指针一致；实际写入经 bitmap 原 metadata 的物理地址映射并检查尺寸/格式/布局及前后身份。不能把 `0x32...` token 直接当物理地址。

原 filter 映射 `libObj+0x84be14` / 表 `+0x10265a8` 为 0→GL_NEAREST、1→GL_LINEAR。新增双线性采样保留原分块寻址、alpha、混合和读锁生命周期，使用原分配的纹理 padding；不支持的过滤/边界模式继续拒绝。实际原 AP 消费结果单独记录，host 插值检查不能代替显示验收。

## 测试图案与取景源

此前的彩条实际写在**显示输出副本**上，并不是 DMM/VDT 成像输入。现在需显式 `--test-pattern` 才启用；仅填 alpha=0 的像素，不保留会覆盖后来 OSD 的旧归属表。标记随原 present 次数变化，没有独立帧定时器，不称活动取景或已实现帧源。

A7C2 `yc_inject` 仍仅是另一型号的研究参考，其缓冲/端点不能从数值相似直接移植。是否需要成像帧才能完成某个原状态，须用该状态的真实消费证据判断。

## 复现与判据

在产品根目录运行：

```sh
python3 evidence/shoot-startup/inspect_shoot_startup.py
python3 -m pytest tests/test-shoot-probe.py -q
./start-zve10-menu.sh --start-page shoot --headless --out output/shoot-observe-new
./start-zve10-menu.sh --start-page shoot --shoot-view --headless --out output/shoot-stlrec-new
./start-zve10-menu.sh --start-page shoot --shoot-view --capture-table-model --headless --out output/shoot-table-new
```

输出目录必须不存在。最后两条分别为不干预视图选择的原启动观测和显式原拍摄视图请求，不代表 HUD 已通过。原拍摄页探针先按guest单调时间留20秒窗口，显式表模式留60秒，再采样；host等待有上界，实际经过时间记录在probe.guest_timing。所有运行保留 `result.json`、原串口、源码/DSO摘要、RAM读回和正常退出信息。任何 `DMP.*.UNSUPPORTED` / `GEMINI.cpu.UNSUPPORTED` 都使 host 验证失败，不能用缓存旧帧掩盖。

v28时钟探针误引入GLIBC_2.17，原loader拒绝、没有AP ready/帧，保留原失败。已改原ARM32 time32 syscall263，并在构建中从固定原CPIO读取每个SONAME的版本定义，候选需求必须逐项被原库提供，缺版本在Popen前拒绝。默认原菜单和A7C2可选模式的新构建均仅需GLIBC_2.4；本轮未重跑未变菜单guest。

通过需同时有原 `ViewStlrec` 的实际消费、可辨识的原 HUD/文案正内容、未经测试图案覆盖的像素读回和正常退出；单独 `glyph_images>0`、非均匀颜色或 transport `ok` 都不足够。`shooting_page_verified` 与 `capture_verified` 在相应链通过前保持 false。
