# 快速开始

[English](getting-started.md) | **简体中文**

本指南介绍 Alpha 版本的部署方式，不代表所有操作系统、邮箱或办公平台都已通过真实联调。请同时阅读
[部署概览](../README.zh-CN.md#框架与部署环境)和[验证范围](security-review.zh-CN.md)。
随附的 Dockerfile 只安装核心 CLI，默认执行 `--help`；不包含 Web 管理服务，也不包含可选的钉钉
Stream SDK。请使用自己本地的配置、运行数据和模板目录，不要复用或公开其他部署的资料。

## 1. 准备邮箱

在邮箱服务商处启用 IMAP；如支持，优先使用应用专用密码。本版本仅支持使用密码的标准 IMAP，
不包含 Gmail 或 Microsoft OAuth。

将 `config/config.zh-CN.example.toml` 复制为 `config/config.toml`，然后修改：

- 邮箱 ID 和显示名称；
- IMAP 主机、端口、用户名、文件夹和 TLS 模式；
- 保存邮箱密码的环境变量名；
- 一条或多条匹配规则；
- 启用的通知目标。

邮箱 ID、规则 ID 和通知目标 ID 是稳定的本地标识。服务开始运行后修改这些 ID，可能会创建新的状态范围。

中文示例已提供中文 `reply_body_seed`。也可选择英文或原有韩文示例，详见[语言与示例](languages.zh-CN.md)。
只修改 `reply_language` 不会翻译文本；种子正文为空时，仍会使用现有的韩文兜底内容。

## 2. 配置办公群通知目标

在目标群创建自定义机器人，将 Webhook URL 放入环境变量，不要写入 TOML。如果启用了签名校验，
请把签名密钥放入另一个环境变量，并设置 `secret_env`。

平台参考：

- [钉钉自定义机器人](https://open.dingtalk.com/document/orgapp/custom-robot-access)
- [飞书自定义机器人](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)

这里配置的是单向通知用的自定义机器人。飞书自定义机器人不能接收用户消息或卡片回传事件；如需交互，
必须另外实现经过身份验证的应用机器人。

使用通用通知目标时，应明确限定组织的主机域名范围：

```toml
[[notifiers]]
id = "internal-hook"
kind = "generic"
webhook_env = "GENERIC_WEBHOOK_URL"
allowed_hosts = ["hooks.example.com"]
enabled = true
```

通用端点接收 POST 请求，请求体包含 `event`、`title`、`text`、`message_key` 和 `metadata` 字段。

## 3. 编写规则

规则按配置顺序执行，第一个匹配且启用的规则生效。发件人、主题或正文的匹配表达式为空时，表示匹配任意值。
字段提取使用 Python 正则表达式，建议使用名为 `value` 的捕获组：

```toml
[rules.fields.case_id]
source = "body"
pattern = "(?im)^case id\\s*:\\s*(?P<value>[A-Z0-9-]+)"
required = true
```

必填字段提取失败时，仍会生成邮件通知，但会阻止回复草稿生成。这样可以发现供应方格式变化或缺失字段，
而不是生成猜测性的回复。

只要启用了通知目标，每条启用的规则都必须显式列出 `notifier_ids`。程序不会默认发送给所有目标，
因此以后增加通知端不会悄悄扩大现有规则的接收范围。

## 4. 离线测试

导出或构造脱敏的 `.eml` 文件，运行 `preview-eml`。该命令不会建立 IMAP 连接，也不会派发发件箱中的通知。
在本地检查提取字段、模板提案和草稿。

## 5. 建立首次同步基线

首次连接真实邮箱时，保留 `initial_sync = "baseline"`：跳过已有邮件，记录当前 UID。
如确实需要处理历史邮件，可使用 `process_existing` 并将 `max_messages_per_run` 设得较小，
但只应在空测试群或使用 `--no-send` 时尝试。

## 6. 日常运行

选择一种运行方式：

- 持续运行 `mail-to-workchat ... run`；
- 使用 Windows 任务计划程序、systemd timer、cron 或其他管理工具定时执行 `run-once`；
- 在容器中挂载配置、运行数据和模板目录后运行。

同一状态数据库只应运行一个邮件轮询／通知发送进程。可选的伴随机器人可以共享本地状态和模板目录；
不要运行重叠的轮询进程或重复的 Stream 会话。备份运行数据和模板时，应停止所有相关进程；
若数据库仍在运行，应采用支持 SQLite 一致性的备份方式。不支持网络文件系统锁或分布式部署。

使用 `mail-failures --limit 20` 查看被隔离邮件的 UID、位置和原因元数据。达到 MIME 深度／部件数量限制、
发生永久解析错误或原始大小达到 `max_message_bytes` 的邮件，会记录原因后跳过。达到大小上限时采取保守拒绝策略，
即使邮件实际大小恰好等于上限也如此，因为部分 IMAP 拉取无法证明已取得完整邮件。原邮箱中的邮件不会被修改。
请在邮件客户端检查原信，并在本地预览脱敏副本；修正并重新发送为新 UID 后可正常处理。修改限制不会自动重处理
已有隔离记录。传输错误仍可重试，且不会推进检查点。

自定义正则表达式应视为可信代码：避免嵌套且存在歧义的重复匹配，并用较长的不匹配文本测试。
本版本的 Python 正则执行本身没有超时保护。

## 7. 添加个人交互层（可选）

默认配置保持单向通知。如需个人使用的钉钉应用机器人，安装可选 SDK 扩展，将基础配置复制为
`config/personal.local.toml`，启用 `[interaction]`，并配置一个启用的 `[[bots]]` 条目。
必须使用准确的群会话和用户 ID，不要使用通配符。

钉钉连接器采用 Stream 模式，不要求公开的回调端点，但仍需要应用机器人、对应的客户端 ID／密钥、
出站网络连接，以及平台允许机器人接收和回复群消息的权限。

只有在 `check-config --check-secrets` 成功后才启动连接器。指令协议和审批流程见[个人版](personal-edition.zh-CN.md)。
