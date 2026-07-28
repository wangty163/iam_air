# IAM Air

`iam_air` 是一个面向 Home Assistant 的非官方自定义集成，用于接入通过
“心够智家”App 管理的 IAM 空气净化器。第一阶段目标设备为 IAM M8。

> 当前状态：Alpha。云端协议、动态 TSL 发现和 HA 实体映射已经实现，
> 但仍需使用真实 M8 账号完成端到端验证后才能标记为稳定版本。

## 功能

- 通过 IAM 账号登录并换取阿里云生活物联网会话。
- 从用户自行放置的官方“心够智家”APK 中在本地读取匹配的客户端凭证，
  无需手工提供 AppKey/AppSecret。
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
- APK 只从 Home Assistant 主机本地读取，不会上传；其中的 AppKey/AppSecret
  只保留在进程内存中，不写入配置、日志或诊断信息。
- 账号密码使用 HA 密码输入框采集，只保存在用户自己的 Home Assistant
  配置存储中。
- 日志和异常不会输出请求体、密码、Token 或签名密钥。
- CI 会执行仓库敏感信息扫描。

请只使用自己从官方渠道取得的“心够智家”APK，不要上传、提交或重新分发 APK
及其中的客户端凭证。提交 Issue 时也不要粘贴账号、Token、完整设备返回或
未脱敏日志。

## 安装

### HACS 自定义仓库

1. 在 HACS 的“集成”页面打开“自定义仓库”。
2. 添加 `https://github.com/wangty163/iam_air`，类型选择“集成”。
3. 安装 IAM Air 并重启 Home Assistant。

### 手动安装

将 `custom_components/iam_air` 复制到 Home Assistant 的
`config/custom_components/iam_air`，然后重启 Home Assistant。

## 配置

进入“设置 → 设备与服务 → 添加集成”，搜索 `IAM Air`，输入：

- 心够智家账号手机号；
- 心够智家账号密码；
- Home Assistant 主机上官方“心够智家”APK 的绝对路径。

例如可以在 HA 配置目录创建 `iam_air` 子目录，并把 APK 放到：

```text
/config/iam_air/xingou.apk
```

如果 HA 运行在容器中，这个路径必须是**容器内可见路径**。仓库不会提供或下载
APK；请从你自己的手机备份或官方应用分发渠道取得。

集成会定位 APK 中 `XingooConstants` 的 `APP_KEY` / `APP_SECRET` 初始化，
只在内存中使用提取值完成 Link Living 请求签名。界面不再要求填写 AppKey
或 AppSecret。

推荐在心够智家中创建 HA 专用账号，并把 M8 分享给该账号。这样可以降低主账号
登录会话相互影响的风险。

## 工作原理

1. 调用 IAM 官方账号服务登录，获得用户身份。
2. 从本地 APK 读取与 IAM App 匹配的 Link Living 客户端凭证。
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
- APK 解析依赖“心够智家”当前的 DEX 类与字段结构；App 升级若改变结构，
  集成会安全拒绝该 APK，需要同步更新解析器。
- 设备实体由真实 TSL 决定；不同固件可能暴露不同属性。
- 这是非官方集成，与 IAM 或阿里云无隶属或背书关系。

## License

[MIT](LICENSE)
