# Security fixes and verification record: 0.2.1

**English** | [简体中文](security-review.zh-CN.md)

Date: 2026-10-15. Version: 0.2.1 Alpha.

This review fixed reproduced authorization-cache, mail-parsing, draft-consistency, template-update
and connector issues, and completed three rounds of local checks. It was source review and offline
adversarial regression testing, not penetration testing against live platforms or third-party
certification. It cannot guarantee the absence of unknown vulnerabilities. These results apply only
to the version and test environment recorded here, not to the separate company edition, an existing
personal deployment, or every operating system and platform.

## Scope and trust boundaries

- Changes were confined to this project being prepared for public sharing; the original personal production system was not modified.
- No real mailbox, group Webhook or Stream session was connected, and no email was sent.
- No GitHub repository was created and no code was committed or uploaded. The existing staging area was left unchanged; final fixes still need to be included in the reviewed release snapshot before publication.
- Each operator deploys independently. Allowed users share access to all mailboxes' cases, drafts and template history in that instance. Administrators additionally have ignore and template-edit permissions.
- The lateral-authorization checks covered impersonating events, switching users/groups and reusing cached responses. They do not establish group-to-mailbox isolation within an instance.
- Audiences with different data-access scopes need separate configurations, application credentials and runtime directories. The personal edition also requires the work-chat platform's application permissions.

## Fixes and affected areas

| Issue | Fix | Impact and regression focus |
| --- | --- | --- |
| Unauthorized identities could reach existing event responses; event IDs were not bound to requests | Reauthorize first, then verify platform/bot/chat/user and request fingerprints; denial paths never return the cache | Interaction service and event table; identity/content replay and revoked admin rights |
| A crashed event could remain processing indefinitely | Expiring processing leases; transient failures are retryable and completed operations reuse their result | Additive event-table migration; reentry and expired-lease recovery |
| Deep MIME, HTML and long whitespace could block later mail | MIME depth/part and read-size limits; per-UID quarantine; replace cleanup logic vulnerable to excessive backtracking | Parser, IMAP and checkpoints; valid messages after a bad UID continue processing |
| Duplicate Message-IDs or offline previews could overwrite linked drafts | Deduplicate early; include a content digest in draft filenames | Mail orchestration and drafts; original case fields and reply remain consistent |
| The first needs-review draft remained unusable after approval | Store extracted values and a rule fingerprint; generate a new ready draft when compatible | Case table, approval and reply; never guess fields from a truncated body |
| Concurrent template confirmations could overwrite newer versions; interruptions could leave files and database inconsistent | Cross-process writer lock, stale-version checks, durable `applying` intent and idempotent recovery; remove unsafe old-file rollback | Template repository and change table; concurrent confirmation and interruption after file writes |
| Placeholders allowed format expansion; string `false` was treated as true | Simple named variables only, pre-expansion size checks and strict booleans | Config, templates and events; reject attributes, indexing, format widths and conversions |
| DingTalk field mapping and acknowledgements were incorrect | Correct `senderStaffId` and SDK `message_id`; missing time/mention data no longer defaults to allowed; transient errors return a failure ACK | DingTalk connector; local adapter tests with installed SDK 0.24.3 |
| SDK logging and default HTTP behavior could leak data or hang | Suppress private SDK log content; owned HTTP timeouts, no redirects, restricted reply targets and explicit success-code checks | Stream connection/session replies and DingTalk/Feishu notifications; no real network requests |
| Ignored cases retained queued notifications; long diffs/drafts were truncated | Cancel pending jobs; require local review for long drafts; cancel oversized changes instead of approving truncated diffs | Case operations, queue and template review; in-flight notifications cannot be recalled |
| Normal local config triggered false-positive privacy checks; source archives were incomplete | Scan tracked/non-ignored release files while still rejecting force-added private files; extend Docker exclusions and source manifest | Privacy tests and packaging; keep fictional examples/fixtures, exclude runtime data |

Compatibility: database changes add tables/columns and do not delete old data. Ready drafts remain
historical snapshots and are not silently rewritten when templates change. Older records without
field fingerprints, or approvals that change matching/extraction rules, require local re-preview
of the original email and manual copying.

## Three rounds of offline verification

All three rounds used the same review process, not three independent auditors or agents. Tests
overlap; their counts must not be added as if they were independent cases.

1. Authorization and connector: `tests.test_interaction` and `tests.test_dingtalk_connector`, 17 passed.
   Covered chat/user allowlists, administrator restrictions, event freshness, cached-response identity
   substitution, official reply targets, log redaction, timeouts and failure acknowledgements.
