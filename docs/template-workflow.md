# Reply-template workflow

[English](template-workflow.md) | [简体中文](template-workflow.zh-CN.md)

## State model

```text
first matching email
  -> proposed template
  -> needs-review draft
  -> human edits proposal
  -> explicit approval
  -> approved template
  -> compatible existing needs-review drafts become ready
  -> ready drafts for later matching emails
```

The system never sends these drafts. The operator opens the Markdown file, verifies it, and
copies the subject/body into their mail client.

## Built-in placeholders

Every template may use:

- `{subject}`
- `{sender_name}`
- `{sender_email}`
- `{account_id}`
- `{account_label}`
- `{received_at}`

Each configured named field, such as `{case_id}`, is also available when extraction succeeds.

Only simple names are accepted. Expressions such as `{object.attribute}`, `{items[0]}`,
`{subject!r}` or `{subject:>2000000}` are rejected. Expanded output has a size limit.

## Proposal generation

If a rule has `reply_body_seed`, it becomes the initial proposed reply. If that setting is empty,
the local generator creates a conservative Korean acknowledgement containing the subject and
successfully extracted fields. This is a deterministic local starter, not AI understanding or
automatic learning from mail. No email is sent to an AI provider in this release.

`reply_language` and template `language` are labels, not automatic translation settings. For English
or Chinese drafts, provide a non-empty seed in that language or review and install one selected
example template. The original Korean fallback is unchanged. See [language support and examples](languages.md).

The generated proposal does not include the source email body or captured values. It stores
patterns and placeholders, reducing the chance of putting personal data into a reusable file.

## Approval

Edit `.runtime/proposals/<rule-id>.toml`, preview again, then approve it. Approval copies the
validated content to the configured local template directory and sets `approved = true`.

An existing approved file is not overwritten unless `--overwrite` is explicitly supplied.
Do not use overwrite as a normal update workflow: review the diff first.

When the optional personal interaction layer is enabled, an administrator may submit a reply
subject/body update from chat. The command creates a pending change and a diff. A separate
`模板确认` command applies it, saves immutable local revisions, and enables rollback. Chat updates
cannot modify match expressions or field extractors.

CLI approval refreshes existing needs-review cases only when their saved match/extraction fingerprint
matches the approved template. The interactive `回复` command can also perform this compatible
refresh. Older records without that fingerprint, or templates whose matching/extraction rules were
edited, require local re-preview of the original email and manual copying. Source bodies are not
retained in full, so the program must not guess new fields from a snippet.

Ready drafts remain immutable historical snapshots when a template changes. New content gets a new
content-addressed file rather than overwriting another preview or case's draft. Template confirmation
uses a writer lock, rejects stale proposals and records an `applying` intent; retry the same change ID
after a process interruption. Stop processes and resolve interrupted confirmations before using local
`--overwrite` or an editor to change approved templates.

## Matching rules

If zero approved templates match, a proposal workflow is used. If exactly one matches, it is
rendered. If more than one matches, generation stops as ambiguous. Tighten sender/subject/body
patterns rather than relying on file order for templates.
