# Security policy

[English](SECURITY.md) | [简体中文](SECURITY.zh-CN.md)

## Supported versions

This project is in the `0.x` stage. Security fixes are applied to the latest release only.

## Reporting a vulnerability

Do not open a public issue containing credentials, webhook URLs, real email content, or
mailbox data. Use the repository owner's private security-reporting channel instead.
Before publishing the repository, its owner must enable GitHub private vulnerability reporting
or provide another private contact. This source tree does not claim that a reporting channel
has already been configured. See [GitHub's private reporting instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

Include the affected version, a minimal reproduction using synthetic data, and the
expected impact. Remove access tokens, passwords, message bodies, and customer data.

## Secret handling

- Configuration accepts environment-variable names, never literal passwords or webhook URLs.
- Runtime data, drafts, templates, SQLite files, and `.env` files are ignored by Git.
- Rotate a credential immediately if it was ever committed. Deleting the newest copy does
  not remove it from Git history.
- The project does not save attachments, fetch attachment URLs, or follow links found in email
  bodies. Raw MIME retrieval is capped per message.
- Generic webhook destinations require an explicit host allowlist and redirects are rejected.
- Interactive bots are disabled by default and require exact chat/user/admin allowlists.
- Mutating commands are idempotent, reject stale events, and are written to a local audit table.
- Chat-driven template changes default to a second explicit confirmation and preserve revisions.
- The interactive `reply` command only returns a local draft; it cannot send email.

## Deployment trust boundary

This is independently deployed open-source software, not a multi-tenant service. All allowlisted
users in one instance can read that instance's cases, drafts and template history. Use separate
configuration, credentials and data directories for separate audiences. Administrators control
local configuration, regex patterns and templates; the application cannot protect against a user
who can modify those files or read the SQLite database.

Allowlisted sender patterns are routing rules, not proof that an email sender is authentic.
Review message content and the final recipient before manually sending any draft. Operator-supplied
Python regex patterns must be reviewed for excessive backtracking on adversarial input; their
execution is not isolated or timed out in this release.

Run only one mail poller/outbox sender per state database. A companion bot process is supported,
but distributed deployments and network-filesystem locking are not supported. Delivery is not
exactly-once: a crash after remote acceptance can cause a repeated notification.

See [the 0.2.1 review record](docs/security-review.md) for tested attacks, limitations and upgrade
instructions. Passing regression tests is not a guarantee of absence of vulnerabilities.
