from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .mail import parse_email_bytes
from .models import AppConfig, DraftResult, IncomingMessage, RuleConfig, TemplateSpec, ScanFailure
from .notifiers.factory import build_notifiers
from .processors.rules import RuleMatch, build_notification, first_matching_rule
from .sources.imap import ImapSource
from .storage.database import CaseSnapshot, Database
from .storage.outbox import FlushResult, OutboxDispatcher
from .templates.engine import save_draft, select_template, template_matches
from .templates.learning import build_proposal
from .templates.repository import TemplateError, TemplateRepository
from .templates.cases import refresh_case_draft


@dataclass(frozen=True)
class PreviewResult:
    matched: bool
    rule_id: str = ""
    draft: DraftResult | None = None
    draft_status: str = ""
    proposal_path: Path | None = None
    error: str = ""
    match: RuleMatch | None = None


@dataclass
class RunReport:
    baselined_accounts: list[str] = field(default_factory=list)
    scanned_messages: int = 0
    matched_messages: int = 0
    ignored_messages: int = 0
    duplicate_messages: int = 0
    quarantined_messages: int = 0
    errors: list[str] = field(default_factory=list)
    delivery: FlushResult = field(default_factory=FlushResult)


class Application:
    def __init__(
        self,
        config: AppConfig,
        *,
        database: Database | None = None,
        source: ImapSource | None = None,
    ):
        self.config = config
        self.config.app.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.app.templates_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir = self.config.app.data_dir / "drafts"
        self.proposals_dir = self.config.app.data_dir / "proposals"
        self.database = database or Database(self.config.app.data_dir / "state.sqlite3")
        self.source = source or ImapSource(initial_sync=self.config.app.initial_sync)
        self.templates = TemplateRepository(self.config.app.templates_dir, self.proposals_dir)
        self.notifiers = build_notifiers(self.config.notifiers)
        self.dispatcher = OutboxDispatcher(
            self.database,
            self.notifiers,
            max_attempts=self.config.app.outbox_max_attempts,
        )

    def _draft_from_template(
        self,
        template: TemplateSpec,
        message: IncomingMessage,
        status: str,
    ) -> DraftResult:
        return save_draft(
            self.drafts_dir,
            message,
            template,
            status=status,
        )

    def preview(self, message: IncomingMessage) -> PreviewResult:
        match = first_matching_rule(self.config.rules, message)
        if match is None:
            return PreviewResult(matched=False)
        if not match.rule.reply_enabled:
            return PreviewResult(matched=True, rule_id=match.rule.id, match=match)
        try:
            approved = select_template(self.templates.load_approved(), message)
            if approved is not None:
                draft = self._draft_from_template(approved, message, "ready")
                return PreviewResult(
                    matched=True,
                    rule_id=match.rule.id,
                    draft=draft,
                    draft_status="ready",
                    match=match,
                )
            if not self.config.app.auto_propose_templates:
                return PreviewResult(
                    matched=True,
                    rule_id=match.rule.id,
                    draft_status="not_configured",
                    match=match,
                )
            proposal = build_proposal(match.rule, match.values)
            proposal_path, _ = self.templates.save_proposal_if_absent(proposal)
            current_proposal = self.templates.load_proposal(proposal.id)
            if not template_matches(current_proposal, message):
                raise TemplateError("the edited proposal no longer matches this email")
            draft = self._draft_from_template(current_proposal, message, "needs_review")
            return PreviewResult(
                matched=True,
                rule_id=match.rule.id,
                draft=draft,
                draft_status="needs_review",
                proposal_path=proposal_path,
                match=match,
            )
        except TemplateError as exc:
            return PreviewResult(
                matched=True,
                rule_id=match.rule.id,
                draft_status="blocked",
                error=str(exc),
                match=match,
            )

    def _target_notifiers(self, rule: RuleConfig) -> tuple[str, ...]:
        enabled = set(self.notifiers)
        return tuple(notifier_id for notifier_id in rule.notifier_ids if notifier_id in enabled)

    def process_message(self, message: IncomingMessage) -> tuple[PreviewResult, bool]:
        if self.database.is_processed(message.message_key):
            case = self.database.find_case(message.message_key)
            return PreviewResult(
                matched=case is not None,
                rule_id=case.rule_id if case else "",
                draft_status=case.draft_status if case else "",
            ), False
        preview = self.preview(message)
        if not preview.matched or preview.match is None:
            inserted = self.database.record_message(message, rule_id=None, status="ignored")
            return preview, inserted
        notification = build_notification(
            message,
            preview.match,
            snippet_chars=self.config.app.snippet_chars,
            draft_status=preview.draft_status,
        )
        inserted = self.database.record_message(
            message,
            rule_id=preview.rule_id,
            status="matched",
            notification=notification,
            notifier_ids=self._target_notifiers(preview.match.rule),
            case_snapshot=CaseSnapshot(
                account_label=message.account_label,
                sender_email=message.sender_email,
                subject=message.subject,
                snippet=message.body[: self.config.app.snippet_chars],
                extracted=preview.draft.extracted if preview.draft else preview.match.values,
                draft_path=str(preview.draft.path) if preview.draft else "",
                draft_status=preview.draft_status,
                template_id=preview.draft.template_id if preview.draft else "",
                sender_name=message.sender_name,
                template_context_digest=preview.draft.context_digest if preview.draft else "",
            ),
        )
        return preview, inserted

    def refresh_pending_drafts(self, template_id: str) -> tuple[int, int]:
        refreshed = blocked = 0
        for case in self.database.pending_drafts(template_id):
            try:
                refresh_case_draft(case, self.templates, self.database, self.drafts_dir)
                refreshed += 1
            except TemplateError:
                blocked += 1
        return refreshed, blocked

    def run_once(self, *, send: bool = True, outbox_limit: int = 20) -> RunReport:
        report = RunReport()
        for account in self.config.accounts:
            if not account.enabled:
                continue
            try:
                checkpoint = self.database.get_checkpoint(account.id, account.folder)
                batch = self.source.scan(account, checkpoint)
                if batch.baseline_only:
                    self.database.set_checkpoint(
                        account.id,
                        account.folder,
                        batch.uid_validity,
                        batch.final_uid,
                    )
                    report.baselined_accounts.append(account.id)
                    continue
                for message in sorted((*batch.messages, *batch.failures), key=lambda item: item.uid):
                    report.scanned_messages += 1
                    if isinstance(message, ScanFailure):
                        self.database.quarantine(account.id, account.folder, batch.uid_validity, message.uid, message.reason)
                        report.quarantined_messages += 1
                    else:
                        preview, inserted = self.process_message(message)
                        if not inserted:
                            report.duplicate_messages += 1
                        elif preview.matched:
                            report.matched_messages += 1
                        else:
                            report.ignored_messages += 1
                    self.database.set_checkpoint(
                        account.id,
                        account.folder,
                        batch.uid_validity,
                        message.uid,
                    )
            except Exception as exc:
                report.errors.append(f"{account.id}: {type(exc).__name__} (operation failed; no raw server details logged)")
        if send:
            report.delivery = self.dispatcher.flush(limit=outbox_limit)
        return report

    def preview_eml(self, path: Path, *, account_id: str | None = None) -> PreviewResult:
        selected = None
        if account_id:
            selected = next((account for account in self.config.accounts if account.id == account_id), None)
            if selected is None:
                raise ValueError(f"unknown account id: {account_id}")
        else:
            selected = next((account for account in self.config.accounts if account.enabled), self.config.accounts[0])
        with path.open("rb") as stream:
            raw = stream.read(selected.max_message_bytes + 1)
        if len(raw) > selected.max_message_bytes:
            raise ValueError("preview email exceeds max_message_bytes")
        message = parse_email_bytes(
            raw,
            account_id=selected.id,
            account_label=selected.label,
            folder=selected.folder,
            uid=1,
            uid_validity="offline",
        )
        return self.preview(message)
