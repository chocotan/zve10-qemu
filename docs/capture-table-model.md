# ZV-E10 CaptureId 表依赖与显式功能模型

2026-11-09。`shoot-capture-table-readback-v48` 已验证：四个原内容管理 `OnStart` 正常返回；原抑制模型 `0x96` 创建，原镜头收纳警示消失；原画面显示相机/P图标、`XAVC S HD`、曝光图标。完整 HUD、MENU 进退、取景与成片仍未验收通过。

## 原失败与原因

原 `IsCaptureIdTable()` 读 Backup `0x3c038a` 返回1，`GetCaptureIdTableMaxCount()` 读 `0x3c04c2` 返回1024。不能关闭这项已启用功能来跳过启动。

四个 `ObjCntMgr` 的 `OnStart` 都向 `0x4015e` 发24字节请求 `{0,0x1000,0,0,0,0}`，并等待各自原动态回复队列。原 `osal_msg_size` 返回52，24是正文复制长度，不能把它当分配尺寸。v43仅抓到无限期等待；v44修正发送采样界限后四笔实际请求均读回。

原调用者检查回复 word0=1、word1=原操作码，读取 `+0xc` 物理地址，通过 `/dev/mem` 映射 `0x4014` 字节。原表由20字节头与1024个16字节行组成。`0x1001/0x1002` 位于成对访问路径，调用者检查 `+8` 状态。原 CP 服务本体未恢复，不声称这些操作的物理 CP 语义已验证。

媒体配置 `0xcf016d` callback、媒体管理任务提交和 `0x37807c` 同步调用已实际返回，均不是此阶段的等待端点。`CapIdSync_Init` 是三参数入口，未冒充零参数通用 initializer 调用。

## 显式模型

```sh
./start-zve10-menu.sh --start-page shoot --shoot-view --capture-table-model --headless --out output/your-new-run
```

默认不启用。仅本机隔离 QEMU，原镜像只读，`query-block=[]`。与 `--test-pattern` 无依赖。

- 启动命令额外声明 `memrsv=128K@0x1ff00000`。原内核 `arch/arm/mm/init.c:parse_memrsv` 通过 `memblock_reserve`/`reserve_bootmem_node` 移除可分配RAM；v45–v48实际日志均有 `reserve area 2: 20000 @ 1FF00000`。服务核对guest启动声明才映射，未声明则拒绝写内存。
- `0x1000` 返回一张独立保留RAM中的真实共享表：容量1024，初态头 `{1024,1023,1023,1023,0}`，行区为空。只有首个请求初始化，其后保留原客户端修改。
- 本机模型将 `0x1001/0x1002` 定义为访问事务：绑定实际调用线程owner；拒绝重入/跨owner结束；结束时把实际表复制到同保留区 `+0x8000` 并读回校验，之后释放owner。它不是持久Backup或写卡服务。
- 仅支持观察到的六word全零参数请求和三种操作码；未知操作、非法长度、映射或读回失败使运行失败。没有改原 getter、模型ready、原表指针读取者或原消息释放者。
- 原OSAL接收者实际消费回复、映射表并释放消息。发送失败由模型回收原请求；成功交还原接收者所有权。

实现：[`capture_table_model.h`](../source/menu/capture_table_model.h)、[`original.inc`](../source/menu/original.inc)、[`menu_run.py`](../scripts/menu_run.py)。构建的glibc版本provider检查仍生效，模型只需原CPIO提供的版本。

## 原消费与内容型验收

v45首次真实 `0x1000` 回复被原客户端消费，随后未支持的 `0x1001` 被拒绝；v46继续到未支持的 `0x1002` 后拒绝。两轮原失败均保留，QMP正常quit/rc0/无VM信号。v46曾将1001暂称清表，已被后续成对访问上下文更正；历史源码/收据不回填。

v47、v48四个原 `OnStart` 全部进入并返回0，均实际走 `0x1000→0x1001→0x1002`。原ModelMedia批完成，原0x96创建；没有注入镜头通知，警示通过原模型初始化自然消失。v47在观察末段仍处ModelNetInfo，v48该模型继续完成到后继模型，不能将较早截断点提升为固定阻塞。

v48由受管 `CAPTABLE` 读取原进程所见共享表及checkpoint摘要，随后QMP暂停并分别物理读回两份RAM，核实长度、地址、头与FNV摘要：

| 项 | 实测 |
| --- | --- |
| 表头 | `[1024,1023,1023,1023,0]` |
| FNV1a64（live/checkpoint） | `80d7b66e3b7f9e8f` |
| SHA256（live/checkpoint） | `b468e8163614e6862c43231649e3f2cf62808f92c5fa45e4617f92a1b810cca7` |
| guest/QMP内容 | exact |
| 表/提交副本 | exact |
| QMP/进程收尾 | quit、rc0、无VM信号、owner消失 |
| 物理CP兼容性 / 持久存储 / 成片 | 未验证 / 无 / false |

本轮集中host检查35通过、1项因未设置固定资源ZIP环境变量跳过、11子检查通过。新表核心由ASan/UBSan覆盖长度/容量、越界、未知命令、owner、真实数据修改保留及提交读回；host读回检查非法物理地址拒绝和读取失败后恢复QEMU运行。原始证据收据见 [`shoot-startup/validation.json`](../evidence/shoot-startup/validation.json) 与对应私有output目录。

## 后继与下一步

v49按原guest时钟留60,150ms初始窗口，总观测122,972ms。表与checkpoint再次双通道exact、SHA不变；原ModelNetInfo已完成，末段在 `ModelRemoteAsync(0x126)` 的record0x30000/business state1反复消费事件。固件具有两个独立工厂：`ObjRemote_Create=0x38fcd9` 与 `ObjRemoteAsync_Create=0x3449a9`。名字表ID56=ObjRemote，不能从ModelRemoteAsync的名称把它套成Async对象。Async vtable0x13a7530、OnStart0x344d31、command0x345421；v50新增这两个槽的透传观察无OnStart进入，只是该Async类的否定证据，不表示普通ObjRemote未启动。此前将两者相等的推测已撤回。主已核原state1动作2在0x6bde44请求拓扑项0xe2（原0xfdfd04={226,0}，0xf2c678记录+8=68=ObjRemoteAsync），完成ID为0x12126011；v50全局拓扑仍占在前一项ModelRemote0xf5的0x120f502c，资源265/264/262中最后未回复为普通ObjRemote/ID56，尚未见资源226进入。Async模型可能等的是排队，不能直接说Async服务内部失败。主核原窗口摘要见 [remote-topology-static.json](../evidence/shoot-startup/remote-topology-static.json)。下一观察普通Remote原OnStart/ObjSignal与两笔拓扑排队，不重复已解除的表等待。[v49原画面](../evidence/shoot-startup/shoot-capture-table-late-v49-original.png)。

完整HUD及MENU进退按原事件/状态/像素验收。当前表模型只有挥发性RAM事务，不代表固件完整CP、取景、拍照录像或持久存储已实现。
