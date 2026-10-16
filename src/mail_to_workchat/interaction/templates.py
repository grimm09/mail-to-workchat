from __future__ import annotations

import difflib
import hashlib
import tomllib
import uuid
from dataclasses import dataclass, replace

from ..models import TemplateSpec
from ..storage.database import Database, TemplateRevisionRecord
from ..templates.repository import (
    TemplateError,
    TemplateRepository,
    template_to_toml,
    validate_template,
)


@dataclass(frozen=True)
class TemplateProposalResult:
    change_id: str
    diff: str


class VersionedTemplateManager:
    def __init__(self, repository: TemplateRepository, database: Database):
        self.repository = repository
        self.database = database

    @staticmethod
    def _digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _candidate(
        current: TemplateSpec,
        *,
        reply_subject: str,
        reply_body: str,
    ) -> TemplateSpec:
        candidate = replace(
            current,
            approved=True,
            reply_subject=reply_subject,
            reply_body=reply_body,
            source_path=None,
        )
        return validate_template(candidate, source_name=current.id)

    @staticmethod
    def _diff(current: TemplateSpec, candidate: TemplateSpec) -> str:
        before = [
            f"Subject: {current.reply_subject}\n",
            "Body:\n",
            *(f"{line}\n" for line in current.reply_body.splitlines()),
        ]
        after = [
            f"Subject: {candidate.reply_subject}\n",
            "Body:\n",
            *(f"{line}\n" for line in candidate.reply_body.splitlines()),
        ]
        return "".join(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"{current.id}:current",
                tofile=f"{current.id}:proposed",
            )
        ).strip()

    def propose_update(
        self,
        template_id: str,
        *,
        reply_subject: str | None,
        reply_body: str,
        actor_hash: str,
        event_id: str,
    ) -> TemplateProposalResult:
        current = self.repository.load_approved_by_id(template_id)
        previous = self.database.template_change_for_event(event_id)
        if previous is not None:
            candidate = self._candidate(current, reply_subject=previous.reply_subject, reply_body=previous.reply_body)
            return TemplateProposalResult(previous.change_id, self._diff(current, candidate))
        candidate = self._candidate(
            current,
            reply_subject=reply_subject or current.reply_subject,
            reply_body=reply_body,
        )
        current_toml = template_to_toml(current)
        candidate_toml = template_to_toml(candidate)
        if current_toml == candidate_toml:
            raise TemplateError("proposed template is identical to the approved template")
        change_id = f"c-{uuid.uuid4().hex[:12]}"
        self.database.create_template_change(
            change_id=change_id,
            template_id=template_id,
            base_digest=self._digest(current_toml),
            reply_subject=candidate.reply_subject,
            reply_body=candidate.reply_body,
            created_by_hash=actor_hash,
            source_event_id=event_id,
        )
        return TemplateProposalResult(change_id=change_id, diff=self._diff(current, candidate))

    def apply(self, change_id: str, *, actor_hash: str) -> int:
        with self.repository.write_lock():
            return self._apply_locked(change_id, actor_hash=actor_hash)

    def _apply_locked(self, change_id: str, *, actor_hash: str) -> int:
        change = self.database.get_template_change(change_id)
        if change is None:
            raise TemplateError(f"template change not found: {change_id}")
        if change.status == "applied" and change.revision is not None:
            return change.revision
        if change.status not in {"pending", "applying"}:
            raise TemplateError(f"template change is already {change.status}: {change_id}")
        other_writes = [item for item in self.database.applying_changes(change.template_id) if item.change_id != change_id]
        if other_writes:
            raise TemplateError(f"finish interrupted confirmation first: {other_writes[0].change_id}")
        current = self.repository.load_approved_by_id(change.template_id)
        current_toml = template_to_toml(current)
        candidate = self._candidate(
            current,
            reply_subject=change.reply_subject,
            reply_body=change.reply_body,
        )
        candidate_toml = template_to_toml(candidate)
        current_digest = self._digest(current_toml)
        candidate_digest = self._digest(candidate_toml)
        if current_digest != change.base_digest and not (change.status == "applying" and current_digest == candidate_digest):
            raise TemplateError("approved template changed after this proposal; create a new proposal")
        if change.status == "pending":
            self.database.record_template_revision(
                template_id=current.id,
                content_toml=current_toml,
                content_digest=current_digest,
                changed_by_hash=actor_hash,
                reason=f"baseline before {change_id}",
            )
            if not self.database.mark_template_change_applying(change_id):
                raise TemplateError("template change was not pending during confirmation")
        # Durable intent precedes the file write. A retry finishes either side of a crash;
        # never roll an old file back over another writer's successful update.
        if current_digest != candidate_digest:
            self.repository._replace_approved_locked(candidate)
        revision = self.database.record_template_revision(
            template_id=candidate.id, content_toml=candidate_toml, content_digest=candidate_digest,
            changed_by_hash=actor_hash, reason=f"applied {change_id}",
        )
        if not self.database.mark_template_change_applied(change_id, revision):
            raise TemplateError("template update could not be finalized; retry confirmation")
        return revision

    def cancel(self, change_id: str) -> None:
        with self.repository.write_lock():
            change = self.database.get_template_change(change_id)
            if change is None:
                raise TemplateError(f"template change not found: {change_id}")
            if change.status == "cancelled":
                return
            if not self.database.cancel_template_change(change_id):
                raise TemplateError(f"template change is already {change.status}: {change_id}")

    def revisions(self, template_id: str) -> tuple[TemplateRevisionRecord, ...]:
        self.repository.load_approved_by_id(template_id)
        return self.database.list_template_revisions(template_id)

    def propose_rollback(
        self,
        template_id: str,
        revision: int,
        *,
        actor_hash: str,
        event_id: str,
    ) -> TemplateProposalResult:
        historical = self.database.get_template_revision(template_id, revision)
        if historical is None:
            raise TemplateError(f"template revision not found: {template_id} v{revision}")
        try:
            raw = tomllib.loads(historical.content_toml)
            subject = str(raw["reply_subject"])
            body = str(raw["reply_body"])
        except (KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
            raise TemplateError("stored template revision is invalid") from exc
        return self.propose_update(
            template_id,
            reply_subject=subject,
            reply_body=body,
            actor_hash=actor_hash,
            event_id=event_id,
        )
