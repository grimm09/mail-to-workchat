# 个人版

[English](personal-edition.md) | **简体中文**

个人版是在通用核心之上的可选功能层，不会分叉或复制邮件处理流程。因此，可复用代码可以公开，
而每次部署的账号、规则、白名单、凭据、已批准模板、事项和草稿仍保留在本地。

这是 Alpha 阶段的功能集合，不是维护者个人环境或工作资料的打包副本，不包含个人关键词数据库或真实业务模板。
使用者自行配置账号、规则和模板。离线适配测试不等同于获得真实平台审批，也不代表每个部署都已完成端到端联调。

## 功能边界

- 通用核心继续执行 IMAP 轮询、规则匹配、草稿生成，以及钉钉／飞书／通用 Webhook 通知入队。
- 个人层读取本地事项和模板存储，并接收一个或多个显式配置的应用机器人的指令。
- 0.2 版本提供钉钉 Stream 连接器。飞书自定义机器人仍仅支持单向通知；未来的飞书应用机器人适配器可以复用相同的标准化指令服务。
- 任何群指令都不会发送邮件。`回复` 只返回供人复制的草稿。
- 所有白名单用户都能访问该实例全部邮箱和群对应的事项、草稿及模板历史。这不是多租户隔离。
  需要隔离的数据受众，应使用独立部署、独立凭据和独立数据目录。
- 个人版仍需要应用机器人和平台／组织授予的权限，不能绕过权限要求。

## 本地配置

使用 `config/personal.local.toml` 等被忽略的文件名。从 `config/config.zh-CN.example.toml` 开始，
然后启用交互配置：

```toml
[interaction]
enabled = true
event_ttl_seconds = 600
response_chars = 3500
template_confirmation_required = true

[[bots]]
id = "dingtalk-personal"
platform = "dingtalk"
app_id_env = "DINGTALK_APP_CLIENT_ID"
app_secret_env = "DINGTALK_APP_CLIENT_SECRET"
allowed_chat_ids = ["replace-with-one-exact-conversation-id"]
allowed_user_ids = ["replace-with-one-exact-user-id"]
admin_user_ids = ["replace-with-one-exact-user-id"]
enabled = true
require_mention = true
```

`admin_user_ids` 必须是 `allowed_user_ids` 的子集。即使这些 ID 不是密码，也应保留在被忽略的本地文件中。
客户端 ID 和密钥放入环境变量，切勿粘贴到 TOML 或提交到仓库。

钉钉连接器优先使用 `senderStaffId`，缺失时使用 `senderId`；白名单应填写相应的准确标识，而不是显示名称。
回调头部的备用事件标识使用 SDK 的 `message_id`。缺少时间戳或提及标记不是布尔值的事件会被拒绝。
不要为了收集 ID 而开启完整 SDK 回调日志，因为其中可能暴露会话凭据和邮件内容。

安装并检查：

```bash
python -m pip install -e ".[dingtalk]"
mail-to-workchat --config config/personal.local.toml check-config --check-secrets
mail-to-workchat --config config/personal.local.toml bot-run dingtalk-personal
```

同一应用凭据同一时间只应供一个 Stream 进程使用。连接真实业务群之前，请使用独立的开发应用和测试群验证。

平台参考：

- [钉钉自定义机器人文档](https://open.dingtalk.com/document/orgapp/custom-robot-access)
- [官方钉钉 Stream Python SDK](https://github.com/open-dingtalk/dingtalk-stream-sdk-python)
- [飞书自定义机器人限制](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)

## 指令

文档提供双语版本，但机器人回复和不少错误信息仍为中文。基础指令有英文别名；模板管理指令及其中的
`主题:`／`正文:` 标记仍须使用下方准确的中文关键词。它们属于指令语法，不是可翻译的占位内容。
详见[语言支持](languages.zh-CN.md)。

| 操作 | 英文输入 | 中文输入 |
| --- | --- | --- |
| 帮助 | `help` | `帮助` |
| 列出／查询事项 | `query` / `query m-a1b2c3d4e5f6` | `查询` / `查询 m-a1b2c3d4e5f6` |
| 查看草稿 | `reply m-a1b2c3d4e5f6` | `回复 m-a1b2c3d4e5f6` |
| 忽略事项（管理员） | `ignore m-a1b2c3d4e5f6` | `忽略 m-a1b2c3d4e5f6` |

每封匹配邮件的通知都包含 `m-a1b2c3d4e5f6` 这样的本地事项编号。

```text
查询
查询 m-a1b2c3d4e5f6
回复 m-a1b2c3d4e5f6
忽略 m-a1b2c3d4e5f6
```

`查询` 和 `回复` 要求用户在白名单内；`忽略` 还要求管理员权限。忽略只改变本地工作流状态，不删除原邮件或草稿。
它也会取消 pending 状态的通知任务；已经在途的通知仍可能送达。过长草稿会要求在本机查看，
不会返回不完整的回复内容。

只更新某个已批准模板的回复主题／正文：

```text
模板更新 action-required
主题: Re: {subject}
正文:
您好，

这是事项 {case_id} 的更新草稿。
```

机器人会校验占位符，并返回变更 ID 和差异预览。采用建议的默认设置时，管理员发送以下指令之前，文件不会改变：

```text
模板确认 c-0123456789ab
```

其他模板操作：

```text
模板取消 c-0123456789ab
模板历史 action-required
模板回滚 action-required 1
```

回滚同样属于提案，需要单独确认。群指令不能改变发件人／正文匹配表达式或字段提取模式；
这些仍需作为本地配置修改进行审查。

差异过长时会取消提案，而不是截断后让人批准。如果确认过程被中断，请再次发送相同变更 ID 的 `模板确认`。
持久化意图记录允许更新继续完成，而不会回滚其他写入者的数据。恢复变更时，不要删除 `.writer.lock`，
也不要手工覆盖模板。更新只影响未来草稿，不改变已经 ready 的历史草稿。

暂时性的处理或回复投递故障会向 SDK 返回失败确认。重试可以复用已授权的响应，避免重复执行修改，
但平台是否重投、会话是否过期不受本应用控制。如果没收到回复，应先查询事项或模板历史，
不要假定操作失败后盲目提交另一次更新。

## 离线适配测试

`chat-event` 接受标准化事件 JSON 文件，用于隔离的本地测试。只使用与测试配置匹配的虚构 ID，
并将 `occurred_at` 改为当前带时区的时间：

```json
{
  "event_id": "event-example-1",
  "bot_id": "dingtalk-personal",
  "platform": "dingtalk",
  "chat_id": "replace-with-test-chat-id",
  "user_id": "replace-with-test-user-id",
  "text": "查询",
  "occurred_at": "2026-10-14T12:00:00+08:00",
  "is_group": true,
  "mentioned_bot": true
}
```

```bash
mail-to-workchat --config config/personal.local.toml chat-event event.local.json
mail-to-workchat --config config/personal.local.toml chat-audit
```

事件文件本身可能包含私有平台标识，应使用 `.local.json` 文件名，或保存在仓库之外。
