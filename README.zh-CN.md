# mail-to-workchat

[English](README.md) | **简体中文**

把标准 IMAP 邮件转成钉钉、飞书或通用 Webhook 通知，并在本地生成需要人工审核和复制的回复草稿。

> 当前版本：`0.2.1`（Alpha／早期版本）。通用核心默认仍是单向通知；个人部署可选择启用钉钉应用机器人的受控群指令。任何模式都不会自动发送邮件。

## 公开范围与状态

本仓库只分享通用邮件通知、回复草稿和可选互动功能的代码、文档及虚构示例；独立公司版管理后台不包含在本仓库中。

- 不附带个人或公司的真实邮箱、邮件、凭据、业务规则、工作模板、日志或运行数据库。
- 不附带或自动读取既有个人标题关键词库、知识库及其他业务数据库。项目中的 SQLite 用于每位使用者独立生成的邮件状态与队列，不是个人词库。
- “个人互动版”指可选的部署功能，不是维护者个人环境或工作资料的打包副本。每位使用者自行配置自己的邮箱、规则和模板。

公司版测试验证中，待内部审批。

当前公开版的验证以本地离线回归为主，不代表所有邮箱、办公平台或部署环境均已完成真实联调，也不继承其他项目或个人部署的验证结论。具体范围见 [验证记录](docs/security-review.zh-CN.md)。

## 适合什么场景

- 多个邮箱收到需要处理的业务邮件，希望统一推到办公群。
- 相似邮件中包含工单号、订单号或产品编号，希望按规则提取。
- 第一次遇到某类邮件时生成回复模板提案；人工编辑、批准后，后续邮件自动替换关键信息并生成草稿。
- 希望代码能公开展示，但凭据、邮件内容和个人模板始终留在本机。

## 当前能力

- 标准 IMAP：SSL 或 STARTTLS，密码/应用专用密码从环境变量读取。
- 多邮箱、多规则、命名字段正则提取。
- 钉钉自定义机器人 Webhook。
- 飞书自定义机器人 Webhook。
- 带目标域名白名单的通用 JSON Webhook。
- SQLite 邮件去重、断点和可靠发送队列。
- 首次运行默认只建立 UID 基线，不群发历史邮件。
- 本地模板提案、显式人工批准、严格变量替换、Markdown 回复草稿。
- 完全离线的 `.eml` 预览和单元测试。
- 可选个人互动层：案件查询、显示草稿、忽略、模板提案/确认/回滚。
- 钉钉 Stream 应用机器人连接器，精确群/用户白名单、管理员分级和事件防重放。
- SQLite 互动审计；群和用户标识保存为摘要，但不代表全部存储数据已匿名化。

明确不包含：SMTP 自动回复、聊天指令直接发送邮件、OAuth、附件下载、邮件正文中的链接抓取。飞书仍支持单向通知；飞书应用机器人的入站连接器尚未包含在这一版。

这是供他人自行部署的开源项目，不是托管服务。“个人版”表示可选互动功能，不表示无需平台应用权限。同一实例是一个共同信任范围：所有获准用户可以查询该实例的案件和草稿，并没有按群或邮箱隔离。不同团队或不同可见范围应使用独立配置、凭据和数据目录。

## 语言与示例

首页和主要文档提供中英文版本；本文使用中文回复示例。英文、中文和原有韩文示例的选择方式见 [语言与示例](docs/languages.zh-CN.md)。

文档双语不代表程序已完整国际化：CLI 帮助以英文为主，部分错误和机器人回复仍为中文；基础群指令支持中英文，模板管理指令目前仍须使用中文。语言标记不会自动翻译文本；未设置 `reply_body_seed` 时，缺省草稿仍为韩文。没有新增运行界面语言切换。

## 框架与部署环境

通用核心是 Python 3.11+ 命令行程序，使用标准 IMAP、SQLite 和 Webhook；可选钉钉互动层使用 Stream SDK。本仓库不提供网页管理后台，也不依赖外部个人知识库。

