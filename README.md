# mail-to-workchat

**English** | [简体中文](README.zh-CN.md)

Route standard IMAP email to DingTalk, Feishu or a generic Webhook, and generate local reply drafts for human review and copying.

> Version: `0.2.1` (Alpha / early release). The generic core is one-way by default. An optional personal deployment layer supports controlled DingTalk application-bot commands. No mode sends email automatically.

## Public scope and status

This repository shares only reusable mail notifications, reply drafts and optional interaction code, documentation and fictional examples. The separate company administration project is not included.

- No real personal/company mailboxes, emails, credentials, operational rules, work templates, logs or runtime databases are distributed.
- Existing personal title-keyword libraries, knowledge bases and business databases are neither bundled nor automatically read. SQLite stores each operator's own mail state and queue; it is not a personal keyword library.
- "Personal edition" means optional deployment features, not a copy of the maintainer's personal installation or work materials. Each operator supplies their own accounts, rules and templates.

Company edition: under testing and validation, pending internal approval.

Current public-edition verification is primarily local offline regression testing. It does not establish successful live integration with every mailbox, chat platform or deployment environment, and it does not inherit validation results from other projects or personal deployments. See the [verification record](docs/security-review.md).

## Use cases

- Forward actionable messages from multiple mailboxes into a work-chat group.
- Extract case, order or product identifiers from similar messages using configured rules.
- Propose a reply template for the first matching email; after human editing and approval, substitute fields into later drafts.
- Share the reusable code while keeping credentials, mail content and private templates local.

## Capabilities

- Standard IMAP over SSL or STARTTLS, using passwords/app passwords from environment variables.
- Multiple accounts and rules, with named regular-expression field extraction.
- DingTalk and Feishu custom-robot Webhooks; generic JSON Webhooks with an explicit host allowlist.
- SQLite deduplication, checkpoints and a retryable delivery queue.
- First-run UID baseline by default, without notifying historical mail.
- Local template proposals, explicit human approval, strict variable substitution and Markdown drafts.
- Fully offline `.eml` preview and unit tests.
- Optional personal interaction: case queries, draft display, ignore, and template proposals/confirmation/rollback.
- DingTalk Stream application-bot connector with exact chat/user allowlists, administrator roles and replay protection.
- SQLite interaction audit with hashed chat/user labels; hashing does not anonymize all stored data.

Not included: automatic SMTP replies, sending email from chat commands, OAuth, attachment downloads, or fetching links in email bodies. Feishu notifications are outbound-only; this release has no Feishu application-bot inbound connector.

This is self-hosted software, not a hosted service. "Personal" does not bypass platform application permissions. All allowlisted users in an instance share access to its cases and drafts; there is no per-chat or per-mailbox isolation. Use independent configuration, credentials and data directories for audiences that must not share data.

## Languages and examples

The landing page and main documentation are available in English and Simplified Chinese. This guide uses English reply examples. See [language support and examples](docs/languages.md) for English, Chinese and original Korean examples.

Bilingual documentation is not full runtime localization: CLI help is mainly English, some errors and bot responses remain Chinese, basic chat commands have English aliases, and template-management commands still use Chinese keywords. Language labels do not translate text; an empty `reply_body_seed` still produces the existing Korean fallback. No runtime interface-language switch has been added.

## Architecture and deployment

The core is a Python 3.11+ CLI using standard IMAP, SQLite and Webhooks; the optional DingTalk layer uses the Stream SDK. This repository has no web administration UI or dependency on a personal knowledge library.

| Deployment | Current instructions and verification boundary |
| --- | --- |
| Windows host | Local offline regression results are recorded for Windows / Python 3.11. Operators must configure and validate their own live mailboxes and groups. |
| macOS / Linux host | Python installation and execution instructions are provided; live integration in these environments is not claimed. |
| Docker | The supplied Dockerfile uses `python:3.11-slim` Linux containers and defaults to CLI help. It installs the core only, without the optional Stream SDK. This is not a claim of container end-to-end validation. |

Keep runtime data and templates in separate local directories. Run only one mail poller/outbox sender per state database. See [getting started](docs/getting-started.md) and the [architecture](docs/architecture.md).

## Quick start

