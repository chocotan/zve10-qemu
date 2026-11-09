# ZV-E10 原拍摄主页面实施顺序

日期：2026-11-09。权威现状见 [模型与 ABI 分析](shoot-model-assessment.md)；历史失败和被撤回推断保留在 Git 与原运行目录中。

已完成菜单入口不作为本任务的替代交付。本轮目标是原 `im.elf` 实际创建拍摄视图并绘制原资源 HUD；取景/成片分别记账，不能用显示输出彩条代替。

## 已闭合的第一段

1. 核原 ELF：三库摘要固定；原 CPIO 和 observer 源码摘要保持；派生源码/DSO 另存运行目录。
2. 纠正 ABI：OSAL 接收输出 `void **`，正文用 `osal_msg_size` 限界；原 PLT 需解实际跳转，`SendASync=0x1083a8`。
3. 核原视图身份：`0xa0=ViewRoot`，`0xa3=ViewRootSelector`，`0xa1=ViewRootPowerSw`；`0xc3=ViewStlrec` 为原静态拍摄页。
4. 在真实 UI 线程首帧后，通过原 selector 的 `+0x18` thunk 请求 `0xc3`；原 ViewManager 消费并创建，不重放工厂、不清 ready。
5. 扩 CPU 渲染所需的受限整面清屏和 GL_LINEAR 采样。后者已被原 AP 实际消费，原资源由 144×28 拉伸到 448×28；保留原 finish/read-lock/unlock 与几何/混合/边界检查。
6. `shoot-linear-v11` 实际读回 `XAVC S HD`、曝光图标、日文“镜头处于收纳状态、无法拍摄、请伸出镜头”警示，未经诊断彩条覆盖。`shoot-menu-v12` 重现相同原像素；MENU 表事件到达原 Stlrec（函数36），未产生导航变化。

这证明拍摄页已出现原内容；**完整拍摄主界面、正常镜头状态和导航尚未通过**。旧“无视频帧不能画任何OSD”说法撤回。

## 当前推进点

- 实际窗口：复用现有 Tk/Pillow 显示 guest RAM 读回，正内容与窗口 RGB 必须 exact，正常关闭并 QMP quit。
- 原模型生命周期：v16/v17原0x96缺失导致getter fail-closed，警示不能证明镜头状态。v47/v48显式表模型解除ModelMedia等待后，原0x96实际创建、警示自然消失，原相机/P图标显示；未改getter或注入镜头通知。原ModelNetInfo在不同运行截断点进度不同，v48已继续完成，需延长自然启动观察，不能当作固定阻塞。
- 内容管理初始化：原四个OnStart均等0x4015e表服务。v44实际24字节请求/52字节分配、原/dev/mem映射合同已核；新增显式 `--capture-table-model` 提供独立保留RAM真表与owner事务。v47/v48四个原OnStart均正常返回；v48guest/QMP表及checkpoint摘要exact，SHA b468e816…cca7。仅本机功能模型、挥发RAM，不提升为完整CP/Backup/成片。详情见 [表合同](capture-table-model.md)。
- 观测边界：v29真实guest经过82,046ms仍同一媒体批；线程名/wchan实际121条，stack/syscall文件errno2，没有完整回溯。v28原loader因GLIBC_2.17拒绝未到AP，保留失败；改ARM syscall263并从原CPIO库版本定义逐项校验候选，两个菜单模式的新构建版本守卫均过。
- 镜头模型后继：原状态参数 `0xc210`；原 CameraManager 转换中 `0x2eda/0x2edb/0x2edc` 分别对应不适用/收纳/伸出，并联动禁止拍摄因子 `0x18ee` 和其它通知。原type6/code2069仅静态锚点，在原模型正常加载前不注入；只改一个返回值、清警示或空 ACK 不构成模型。
- 原导航：MENU `0x150100f0` 已实际分派成 Stlrec 函数36，但画面和视图未变；需核原当前状态/抑制/动作处理的前置条件。不得将发送返回或函数计数记为导航通过。
- 取景源：显示输出彩条已经作为 `--test-pattern` 隔离。后续要恢复实际成像输入，仍须核 ZV-E10 自己的 DMM/数据流缓冲格式、所有权与完成链；相同常量不能代替 ABI 证据。

## 2026-11-09 收尾复验

- `shoot-menu-final-v84`：原拍摄页显示通过，raw SHA `4e3c5856a3…`；通用MENU事件入队但未切页。
- `full-ondemand-v80`：恢复原服务后也实际显示拍摄页，正常QMP退出。
- `full-menu-v76`：`--full-services` 原菜单17帧及方向往返通过；这是独立菜单模式证据，不冒充拍摄页MENU闭环。
- v85/v87的函数6/36只改变状态或稍后出拍摄页像素，没有打开菜单；v88面板键扫描和v93–v100直接打开实验均未通过。导致原AP异常的菜单thunk实验已撤下，失败收据原样保留。
- 最终安全源码的guest DSO SHA `6dba7aa1d94e234ce9e428186678bc546a4119862a76026763a047e6c2e89c87`，与v84完全相同。v101/v102同一DSO出现黑帧，证明启动仍有非确定性；旧成功不回填到新轮次。
- README已加入拍摄页和菜单原LCD截图；`shooting_page_display_verified` 与 `shooting_to_menu_verified` 分字段记录，后者保持false。

## 验收

| 能力 | 判据 | 当前 |
| --- | --- | --- |
| 原拍摄视图注册/创建 | 原 factory 注册、原请求消费、真实对象/状态 | 已有原运行证据 |
| 原拍摄页绘制 | 原资源、字形、RAM读回正内容 | 已有原相机/P、XAVC S HD、曝光图标；旧警示页证据保留 |
| 内容管理启动/表数据 | 四原OnStart返回、原客户端真实映射及数据读回 | 显式表模型v47/v48通过，物理CP/持久化未验证 |
| 实际窗口 | guest RGB 与窗口 RGB 完全一致 | 见最新运行收据 |
| 普通完整HUD/镜头状态 | 原状态更新与原业务/像素一致 | 未通过 |
| MENU进退/方向 | 实际原事件消费、正常切页、焦点/像素恢复 | 未通过 |
| 实时取景/拍照录像 | 原成像链、编码、存储与独立解码 | 未实现，`capture_verified=false` |

本轮默认原菜单与可选 A7C2 菜单在独立 QEMU 回归；同时最多两个验收工作线程。旧一键包保持其原版本摘要，本轮新源码不冒称已在该包中。