| 部署方式 | 当前说明与验证边界 |
| --- | --- |
| Windows 本机 | 已有 Windows / Python 3.11 的本地离线回归记录；真实邮箱和群仍需使用者自行配置、验证。 |
| macOS / Linux 本机 | 提供 Python 安装与运行用法，不宣称这些环境已完成真实联调。 |
| Docker | 提供基于 `python:3.11-slim` 的 Linux 容器构建文件，默认只显示 CLI 帮助；镜像仅安装通用核心，不含可选 Stream SDK。不代表已完成容器端到端验证。 |

运行数据和模板使用独立的本地目录；同一状态库仅运行一个邮件扫描／发送进程。部署步骤见 [上手指南](docs/getting-started.zh-CN.md)，数据流见 [架构说明](docs/architecture.zh-CN.md)。

## 快速开始

要求 Python 3.11 或更高版本。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e .
```

复制示例配置，不要直接修改示例文件：

```bash
cp config/config.zh-CN.example.toml config/config.toml
```

Windows PowerShell 可以这样设置当前进程的环境变量：

```powershell
$env:MAILBOX_PASSWORD = "your-app-password"
$env:DINGTALK_WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send?..."
$env:DINGTALK_SIGNING_SECRET = "your-optional-signing-secret"
```

macOS/Linux：

```bash
export MAILBOX_PASSWORD='your-app-password'
export DINGTALK_WEBHOOK_URL='https://oapi.dingtalk.com/robot/send?...'
export DINGTALK_SIGNING_SECRET='your-optional-signing-secret'
```

程序不会自动读取 `.env`，以免无意间把别的项目凭据带入进程。可由你选择的进程管理器安全注入环境变量。

先验证配置，再用仓库里的虚拟邮件离线预览：

```bash
mail-to-workchat --config config/config.toml check-config
mail-to-workchat --config config/config.toml preview-eml tests/fixtures/sample_alert.eml
```

预览会在 `.runtime/proposals/` 生成待审核模板，在 `.runtime/drafts/` 生成第一封回复草稿，全程不连接邮箱、不调用 Webhook。

## 审核模板

1. 打开命令输出中的 `.runtime/proposals/<rule-id>.toml`。
2. 修改匹配条件、字段提取和回复内容；保留需要替换的 `{case_id}` 等占位符。
3. 再次离线预览确认内容。
4. 明确批准：

```bash
mail-to-workchat --config config/config.toml templates approve action-required
```

批准后的模板写入本地 `templates/`。这个目录默认被 Git 忽略；公开仓库只保留 `templates.example/` 中的虚拟示例。详细说明见 [模板工作流](docs/template-workflow.zh-CN.md)。

## 首次连接真实邮箱

先检查所有环境变量是否存在以及 Webhook 主机是否合法：

```bash
mail-to-workchat --config config/config.toml check-config --check-secrets
```

默认配置 `initial_sync = "baseline"`。首次运行只记录邮箱当前最大 UID，不处理旧邮件：

```bash
mail-to-workchat --config config/config.toml run-once --no-send
```

后续新邮件可以先只入队、不发送：

```bash
mail-to-workchat --config config/config.toml run-once --no-send
mail-to-workchat --config config/config.toml outbox-status
```

确认后再发送队列，或者持续运行：

```bash
mail-to-workchat --config config/config.toml flush-outbox
mail-to-workchat --config config/config.toml run
```

死信只显示任务 ID、目标、次数和脱敏错误，不显示邮件正文。排查并修复原因后，逐条恢复：

```bash
mail-to-workchat --config config/config.toml outbox-list --status dead_letter
mail-to-workchat --config config/config.toml outbox-retry 42
mail-to-workchat --config config/config.toml flush-outbox
```

也可以用操作系统计划任务定期执行 `run-once`。同一状态库只运行一个邮件扫描/队列发送进程；可同时运行一个可选互动机器人进程。不要让计划任务与常驻扫描进程重叠。

无法安全解析或达到 MIME 大小上限的邮件会登记隔离原因，后续 UID 仍可继续处理；原邮件不会被删除或移动。查看仅含定位信息和原因的记录：

```bash
mail-to-workchat --config config/config.toml mail-failures --limit 20
```

## 可选：个人互动版

互动版复用同一套邮件、案件、草稿和模板数据，不复制通用核心。安装钉钉 Stream 可选依赖：

```bash
python -m pip install -e ".[dingtalk]"
```

在本地配置中启用 `[interaction]` 和一个 `[[bots]]`，并填写精确的群、用户和管理员 ID 白名单；应用 ID 与密钥仍只引用环境变量。完成平台配置后启动：

```bash
mail-to-workchat --config config/personal.local.toml check-config --check-secrets
mail-to-workchat --config config/personal.local.toml bot-run dingtalk-personal
```

群内使用通知中的 `m-xxxxxxxxxxxx` 案件编号执行“查询”“回复”“忽略”等指令。“回复”只显示本地草稿供人工复制；模板聊天更新默认生成差异和待确认变更，不会直接覆盖。完整说明见 [个人互动版](docs/personal-edition.zh-CN.md)。

## 安全默认值

- 配置只能写 `password_env`、`webhook_env`、`secret_env`，不接受明文密钥字段。
- Webhook 仅允许 HTTPS；通用 Webhook 必须配置目标域名白名单。
- HTTP 重定向被拒绝，避免发送到意外目标。
- 不保存附件、不抓取附件 URL，也不访问邮件正文中的 URL；每封原始 MIME 读取有大小上限。
- 通知只带受限长度摘要；完整草稿和状态留在本地运行目录。
- 必填字段缺失或多个模板同时命中时，草稿生成会阻断。
- Webhook 失败进入退避重试，达到上限进入 `dead_letter`，不会无限重试。
- 重复邮件不会覆盖已经关联的草稿；异常 MIME 和超长模板展开有明确限制。
- 群指令先鉴权再读取事件缓存；模板确认使用跨进程锁和可重试的更新记录。

本地 SQLite、草稿和模板仍可能包含敏感业务信息。请阅读 [隐私与公开仓库检查](docs/privacy.zh-CN.md)。

从 `0.2.0` 升级前，请停止扫描和机器人进程，备份整个本地运行目录及模板目录。新版本会增量扩展 SQLite 表，不清空已有数据；旧记录缺少字段快照指纹时，需要在本机重新预览原邮件，不能自动猜测回复字段。详见 [安全修复与验证记录](docs/security-review.zh-CN.md)。

## 项目结构

```text
src/mail_to_workchat/
├── sources/       # 标准 IMAP
├── processors/    # 规则匹配与字段提取
├── templates/     # 提案、审批、渲染
├── notifiers/     # 钉钉、飞书、通用 Webhook
├── interaction/   # 可选个人群指令、权限、模板版本与钉钉 Stream
├── storage/       # SQLite 断点与可靠队列
├── app.py         # 应用编排
└── cli.py         # 命令行入口
```

架构和故障边界见 [架构说明](docs/architecture.zh-CN.md)，完整配置步骤见 [上手指南](docs/getting-started.zh-CN.md)，个人部署边界见 [个人互动版](docs/personal-edition.zh-CN.md)。

## 文档导航

- [架构说明](docs/architecture.zh-CN.md) · [上手指南](docs/getting-started.zh-CN.md)
- [个人互动版](docs/personal-edition.zh-CN.md) · [模板工作流](docs/template-workflow.zh-CN.md) · [语言与示例](docs/languages.zh-CN.md)
- [隐私与发布边界](docs/privacy.zh-CN.md) · [安全政策](SECURITY.zh-CN.md) · [安全验证记录](docs/security-review.zh-CN.md)
- [贡献指南](CONTRIBUTING.zh-CN.md) · [更新记录](CHANGELOG.zh-CN.md)

## 测试

```bash
python -m compileall -q src
python -m unittest discover -s tests -v
```

测试只使用 `example.com` 虚拟数据，不连接邮箱、不调用真实 Webhook。
安装 `.[dingtalk]` 后还会运行连接器兼容性测试；未安装时这些测试会跳过。离线测试通过不等于真实平台联调或独立渗透测试通过。

## License

本项目采用 [MIT 许可证](LICENSE)。公开内容仅限本仓库的通用代码、文档及虚构示例，不包含个人词库、真实业务规则、工作资料或私密运行数据。
英文 `LICENSE` 文件为正式许可证文本。
