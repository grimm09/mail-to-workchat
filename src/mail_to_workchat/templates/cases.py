from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..models import IncomingMessage
from ..storage.database import CaseRecord, Database
from .engine import save_draft
from .repository import TemplateError, TemplateRepository, context_digest


def refresh_case_draft(case: CaseRecord, repository: TemplateRepository, database: Database, drafts_dir: Path) -> CaseRecord:
    if case.draft_status != "needs_review":
        return case
    with repository.write_lock():
        template = repository.load_approved_by_id(case.template_id)
        if not case.template_context_digest or context_digest(template) != case.template_context_digest:
            raise TemplateError("原记录缺少兼容的字段快照，或模板匹配/提取规则已修改；请用原邮件在本机重新预览并人工复制")
        message = IncomingMessage(
            account_id=case.account_id, account_label=case.account_label, folder="", uid=0,
            uid_validity="", message_key=case.message_key, message_id="", sender_name=case.sender_name,
            sender_email=case.sender_email, subject=case.subject, body="",
            received_at=datetime.fromisoformat(case.received_at),
        )
        draft = save_draft(drafts_dir, message, template, status="ready", supplied_values=case.extracted)
        database.update_case_draft(case.message_key, str(draft.path))
    return database.find_case(case.message_key) or case
