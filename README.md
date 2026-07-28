# IAM Air

`iam_air` 是一个面向 Home Assistant 的非官方自定义集成，用于接入通过
“心够智家”App 管理的 IAM 空气净化器。第一阶段目标设备为 IAM M8。

> 当前状态：Alpha。IAM、Link Living 登录和真实账号下的空气净化器发现已验证；
> 设备控制仍需覆盖更多固件和属性组合。

## 功能

- 通过 IAM 账号登录并换取阿里云生活物联网会话。
- 从 HA 主机的私有文件直接读取 Link Living AppKey/AppSecret。
- 自动发现账号下具有空气净化器 TSL 的设备。
- 根据设备自己的 TSL 创建实体，不在代码中硬编码设备 ID 或账号数据。
- `fan`：开关、风速、运行模式。
- `sensor`：PM2.5、甲醛、TVOC、温度、湿度、滤芯状态、空气质量等级。
- `switch`：童锁、UV、负离子、消毒等；只为 TSL 标记为可读写的属性创建。
- IoT Token 到期前自动刷新，30 秒云端轮询。

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
4. 创建 IoT 会话，并从 `/uc/listBindingByAccount` 获取绑定设备。
5. 使用 `/thing/tsl/get` 读取设备物模型。
6. 使用 `/thing/properties/get` 和 `/thing/properties/set` 读取及控制设备。

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

- 当前只实现云端轮询，尚未实现 ALCS/CoAP 局域网控制。
- AppKey/AppSecret 由 IAM 对应的 Link Living 项目管理；项目轮换凭据时需要
  更新本地私有文件。
- 设备实体由真实 TSL 决定；不同固件可能暴露不同属性。
- 这是非官方集成，与 IAM 或阿里云无隶属或背书关系。

## License

[MIT](LICENSE)
