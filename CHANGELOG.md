# Changelog

[English](CHANGELOG.md) | [简体中文](CHANGELOG.zh-CN.md)

All notable changes are documented here.

## Unreleased

- Add an English landing page and complete Chinese counterparts for the main documentation, with reciprocal language links.
- Add isolated English/Chinese reply examples, retain the original Korean examples, and document existing runtime language limitations without changing application behavior.
- Include the bilingual files in source distributions and privacy checks, and add offline documentation/example regression coverage.
- Confirm the MIT license for the public project while keeping private operational data outside the distribution.
- Clarify the Alpha status and distinguish deployment instructions from verified live integrations.
- Document the public mail-only scope, excluding personal keyword libraries, work data and the separate company administration project.
- Describe deployment options and require review of the final staged files, license, commit identity and rebuilt archives before publication.

## 0.2.1 - 2026-10-15

- Bound MIME structure and rendering size; quarantine unsafe messages without blocking later UIDs.
- Replace backtracking-prone HTML and whitespace cleanup with bounded-input parsing and linear cleanup.
- Deduplicate before draft generation and use content-addressed draft files to preserve recorded replies.
- Refresh first-message drafts after approval only when their saved extraction contract is unchanged.
- Bind interaction replay caches to identities and request content, recheck roles, and recover expired processing leases.
- Serialize template confirmation, detect stale proposals, and journal interrupted writes for safe retry.
- Correct DingTalk SDK callback field mapping; enforce timestamps, mention booleans, bounded HTTP and explicit success responses.
- Suppress private SDK log details and constrain session reply destinations.
- Reject truncated reply/diff approval; cancel pending notifications when a case is ignored.
- Add offline adversarial regression tests and define the single-trust-scope deployment boundary.
- Scan the intended publication surface instead of ignored local operator data; exclude private configuration from Docker builds.
- Include public configuration, documentation and synthetic test fixtures in source distributions.

Upgrade with all processes stopped and back up runtime/template directories first. SQLite migration
is additive; older case snapshots require local review rather than automatic draft refresh.

## 0.2.0 - 2026-10-14

- Added an optional personal interaction layer on top of the unchanged generic mail core.
- Added stable case references to notifications and local case lookup/state.
- Added allowlisted `query`, `reply`, and admin-only `ignore` chat commands.
- Added approved-template update proposals, explicit confirmation, immutable revisions, and rollback.
- Added stale-event rejection, event idempotency, role separation, and pseudonymized interaction audit.
- Added an optional DingTalk Stream application-bot connector; Feishu inbound interaction is not yet included.
- Reply commands remain draft-only and never send email.

## 0.1.0 - 2026-10-14

- Added standard IMAP polling with safe first-run baseline behavior.
- Added DingTalk, Feishu, and allowlisted generic webhook adapters.
- Added SQLite deduplication and retryable outbox delivery.
- Added rule-based field extraction and human-approved reply-template workflow.
- Added offline `.eml` preview, documentation, CI, and privacy regression tests.
- Reply drafts are local files only; SMTP sending and interactive chat bots are out of scope.
