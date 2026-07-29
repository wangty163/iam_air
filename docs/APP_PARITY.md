# 心够智家设备页对账基线

本文件记录 IAM Android App 3.4.3 的 XDJ/KX 设备详情页与 Home Assistant
实体之间的完整映射，避免后续按单个现象反复修补。证据来自 App 的
`view_xdj_property`、`activity_xdj_tuoguan_config` 布局及对应控制字节码，
并用 KX type 5 的脱敏 TSL 能力集交叉验证。

## 设备详情页

| App 显示/操作 | 设备数据或命令 | Home Assistant 映射 | 对账规则 |
|---|---|---|---|
| 设备标题 | App 设备详情名称 | 设备名、主 `fan` | 用户备注优先，否则使用产品类型名 |
| 开机/关机 | `PowerSwitch` | `电源` switch、主 `fan` | App 文字表示下一操作；HA 状态表示当前电源 |
| 定时开机/关机 | `TimingOn`、`TimingOff`、`TimingRemain` | `定时开机`、`定时关机` number，`定时剩余时间` sensor | App 根据当前电源只展示对应方向；值域 0–12 小时 |
| 童锁 | `ChildLockSwitch` | `童锁` switch | 智能托管开启或设备关机时拒绝直接操作 |
| 异味指数(VOC) | `TVOCLevel` | `异味指数(VOC)` sensor | 显示 `优/良/中/差` |
| 甲醛 | `HCHO`、`HCHOLevel` | `甲醛`、`甲醛等级` sensor | 浓度单位 `mg/m³` |
| PM2.5 | `PM25`、`PM25Level` | `PM2.5`、`PM2.5 等级` sensor | 浓度单位 `μg/m³` |
| 室内温度 | `CurrentTemperature` | `室内温度` sensor | 单位 `°C` |
| 室内湿度 | `CurrentHumidity` | `室内湿度` sensor | 单位 `%` |
| 智能 | `WorkMode=0` | `模式=自动` | App 将自动模式与风速条分开 |
| 风速 | `WindSpeed=1..5` | 主 `fan` 五档、`风速` select | `WindSpeed=0` 不计入五档；它是自动状态 |
| 睡眠 | `WorkMode=2` | `模式=睡眠` | 再次退出睡眠对应手动模式 |
| 负离子 | `IonsSwitch` | `负离子` switch | 智能托管开启或设备关机时拒绝直接操作 |
| 消毒 | `DisinfectSwitch` | `消毒` switch | 智能托管开启或设备关机时拒绝直接操作 |
| 亮屏/息屏 | `T_Panel_Status`（物理反馈），`ScreenSwitch`（切换命令） | `屏幕显示` switch | App 文字表示下一操作；REST 中命令值可能陈旧 |
| HEPA | `FilterRunTime_1`、`FilterStatus_1` | `HEPA滤芯寿命`、累计时间、状态、重置按钮 | 百分比按 App 机型最大时长计算 |
| 炭魔方 | `FilterRunTime_2`、`FilterStatus_2` | `炭魔方滤芯寿命`、累计时间、状态、重置按钮 | 百分比按 App 机型最大时长计算 |
| 智能托管 | `Trusteeship` | `智能托管` switch | 童锁开启时拒绝切换；设备关机时不能开启 |
| 使用统计入口 | App WebView | `累计运行时间` sensor | HA 提供设备累计时长，不复制 App 图表页面 |

## 智能托管设置页

| App 分组 | Home Assistant 实体 | App 值域 |
|---|---|---|
| 自动运行 甲醛 | `自动运行 甲醛` number | `0`（不设置）或 `0.01–0.10 mg/m³` |
| 自动运行 PM2.5 | `自动运行 PM2.5` number | `0`（不设置）或 `5–110 μg/m³`，步长 5 |
| 自动运行 VOC | `自动运行 VOC` select | 不设置、良、中、差 |
| 自动运行 负离子 | `自动运行 负离子` switch | 关闭/开启 |
| 自动运行 消毒 | `自动运行 消毒` switch | 关闭/开启 |
| 自动待机 甲醛 | `自动待机 甲醛` number | `0`（不设置）或 `0.01–0.10 mg/m³` |
| 自动待机 PM2.5 | `自动待机 PM2.5` number | `0`（不设置）或 `5–110 μg/m³`，步长 5 |
| 自动待机 VOC | `自动待机 VOC` select | 不设置、优、良、中 |

## 不属于设备实体的 App 页面

以下入口也出现在 App，但不是设备 TSL 状态或控制，不创建 HA 实体：

- “购买”跳转到耗材商城；
- “查看使用统计”打开 App WebView 图表；
- 托管周期、进入/退出托管时间由 App 的账号侧场景服务保存。

HA 可用自己的自动化实现时间段和周期调度。集成保留简单稳定的
AppKey/AppSecret 设备属性通道，不依赖商城、WebView 或账号侧场景接口。

## 刷新机制

非 FOG 设备的净化器详情页在属性 Provider 创建时调用一次
`thingPropertiesGet`，随后监听 `/thing/properties` MQTT 通知，并按每个
属性携带的时间戳合并新值。FOG 设备则调用 `findJwtToken` 获取账号 MQTT
身份，订阅服务端返回的通配主题并接收完整属性快照。App 回到前台时会恢复
MQTT 连接，并通过页面生命周期刷新账号侧页面数据。

Home Assistant 保持 AppKey/AppSecret-only 的实现，不打包或运行 Android
私有 SDK。非 FOG 设备通过 `/app/aepauth/handle` 和 IoT Token 绑定监听
`/thing/properties`；FOG 设备通过 `devOperate/findJwtToken` 获取账号 MQTT
身份并监听完整快照。两种 MQTT 都会自动重连。FOG 服务端拒绝派生客户端
ID，HA 与 App 只能有一个长连接，因此 HA 常驻会占用 App 的 MQTT 会话；
5 秒 FOG REST 读取负责连接被 App 抢占时的兜底同步。非 FOG REST 兜底为
30 秒。HA 自己发出的控制仍会立即显示目标状态并立刻请求一次云端回读。