Requires Python 3.11 or newer.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e .
```

Copy the English example; do not put private settings into the example file:

```bash
cp config/config.en.example.toml config/config.toml
```

Set environment variables for the current process in Windows PowerShell:

```powershell
$env:MAILBOX_PASSWORD = "your-app-password"
$env:DINGTALK_WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send?..."
$env:DINGTALK_SIGNING_SECRET = "your-optional-signing-secret"
```

Or on macOS/Linux:

```bash
export MAILBOX_PASSWORD='your-app-password'
export DINGTALK_WEBHOOK_URL='https://oapi.dingtalk.com/robot/send?...'
export DINGTALK_SIGNING_SECRET='your-optional-signing-secret'
```

The application deliberately does not load `.env` automatically, to avoid importing another project's credentials. Use your chosen process manager to inject secrets securely.

Validate configuration and preview the fictional email offline:

```bash
mail-to-workchat --config config/config.toml check-config
mail-to-workchat --config config/config.toml preview-eml tests/fixtures/sample_alert.eml
```

Preview writes a proposed template under `.runtime/proposals/` and an initial draft under `.runtime/drafts/`. It does not connect to IMAP or call Webhooks.

## Review a template

1. Open `.runtime/proposals/<rule-id>.toml` from the command output.
2. Edit matching rules, field extraction and reply text. Keep the necessary placeholders, such as `{case_id}`.
3. Preview again and inspect the result.
4. Explicitly approve:

```bash
mail-to-workchat --config config/config.toml templates approve action-required
```

Approved templates are saved in the local, Git-ignored `templates/` directory. Only fictional examples under `templates.example/` belong in the public repository. See the [template workflow](docs/template-workflow.md).

## First live mailbox connection

First check that referenced environment variables exist and Webhook hosts are allowed:

```bash
mail-to-workchat --config config/config.toml check-config --check-secrets
```

Keep `initial_sync = "baseline"`. The first run records the current maximum UID without processing old messages:

```bash
mail-to-workchat --config config/config.toml run-once --no-send
```

Later new messages can be queued without sending:

```bash
mail-to-workchat --config config/config.toml run-once --no-send
mail-to-workchat --config config/config.toml outbox-status
```

Only after reviewing the configuration and queue, send queued notifications or run continuously:

```bash
mail-to-workchat --config config/config.toml flush-outbox
mail-to-workchat --config config/config.toml run
```

Dead-letter inspection shows job IDs, targets, attempt counts and sanitized errors, not email bodies. Fix the cause before retrying individual jobs:

```bash
mail-to-workchat --config config/config.toml outbox-list --status dead_letter
mail-to-workchat --config config/config.toml outbox-retry 42
mail-to-workchat --config config/config.toml flush-outbox
```

An operating-system scheduler can periodically run `run-once`. Do not overlap it with a persistent poller. Only one mail poller/outbox sender may use a state database; one optional companion bot process is supported.

Unsafe MIME or messages reaching the size limit are recorded as quarantined metadata while later UIDs can continue. The source email is not deleted or moved:

```bash
mail-to-workchat --config config/config.toml mail-failures --limit 20
```

## Optional personal interaction

This layer reuses the same mail, case, draft and template data rather than copying the core. Install the optional SDK:

```bash
python -m pip install -e ".[dingtalk]"
```

In an ignored local configuration, enable `[interaction]` and one `[[bots]]` entry with exact chat/user/admin allowlists. App credentials still reference environment variables. After configuring platform permissions:

```bash
mail-to-workchat --config config/personal.local.toml check-config --check-secrets
mail-to-workchat --config config/personal.local.toml bot-run dingtalk-personal
```

Use the notification's `m-xxxxxxxxxxxx` case reference with `query`, `reply` or `ignore`. `reply` only displays a local draft for manual copying. Template updates propose a diff and require confirmation by default; the template-management commands still use Chinese syntax. See [personal edition](docs/personal-edition.md) for exact commands and current language limitations.

## Security defaults

- Secret fields accept environment-variable names such as `password_env`, `webhook_env` and `secret_env`, not literal credentials.
- Webhooks require HTTPS; generic targets require an explicit host allowlist. Redirects are rejected.
- No attachments are saved, and no attachment/body URLs are fetched. Raw MIME reads are size-capped.
- Notifications contain bounded snippets; complete drafts and state remain in local runtime storage.
- Missing required fields or ambiguous template matches block draft generation.
- Failed delivery uses backoff and eventually `dead_letter`, not unlimited retries.
- Duplicate mail does not overwrite associated drafts. MIME structure and template expansion have explicit limits.
- Chat authorization precedes cache access. Template confirmation uses cross-process locking and retryable update records.

Local SQLite, drafts and templates may still contain sensitive business data. Read the [privacy checklist](docs/privacy.md).

Before upgrading from `0.2.0`, stop the poller and bot and back up the entire runtime and template directories. Migration adds SQLite fields without clearing existing data. Older records without extraction fingerprints require local re-preview of the original email rather than guessed fields. See the [security review](docs/security-review.md).

## Project layout

```text
src/mail_to_workchat/
├── sources/       # Standard IMAP
├── processors/    # Rule matching and field extraction
├── templates/     # Proposals, approval and rendering
├── notifiers/     # DingTalk, Feishu and generic Webhooks
├── interaction/   # Optional commands, permissions, revisions and DingTalk Stream
├── storage/       # SQLite checkpoints and delivery queue
├── app.py         # Application orchestration
└── cli.py         # Command-line entry point
```

## Documentation

- [Architecture](docs/architecture.md) · [Getting started](docs/getting-started.md)
- [Personal edition](docs/personal-edition.md) · [Template workflow](docs/template-workflow.md) · [Languages and examples](docs/languages.md)
- [Privacy](docs/privacy.md) · [Security policy](SECURITY.md) · [Security review](docs/security-review.md)
- [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## Tests

```bash
python -m compileall -q src
python -m unittest discover -s tests -v
```

Tests use fictional `example.com` data, with no real mailbox or Webhook connections. Installing `.[dingtalk]` enables SDK compatibility tests; those tests skip when the optional dependency is absent. Passing offline tests is not live-platform validation or independent penetration testing.

## License

This project uses the [MIT License](LICENSE). Public content is limited to reusable code, documentation and fictional examples, excluding personal keyword libraries, real operational rules, work materials and private runtime data. The English `LICENSE` file is the governing license text.
