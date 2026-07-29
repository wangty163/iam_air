# IAM Air

`iam_air` 是一个面向 Home Assistant 的非官方自定义集成，用于接入通过
“心够智家”App 管理的 IAM 空气净化器。第一阶段目标设备为 IAM M8。

> 当前状态：Alpha。IAM、Link Living 登录、App 可见设备发现，以及 Y/KX
> 设备的主要查看与控制能力已验证。

## 功能

- 通过 IAM 账号登录并换取阿里云生活物联网会话。
- 从 HA 主机的私有文件直接读取 Link Living AppKey/AppSecret。
- 先读取心够智家首页设备列表，再按 `iotId` 关联 Link Living 绑定设备；
  不按产品系列硬编码或暴露历史绑定；集成重载时会清理不再出现在 App
  首页中的旧 HA 设备。
- 从 App 设备详情接口补全设备备注名、默认产品名和产品类型名；有用户备注
  时显示备注，否则显示更准确的产品类型名。
- 根据设备自己的 TSL 创建实体，不在代码中硬编码设备 ID 或账号数据。
- `fan`：电源、App 风速条对应的 5 档手动风速、自动/手动/睡眠工作模式。
- `switch`：电源、童锁、屏幕显示、负离子、消毒、智能托管，
  以及“自动运行”中的负离子/消毒开关。
- `select`：带 App 原始中文档位的风速、模式，以及“自动运行/自动待机”的 VOC
  开启/关闭阈值。
- `number`：定时开机、定时关机，以及“自动运行/自动待机”的 PM2.5、甲醛阈值。
- `sensor`：PM2.5、甲醛、异味指数(VOC)、室内温湿度、滤芯状态与累计时长、
  App 命名的 HEPA/炭魔方滤芯寿命百分比、设备累计运行时长、定时剩余时间。
- `button`：重置 HEPA/炭魔方滤芯寿命。该动作会修改设备的维护数据，只应在更换
  对应滤芯后按下。
- IoT Token 到期前自动刷新；同账号在 App 重新登录导致旧会话失效时，自动
  串行刷新并重试原请求。
- 复用 AppKey/AppSecret 注册 Link Living 移动端 MQTT 通道，并用当前 IoT Token
  绑定账号；非 FOG 设备的属性会立即推送到 HA，30 秒 REST 轮询仅作为兜底。
- FOG 设备复用 IAM 账号接口签发的 MQTT 身份接收完整属性快照，断线后自动
  重连，并保留 5 秒属性读取兜底。该通道与 App 使用同一个服务端限定的客户端
  ID，HA 常驻时会占用 App 的 MQTT 会话。
- M8 Pro 屏幕控制按 App 的“当前值触发切换”语义发送，并在属性中提供
  `app_action=亮屏/息屏`；该文字表示 App 按钮的下一操作，HA 开关状态仍表示
  实际屏幕是否点亮。非托管模式下实际状态是最后一次 `ScreenSwitch` 切换命令
  的反值，托管模式下才使用 `T_Panel_Status`。
- 智能托管开启时，电源、档位、模式、童锁、负离子、消毒和定时控制会像 App
  一样拒绝直接操作；需要先关闭智能托管。

## 安全与隐私

这是公开仓库，**不包含也不接受任何真实密钥或个人数据**：

- 不内置心够智家或第三方 App 的 AppKey、AppSecret。
- 不提交账号、密码、手机号、IoT Token、设备 ID、抓包、APK 或 HA
  `.storage` 数据。
- AppKey/AppSecret 只放在用户自己的
  `/config/iam_air/credentials.json`，文件必须为 `600` 权限；读取后只保留
  在进程内存中，不写入配置条目、日志或诊断信息。
- 账号密码使用 HA 密码输入框采集，只保存在用户自己的 Home Assistant
  配置存储中。
- 日志和异常不会输出请求体、密码、Token 或签名密钥。
- 移动端 MQTT 临时三元组和 IoT Token 只保留在进程内存中，不写入仓库、配置条目
  或日志。
- CI 会执行仓库敏感信息扫描。

不要上传、提交或公开分发客户端凭证。提交 Issue 时也不要粘贴账号、Token、
完整设备返回或未脱敏日志。

## 安装

### HACS 自定义仓库

1. 在 HACS 的“集成”页面打开“自定义仓库”。
2. 添加 `https://github.com/wangty163/iam_air`，类型选择“集成”。
3. 安装 IAM Air 并重启 Home Assistant。

### 手动安装

