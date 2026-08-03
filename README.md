# IAM Air

`iam_air` 是一个面向 Home Assistant 的非官方自定义集成，用于接入通过
“心够智家”App 管理的 IAM 空气净化器。

> 这是非官方集成。设备和实体按账号在 App 中实际可见的设备、FOG 属性及
> Link Living TSL 动态发现，不保证所有固件暴露完全相同的能力。

## 功能

- 通过 IAM 账号登录并换取阿里云生活物联网会话。
- 自动发现账号下具有空气净化器 TSL 的设备。
- 根据设备自己的 TSL 创建实体，不在代码中硬编码设备 ID 或账号数据。
- `fan`：开关、风速、运行模式。
- `button`、`number`、`select`：按设备物模型提供复位、参数和枚举控制。
- `sensor`：PM2.5、甲醛、TVOC、温度、湿度、滤芯状态、空气质量等级。
- `switch`：童锁、UV、负离子、消毒等；只为 TSL 标记为可读写的属性创建。
- 优先使用与 App 相同的账号级 MQTT 推送；推送不可用时仍保留 REST 轮询。
- MQTT 凭据被拒绝后自动丢弃旧客户端、重新申请凭据并进行有界退避，避免
  使用过期 JWT 无限重连。

## 安全与隐私

这是公开仓库，**不包含也不接受任何真实密钥或个人数据**：

- 不内置心够智家或第三方 App 的 AppKey、AppSecret。
- 不提交账号、密码、手机号、IoT Token、设备 ID、抓包、APK 或 HA
  `.storage` 数据。
- AppKey/AppSecret 只从 Home Assistant 本机的
  `/config/iam_air/credentials.json` 读取；配置界面只采集 IAM 账号和密码。
- 日志和异常不会输出请求体、密码、Token 或签名密钥。
- CI 会执行仓库敏感信息扫描。

请只使用你有权使用的 Link Living App 凭证，不要从第三方应用中提取后公开分发。
提交 Issue 时也不要粘贴账号、Token、完整设备返回或未脱敏日志。

## 安装

### HACS 自定义仓库

1. 在 HACS 的“集成”页面打开“自定义仓库”。
2. 添加 `https://github.com/wangty163/iam_air`，类型选择“集成”。
3. 安装 IAM Air 并重启 Home Assistant。

### 手动安装

将 `custom_components/iam_air` 复制到 Home Assistant 的
`config/custom_components/iam_air`，然后重启 Home Assistant。

## 配置

先在 Home Assistant 配置目录创建仅本机可读的应用凭据文件：

```json
{
  "app_key": "<your-app-key>",
  "app_secret": "<your-app-secret>"
}
```

文件路径必须是 `/config/iam_air/credentials.json`；在 POSIX 系统上权限必须
限制为当前用户可读写（例如 `chmod 600`）。然后进入“设置 → 设备与服务 →
添加集成”，搜索 `IAM Air`，输入：

- 心够智家账号手机号；
- 心够智家账号密码。

推荐在心够智家中创建 HA 专用账号，并把 M8 分享给该账号。这样可以降低主账号
登录会话相互影响的风险。

## 工作原理

1. 调用 IAM 官方账号服务登录，获得用户身份。
2. 使用该身份完成 Link Living 自有账号授权。
3. 创建 IoT 会话，并从 `/uc/listBindingByAccount` 获取绑定设备。
4. 使用 `/thing/tsl/get` 读取设备物模型。
5. 按设备通道使用 FOG 或 Link Living API 读取及控制设备。
6. 建立账号级 MQTT 推送；连接异常期间继续用 REST 兜底。

协议边界和已确认字段见 [docs/PROTOCOL.md](docs/PROTOCOL.md)。

## 开发

需要 Python 3.14.2+ 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync --group dev
uv run ruff check .
uv run pytest
uv run python scripts/check_no_secrets.py
```

## 局限

- 当前是云端推送加云端轮询兜底，尚未实现 ALCS/CoAP 局域网控制。
- 设备实体由真实 TSL 决定；不同固件可能暴露不同属性。
- 这是非官方集成，与 IAM 或阿里云无隶属或背书关系。

## License

[MIT](LICENSE)
