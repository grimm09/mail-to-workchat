# Getting started

[English](getting-started.md) | [简体中文](getting-started.zh-CN.md)

This guide describes deployment options for the Alpha release, not certification that every
operating system or mail/chat platform has passed live integration testing. See the
[deployment overview](../README.md#architecture-and-deployment) and [verification scope](security-review.md).
The included Dockerfile installs only the core CLI and defaults to `--help`; it does not include
a web administration service or the optional DingTalk Stream SDK. Supply your own local
configuration and runtime/template directories; do not reuse or publish another installation's data.

## 1. Prepare the mailbox

Enable IMAP with your mail provider. Prefer an app-specific password when available. This
release supports standard password-based IMAP only; Gmail or Microsoft OAuth is not included.

Copy `config/config.en.example.toml` to `config/config.toml` and change:

- account ID and display label;
- IMAP host, port, username, folder, and TLS mode;
- the environment-variable name holding the password;
- one or more matching rules;
- enabled notification targets.

Account IDs, rule IDs, and notifier IDs are stable local identifiers. Changing them after the
service starts may intentionally create a new state scope.

The English example supplies an English `reply_body_seed`. Chinese and original Korean examples
are also available; see [language support and examples](languages.md). Changing `reply_language`
alone does not translate text. An empty seed still uses the existing Korean fallback.

## 2. Configure a work-chat target

Create a custom robot in the chosen work-chat group and place its Webhook URL in an environment
variable. Do not paste it into TOML. If signature verification is enabled, put that secret in a
second environment variable and set `secret_env`.

Platform references:

- [DingTalk custom robot](https://open.dingtalk.com/document/orgapp/custom-robot-access)
- [Feishu custom bot](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)

These are outbound custom robots only. Feishu custom bots cannot receive user messages or card
postback callbacks; build a separately authenticated application bot if interaction is required.

For a generic target, set an exact organizational host suffix:

```toml
[[notifiers]]
id = "internal-hook"
kind = "generic"
webhook_env = "GENERIC_WEBHOOK_URL"
allowed_hosts = ["hooks.example.com"]
enabled = true
```

The generic endpoint receives a POST body with `event`, `title`, `text`, `message_key`, and
`metadata` fields.

## 3. Write a rule

Rules run in file order; the first enabled match wins. Empty sender, subject, or body patterns
mean “any value.” Field patterns use Python regular expressions. Prefer a named `value` group:

```toml
[rules.fields.case_id]
source = "body"
pattern = "(?im)^case id\\s*:\\s*(?P<value>[A-Z0-9-]+)"
required = true
```

A required extraction failure still produces an email notification, but blocks reply-draft
generation. This makes missing or changed supplier formats visible without creating a guessed
response.

Every enabled rule must explicitly list `notifier_ids` when any notifier is enabled. There is no
implicit “send to all” behavior, so adding a new destination later cannot silently broaden the
audience for existing email rules.

## 4. Test offline

Export or construct a sanitized `.eml` and run `preview-eml`. The command does not initialize an
IMAP connection and does not dispatch the outbox. Verify the extracted fields, proposal, and
draft locally.

## 5. Establish the baseline

Keep `initial_sync = "baseline"` for the first live run. Existing messages are skipped and the
current UID is stored. To deliberately process history, use `process_existing` and a small
`max_messages_per_run`, but do this only with an empty test group or `--no-send`.

## 6. Operate

Choose one execution model:

- continuously run `mail-to-workchat ... run`;
- schedule `run-once` using Task Scheduler, systemd timers, cron, or another supervisor;
- run the container with mounted configuration, runtime, and template directories.

Run only one mail poller/outbox sender against a state database. An optional companion bot can share
its local state/template directories; do not run overlapping pollers or duplicate Stream sessions.
Back up runtime and template directories with all processes stopped, or use a SQLite-aware backup
method for a live database. Network-filesystem locks and distributed deployments are unsupported.

Use `mail-failures --limit 20` to inspect quarantined UID/location/reason metadata. MIME depth/part
limits, permanent parse failures and raw messages reaching `max_message_bytes` are skipped after
recording their reason. Reaching the cap is conservatively rejected even if the actual message is
exactly that size, because a partial IMAP fetch is not proof of completeness. The source mail is not
modified. Inspect it in the mail client and locally preview a sanitized copy; correcting/resending
it as a new UID allows normal processing. Existing quarantines are not automatically reprocessed
when a limit changes. Transport errors remain retryable and do not advance the checkpoint.

Treat custom regular expressions as trusted code: avoid nested ambiguous repetition and test with
long non-matching input. Python regex execution itself has no timeout in this release.

## 7. Add the personal interaction layer (optional)

The default profile stays one-way. For a personal DingTalk application bot, install the optional
SDK extra, copy the base configuration to `config/personal.local.toml`, enable `[interaction]`, and
configure one enabled `[[bots]]` entry. Use exact conversation and user IDs; never use a wildcard.

The DingTalk connector uses Stream mode, so it does not require a public callback endpoint. It does
require an application robot, the corresponding client ID/secret, outbound network access, and the
platform-side permissions needed for the robot to receive and reply to group messages.

Do not start the connector until `check-config --check-secrets` succeeds. See
[Personal edition](personal-edition.md) for the command protocol and approval workflow.
