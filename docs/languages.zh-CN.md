# 语言与示例

[English](languages.md) | **简体中文**

公开文档提供双语版本。回复内容可由使用者自行配置，但程序尚未全面国际化。
本次更新不改变邮件处理、权限、模板审批或网络行为。

## 选择一份配置示例

下列文件都是完整配置，标识符、匹配／提取规则和安全设置保持一致，仅注释、显示文字和回复语言／内容不同。
所有示例数据均为虚构。

| 回复语言 | 需要复制的配置 | 可选的已审查模板示例 |
| --- | --- | --- |
| 英文 | [config.en.example.toml](../config/config.en.example.toml) | [英文模板](../templates.example/en/action-required.toml) |
| 简体中文 | [config.zh-CN.example.toml](../config/config.zh-CN.example.toml) | [中文模板](../templates.example/zh-CN/action-required.toml) |
| 韩文（原有示例） | [config.example.toml](../config/config.example.toml) | [韩文模板](../templates.example/action-required.toml) |

只选择**一份**配置，复制为被忽略的 `config/config.toml`，再配置自己的邮箱、匹配规则和目标环境变量名。
不要把真实设置写入公开示例文件。中英文种子正文都使用虚构的英文邮件
[sample_alert.eml](../tests/fixtures/sample_alert.eml)进行匹配；回复语言不会改变规则所匹配的来信语言或结构。

例如，选择中文：

```bash
cp config/config.zh-CN.example.toml config/config.toml
mail-to-workchat --config config/config.toml check-config
mail-to-workchat --config config/config.toml preview-eml tests/fixtures/sample_alert.eml
```

`preview-eml` 不联网，但会在本地写入提案和草稿，请将这些文件保持私有。
安装方法及连接真实环境前的注意事项，见[快速开始](getting-started.zh-CN.md)。

## 回复语言由正文决定，不会自动翻译

- `reply_language`、`default_reply_language` 和模板的 `language` 都是语言标记，不会翻译文本或选择界面语言。
- 生成新提案时，请使用目标语言填写非空的 `reply_body_seed`，保留 `{case_id}`、`{subject}` 等占位符原样。
- 种子正文为空时，无论语言标记是什么，仍使用原有韩文兜底内容。中英文配置通过提供非空种子正文避免这种情况。
- 修改种子正文或语言标记，不会重写已有提案、已批准模板或 ready 草稿。请检查现有本地文件，并遵循[模板工作流](template-workflow.zh-CN.md)。
- 生成过程是确定性的本地处理，不调用 AI 服务商，不理解任意邮件，也不会自动进行跨语言翻译。

## 每次只使用一种模板版本

建议的首次使用流程是：预览示例邮件，审查生成的提案，再明确批准。
另一种本地测试方式是先审查一份示例模板，创建本地 `templates/` 目录后，将该文件复制为
`templates/action-required.toml`。这些虚构示例已包含 `approved = true`，复制后即按已批准模板使用，
因此必须在复制**之前**完成审查。不要覆盖现有私有模板。

三个示例有意使用相同的 ID 和匹配规则。中英文文件分别放在示例子目录中，不属于运行时模板目录。
不要把全部语言版本放入同一个运行目录，不要将 `templates_dir` 指向 `templates.example/`，
也不要期望语言标记自动选择版本。重复 ID 或重叠的已批准匹配可能导致草稿生成停止。
确实不同的工作流应使用不同且互不重叠的规则／模板。

## 当前程序的语言支持

| 范围 | 当前行为 |
| --- | --- |
| README、部署、架构、隐私、安全、贡献和模板指南 | 英文与简体中文，提供相互切换链接 |
| 示例配置与回复正文 | 新增英文／中文选项，保留原有韩文回复示例 |
| CLI 帮助与输出 | 以英文为主，部分错误仍为中文 |
| 机器人帮助、回复和错误 | 以中文为主，没有运行时语言切换功能 |
| 机器人基础输入 | `help`、`query`、`reply`、`ignore` 及对应中文指令 |
| 模板管理输入 | 准确的中文关键词及 `主题:`／`正文:` 标记，详见[个人版](personal-edition.zh-CN.md#指令) |
| 许可证 | 原有英文 [MIT LICENSE](../LICENSE) 为正式许可证文本 |

可以按需翻译回复正文，但不要翻译 TOML 键名、命令名、环境变量名、ID、提取表达式或占位符。
切换文档语言不会切换正在运行的服务配置。

## 保持双语文档同步

英文文件沿用原来的 `.md` 文件名，中文文件使用 `.zh-CN.md`。
行为、指令、安全边界或验证状态发生变化时，应同步更新两种语言。两者都必须保留 Alpha 标识，
区分离线回归结果与真实联调。历史安全记录中的测试数量只对应所注明的日期，不代表此后每次文档修改的结果。
翻译中不得加入真实邮件、业务规则、个人关键词库或私有部署细节。