2. Malicious inputs and recovery: `tests.test_security_regressions` and `tests.test_http_transport`, 32 passed.
   Covered deep MIME, read caps, 200,000-character malformed HTML/whitespace, template expansion,
   multiline commands, concurrent changes, crash recovery and erroneous responses. Slow-input attack
   samples ran in subprocesses with an 8-second timeout so the tests themselves could not wait forever.
3. Full compatibility and release surface: `python -B -m unittest discover -s tests -q`, 91 passed,
   no skips (Windows / Python 3.11 / DingTalk SDK 0.24.3). Included additive database migrations,
   deduplication, queues, templates, privacy, SQLite WAL/SHM sidecar exclusions and SDK tests.
   A wheel was built and all 33 source modules were checked byte-for-byte against the working tree.
   Imports, CLI help and example configuration were verified from a separate temporary installation.
   The source archive included docs, example configuration and fictional test fixtures; tests were
   also run from an unpacked archive. Archive-path checks found no private config or runtime data.

Network-related tests used synthetic inputs and substitute transports. Connector tests prohibited
real socket connections. CI is configured for core and DingTalk jobs on Python 3.11/3.12, but it was
not run on GitHub during this review. Local results must not be described as cloud or cross-platform validation.

Reproduction commands:

```bash
python -B -m unittest tests.test_interaction tests.test_dingtalk_connector -q
python -B -m unittest tests.test_security_regressions tests.test_http_transport -q
python -B -m unittest discover -s tests -q
git diff --check
```

## Dead code, loops and defensive checks

- Removed unused template wrapper methods, an unused proposal-generation argument, and a branch that redundantly wrote the checkpoint after scanning.
- Polling and Stream connection-maintenance loops are operating mechanisms, not dead loops to delete. Mail polling waits between cycles, queues have retry limits, and template locks time out.
- Error paths remain at untrusted-input, file/database and platform-callback boundaries. Failures are not reported as success to hide delivery errors.
- No multi-tenant framework, arbitrary chat-command execution or complex automatic-learning mechanism was added to this single-instance open-source tool.

## Remaining limitations and pre-release work

1. Live mailbox, DingTalk, Feishu and application-permission integration is not complete. Before real use, obtain separate authorization and verify platform fields, signatures, message lengths and session validity with an isolated test mailbox/group.
2. Custom Python regexes still run in the main process without a hard timeout. Poorly designed nested/ambiguous repetition can be slow on email input. Only trusted maintainers should edit rules, and they should test long non-matching inputs. Fixing built-in cleanup logic does not make arbitrary user regexes safe.
3. Only one mail scanner/sender and an optional companion bot may share a local state database. Multi-instance claiming, network-filesystem locks and distributed operation are unsupported. If a destination accepted a notification before local success was recorded, a retry can duplicate it; delivery is not exactly-once.
4. The SDK and transitive dependencies have not received a complete online vulnerability-database scan. This was not a dependency supply-chain audit. Resolve dependencies again in a clean environment and review security advisories before release.
5. Privacy checks are pattern scans, not complete leak detection. Manually inspect the final Git diff, all intended public history and archives. This project had no committed history to review at the time. Ignore rules cannot protect secrets already tracked by Git.
6. Runtime directories contain email snippets, fields, templates, drafts and cached event responses. Hashed user IDs do not make the database anonymous. Restrict local access and define your own backup/retention policy.
7. Sender regexes route mail; they do not authenticate the sender. A person must verify every draft and its recipient. The project has no automatic SMTP sending capability.
8. Configure a private vulnerability-reporting channel before making the repository public. Do not put reproductions containing real data into public issues. See [GitHub private reporting guidance](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately). No GitHub settings were changed in this review.

## Upgrades and recovery

Stop mail scanning, scheduled tasks and bot processes. Back up the full runtime and approved-template
directories before upgrading. First initialization applies additive migrations. Do not copy only the
main SQLite file while processes are writing: the WAL may still contain unmerged data.

Inspect parser failures with `mail-failures`. Records contain only mailbox/folder/UIDVALIDITY/UID and
a fixed reason, not raw email. Messages reaching the size cap are also conservatively quarantined
without automatic retry. The source email remains in its mailbox; inspect and preview it locally,
or correct and resend it as a new UID. Transient network errors are not skipped as permanent bad mail.

After an interrupted template confirmation, resend `模板确认 <change-id>` using the same ID. Do not
delete `.writer.lock` or overwrite the template first. The operating system owns the lock and releases
it when the process exits; the lock file remaining on disk is normal. If a reply is lost, query state
or history before deciding what to do next.