将 `custom_components/iam_air` 复制到 Home Assistant 的
`config/custom_components/iam_air`，然后重启 Home Assistant。

## 配置

先在 HA 配置目录创建固定凭据文件：

```json
{
  "app_key": "YOUR_IAM_LINK_LIVING_APP_KEY",
  "app_secret": "YOUR_IAM_LINK_LIVING_APP_SECRET"
}
```

保存为 `/config/iam_air/credentials.json`，并将文件权限设为仅属主可读写：

```bash
chmod 600 /config/iam_air/credentials.json
```

凭据必须属于 IAM App 使用的 Link Living 项目；其他阿里云项目新建的凭据无法
访问已绑定设备。公开仓库不会提供或下载真实凭据。

然后进入“设置 → 设备与服务 → 添加集成”，搜索 `IAM Air`，只需输入：

- 心够智家账号手机号；
- 心够智家账号密码。

推荐在心够智家中创建 HA 专用账号，并把 M8 分享给该账号。这样可以降低主账号
登录会话相互影响的风险。

## 工作原理

1. 调用 IAM 官方账号服务登录，获得用户身份。
2. 从固定的本地私有文件读取 Link Living AppKey/AppSecret。
3. 使用 IAM 身份完成 Link Living 自有账号授权。
4. 从 IAM `index/homepage` 获取 App 当前展示的设备 ID。
5. 对 App 可见设备调用 `devCustInfo/devInfo` 补全名称和产品类型属性。
6. 调用 `product/listInfo` 获取对应机型的滤芯最大寿命，用 App 相同公式将
   累计使用时长换算为剩余百分比；双滤芯页面按 App 固定标题显示为
   `HEPA` 和 `炭魔方`。
7. 创建 IoT 会话，从 `/uc/listBindingByAccount` 获取可控绑定，并按设备 ID
   与 App 首页列表取交集。
8. 使用 `/thing/tsl/get` 读取设备物模型。
9. 按 App 首页返回的 `iotPaasType` 自动分流：飞燕设备走 Link Living
   `/thing/properties/get` 与 `/thing/properties/set`；FOG 设备走 IAM
   `devOperate/findDevAllProperties` 与 `devOperate/operCmd`。
10. 用 AppKey/AppSecret 调 `/app/aepauth/handle` 获取临时移动端 MQTT 身份，
    通过当前 IoT Token 绑定账号并监听 `/thing/properties`；按属性时间戳合并推送，
    供非 FOG 设备实时更新。
11. FOG 设备调用 `devOperate/findJwtToken` 获取与 App 相同的账号 MQTT 身份，
    监听完整属性快照；同时以 5 秒 REST 读取处理 App 抢占连接或网络中断。

协议边界和已确认字段见 [docs/PROTOCOL.md](docs/PROTOCOL.md)。
App 设备详情页的逐项对账见
[docs/APP_PARITY.md](docs/APP_PARITY.md)。

## 开发

需要 Python 3.14.2+ 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync --group dev
uv run ruff check .
uv run pytest
uv run python scripts/check_no_secrets.py
```

## 局限

- 当前实现云端 MQTT 推送和 REST 兜底，尚未实现 ALCS/CoAP 局域网控制。
- FOG 设备的 REST 兜底间隔为 5 秒，非 FOG 设备为 30 秒。单设备对 NAS 的
  开销很小；继续缩短主要会增加云端限流和会话抖动风险。
- FOG MQTT 凭据把客户端 ID 固定在账号令牌中，不能派生第二个可用 ID。
  HA 常驻连接会挤掉 App 的 MQTT 实时会话；App 仍可通过业务接口发出操作，
  HA 最迟由 5 秒轮询同步。
- Link Living 对同一 IAM 身份只保留一个有效 IoT 会话；集成会在 App
  登录后自动恢复，但恢复动作也会替换 App 的旧会话。若要 App 与 HA
  同时稳定在线，HA 必须使用另一个已分享设备的 IAM 账号。
- AppKey/AppSecret 由 IAM 对应的 Link Living 项目管理；项目轮换凭据时需要
  更新本地私有文件。
- 设备实体由真实 TSL 决定；不同固件可能暴露不同属性。
- 同一个风速和工作模式同时出现在主 `fan` 实体与中文选项 `select` 中：
  前者适合 HA 标准风扇卡片，后者便于按 App 的具体档位名称控制和编写自动化。
- 这是非官方集成，与 IAM 或阿里云无隶属或背书关系。

## License

[MIT](LICENSE)
