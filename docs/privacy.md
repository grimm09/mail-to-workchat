# Privacy and public-repository checklist

[English](privacy.md) | [简体中文](privacy.zh-CN.md)

Email systems handle data that is usually unsuitable for a public Git repository. Treat source
code and local runtime data as two separate products.

## Public distribution boundary

Publish only reusable mail-routing, draft and optional interaction code, neutral documentation,
and fictional examples. The separate company administration project is not included here.
"Personal edition" describes an optional feature set, not a copy of the maintainer's personal
installation, accounts or work materials.

Existing personal title-keyword libraries, knowledge bases, business databases, private rules
and real reply templates are outside this distribution. The application does not automatically
discover or import them. Each operator supplies their own local mail configuration and templates.
The application's SQLite state is created for that deployment; it is not a bundled keyword library.

## Never publish

- `.env` files, mailbox passwords, app passwords, API keys, signing secrets, or full Webhook URLs;
- SQLite state, outbox files, logs, crash dumps, or exported mailbox data;
- generated drafts, pending proposals, or private approved templates;
- personal keyword/knowledge libraries, business databases, and real operational rules or templates;
- real sender/recipient addresses, subjects, message IDs, customer IDs, order IDs, or attachment URLs;
- screenshots and handoff documents copied from a production environment;
- real chat/conversation IDs, application IDs, user IDs, bot credentials, or interaction event exports;
- old Git history that ever contained any of the above.

## Before every public release

1. Build the release from a fresh repository containing only allowlisted source and documentation.
2. Run the test suite, including the privacy regression scan.
3. Inspect `git status --ignored` and confirm runtime files are ignored.
4. Search the complete Git history, not only the working tree, with a secret scanner.
5. Review example files manually; examples must use reserved domains such as `example.com`.
6. If a secret was committed at any time, rotate it before publication even if history is rewritten.
7. Review the exact staged snapshot, including newly added files, against the intended final working
   version. An older staging area must not omit later fixes or documentation changes. Do not use
   an unrestricted directory upload or force-add ignored files.
8. Confirm the license and maintainer-approved public commit identity before the first publication.
   Rebuild distribution archives from the reviewed final version; older archives do not automatically
   include later documentation or source changes.

The regression scan uses tracked plus non-ignored files, not legitimate ignored local secrets.
It still rejects private configuration accidentally added with `git add -f`. Without Git metadata,
the scan checks only the documented source/example directories. Neither mode is a complete secret
scanner, Git-history audit, or permission to publish an entire working directory. Inspect built
archives separately. Docker exclusions also cover local configuration and runtime data; do not
replace them with an unrestricted build context.

## Local data retention

`.runtime/state.sqlite3` stores message keys, account IDs, UIDs, rule IDs, timestamps, notification
payloads, bounded email snippets, case state, template revisions, and interaction audit rows.
Chat and user IDs are stored in audit rows only as SHA-256-derived labels, but these are
pseudonymous rather than guaranteed anonymous. `.runtime/drafts/` contains reply content. Decide how long
you need these files and protect/back them up according to your organization's policy. Event response
caches may contain the full displayed draft, and saved extraction values may contain business data;
hashed user IDs do not make the database anonymous. Quarantine rows contain UID/location/reason only.

The application does not currently include automatic retention deletion. This is intentional:
retention policy depends on the operator's legal and business requirements.

## Remote destinations

A work-chat notification moves selected email data to another service. Configure short snippets,
narrow rules, and only the fields colleagues need. Confirm that the destination workspace and
group membership are authorized for the underlying email data.
Allowlisting a chat user authorizes access to all cases in that deployment, not only the mail sent
to that user's group. Use separate deployments when this scope is too broad.
