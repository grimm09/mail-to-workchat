# Personal edition

[English](personal-edition.md) | [简体中文](personal-edition.zh-CN.md)

The personal edition is an optional layer over the same generic core. It does not fork or copy the
mail pipeline. A deployment can therefore keep reusable code public while its accounts, rules,
allowlists, credentials, approved templates, cases, and drafts remain local.

This is an Alpha feature set, not a bundle of the maintainer's personal environment or work data.
It includes no personal keyword database or real operational templates. Operators configure their
own accounts, rules and templates. Offline adapter tests do not establish live platform approval
or successful end-to-end operation in every deployment.

## Boundaries

- The generic core continues to poll IMAP, match rules, generate drafts, and enqueue outbound
  DingTalk/Feishu/generic Webhook notifications.
- The personal layer reads the local case and template stores and accepts commands from one or more
  explicitly configured application bots.
- Version 0.2 ships a DingTalk Stream connector. Feishu custom bots remain outbound-only; a future
  Feishu application-bot adapter can reuse the same normalized command service.
- No chat command sends email. `回复` only returns a draft for a person to copy.
- Every allowlisted user can access all cases, drafts and template history in the instance, across
  its configured mailboxes and groups. This is not multi-tenant isolation. Deploy independently
  for audiences that must not share data, using separate credentials and data directories.
- The personal edition still requires an application bot and the permissions granted by its
  platform/organization; it is not a permission bypass.

## Local configuration

Use an ignored filename such as `config/personal.local.toml`. Start from
`config/config.en.example.toml`, then enable the interaction block:

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

`admin_user_ids` must be a subset of `allowed_user_ids`. Keep the IDs in the ignored local file even
though they are not passwords. Put the client values in environment variables; never paste them in
TOML or commit them.

For DingTalk, the connector uses `senderStaffId` when present, otherwise `senderId`; the allowlist
must contain the corresponding exact identifier, not a display name. Callback header fallback uses
the SDK's `message_id`. Missing timestamps and non-boolean mention flags are rejected. Do not enable
full SDK callback logging to collect IDs: it can expose session credentials and mail content.

Install and verify:

```bash
python -m pip install -e ".[dingtalk]"
mail-to-workchat --config config/personal.local.toml check-config --check-secrets
mail-to-workchat --config config/personal.local.toml bot-run dingtalk-personal
```

Only one Stream process should use a given application credential at a time. Test with a separate
development application/group before pointing the bot at a real operations group.

Platform references:

- [DingTalk custom robot documentation](https://open.dingtalk.com/document/orgapp/custom-robot-access)
- [Official DingTalk Stream Python SDK](https://github.com/open-dingtalk/dingtalk-stream-sdk-python)
- [Feishu custom bot limitations](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)

## Commands

Documentation is bilingual, but bot responses and many errors remain Chinese. Basic commands have
English aliases; template-management commands and their `主题:` / `正文:` markers still require
the exact Chinese keywords below. They are command syntax, not translated placeholders. See
[language support](languages.md).

| Action | English input | Chinese input |
| --- | --- | --- |
| Help | `help` | `帮助` |
| List/query cases | `query` / `query m-a1b2c3d4e5f6` | `查询` / `查询 m-a1b2c3d4e5f6` |
| Show draft | `reply m-a1b2c3d4e5f6` | `回复 m-a1b2c3d4e5f6` |
| Ignore case (admin) | `ignore m-a1b2c3d4e5f6` | `忽略 m-a1b2c3d4e5f6` |

Each matching mail notification includes a local case reference such as `m-a1b2c3d4e5f6`.

```text
查询
查询 m-a1b2c3d4e5f6
回复 m-a1b2c3d4e5f6
忽略 m-a1b2c3d4e5f6
```

`查询` and `回复` require an allowed user. `忽略` also requires an administrator. Ignoring changes
local workflow state; it does not delete the source email or draft.
It also cancels pending notification jobs; already in-flight notifications may still arrive.
Long drafts are refused with a local-review instruction rather than returned as an incomplete reply.

To change only an approved template's reply subject/body:

```text
模板更新 action-required
主题: Re: {subject}
正文:
Hello,

This is an updated draft for case {case_id}.
```

The bot validates placeholders and returns a change ID plus a diff. With the recommended default,
the file remains untouched until an administrator sends:

```text
模板确认 c-0123456789ab
```

Other template operations:

```text
模板取消 c-0123456789ab
模板历史 action-required
模板回滚 action-required 1
```

A rollback is also a proposal and requires confirmation. Chat commands cannot change sender/body
matching expressions or field extraction patterns; those remain a reviewed local configuration task.

Oversized diffs are cancelled rather than truncated for approval. If confirmation is interrupted,
send `模板确认` with the same change ID again. The durable intent lets the update finish without
rolling back another writer's data. Do not delete `.writer.lock` or overwrite the template manually
while recovering a change. Updates affect future drafts, not already-ready historical drafts.

Transient processing or reply-delivery failures return a failure acknowledgement to the SDK. A retry
can reuse the authorized response without repeating the mutation, but platform redelivery/session
expiry is outside this application's control. If no reply arrives, query the case or template
history; do not assume the operation failed and blindly submit a different update.

## Offline adapter test

`chat-event` accepts a normalized event JSON file for an isolated local test. Use only synthetic IDs
that match a test configuration, and set `occurred_at` to the current timezone-aware time:

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

The event file itself may contain private platform identifiers and should use a `.local.json` name or
remain outside the repository.
