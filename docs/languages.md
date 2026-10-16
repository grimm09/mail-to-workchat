# Languages and examples

**English** | [简体中文](languages.zh-CN.md)

The public documentation is bilingual. Reply text is operator-configurable; the runtime is not
fully localized. This update does not change mail processing, permissions, template approval or
network behavior.

## Choose one configuration example

Each file below is a complete configuration with the same identifiers, matching/extraction rules
and safety settings. Only comments, display text and reply language/text differ. All data is fictional.

| Reply language | Configuration to copy | Optional reviewed-template example |
| --- | --- | --- |
| English | [config.en.example.toml](../config/config.en.example.toml) | [English template](../templates.example/en/action-required.toml) |
| Simplified Chinese | [config.zh-CN.example.toml](../config/config.zh-CN.example.toml) | [Chinese template](../templates.example/zh-CN/action-required.toml) |
| Korean (original example) | [config.example.toml](../config/config.example.toml) | [Korean template](../templates.example/action-required.toml) |

Copy **one** configuration to the ignored `config/config.toml`, then configure your own mailbox,
matching rules and target environment-variable names. Do not put real settings into public example
files. English and Chinese seeds both match the fictional English email at
[sample_alert.eml](../tests/fixtures/sample_alert.eml); their reply language does not change the
language or structure of incoming mail that the rule matches.

For example, to select English:

```bash
cp config/config.en.example.toml config/config.toml
mail-to-workchat --config config/config.toml check-config
mail-to-workchat --config config/config.toml preview-eml tests/fixtures/sample_alert.eml
```

`preview-eml` is offline, but writes local proposals and drafts. Keep those files private.
For installation and live-connection precautions, follow [getting started](getting-started.md).

## Reply language is explicit text, not automatic translation

- `reply_language`, `default_reply_language` and a template's `language` are language labels; they do not translate text or select an interface language.
- For a new proposal, write a non-empty `reply_body_seed` in the desired language. Keep placeholders such as `{case_id}` and `{subject}` unchanged.
- An empty seed still uses the original Korean fallback, regardless of the label. The English and Chinese configurations avoid this by supplying their own non-empty seeds.
- Changing the seed or label does not rewrite existing proposals, approved templates or ready drafts. Review existing local files and follow the [template workflow](template-workflow.md).
- Generation is deterministic and local. It does not call an AI provider, understand arbitrary mail or translate between languages automatically.

## Use only one template variant

The recommended first-run workflow is to preview the example email, review the generated proposal,
then approve it explicitly. An alternative for local testing is to review one example template and
copy that file to `templates/action-required.toml` after creating the local `templates/` directory.
These fictional example templates already contain `approved = true`; copying one installs it as
approved, so the review must happen **before** copying. Do not overwrite an existing private template.

The three examples intentionally share an ID and matching rules. The English and Chinese files are
kept in separate example subdirectories, outside the runtime template directory. Do not copy all
variants into the same runtime directory, point `templates_dir` at `templates.example/`, or expect
the language label to choose a variant. Duplicate IDs or overlapping approved matches can stop draft
generation. Use distinct, non-overlapping rules/templates for genuinely different workflows.

## Current runtime language support

| Surface | Current behavior |
| --- | --- |
| README, deployment, architecture, privacy, security, contribution and template guides | English and Simplified Chinese, with reciprocal language links |
| Example configuration and reply text | English and Chinese alternatives; original Korean reply examples retained |
| CLI help and output | Mainly English; some errors remain Chinese |
| Bot help, responses and errors | Mainly Chinese; no runtime language switch |
| Basic bot input | `help`, `query`, `reply`, `ignore` and their Chinese equivalents |
| Template-management input | Exact Chinese keywords and `主题:` / `正文:` markers; see [personal edition](personal-edition.md#commands) |
| License | The original English [MIT LICENSE](../LICENSE) is the governing text |

Translate reply prose as needed, but do not translate TOML keys, command names, environment-variable
names, IDs, extraction patterns or placeholders. A documentation language switch does not switch
the running service's configuration.

## Keep the two documentation versions aligned

English files use the original `.md` names; Chinese files use `.zh-CN.md`. Update both versions when
behavior, commands, security boundaries or validation status change. Both must retain the Alpha
status and distinguish offline regression results from live integration. Historical security-test
counts refer to their recorded date, not every later documentation change. Do not include real
mail, business rules, personal keyword libraries or private deployment details in translations.
