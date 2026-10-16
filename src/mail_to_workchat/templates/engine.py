from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..models import DraftResult, IncomingMessage, TemplateSpec
from ..processors.rules import extract_fields, template_values
from .repository import TemplateError, write_text_atomic, context_digest
from .formatting import placeholders, render


def _matches(pattern: str, value: str) -> bool:
    return not pattern or re.search(pattern, value, flags=re.IGNORECASE | re.MULTILINE) is not None


def template_matches(template: TemplateSpec, message: IncomingMessage) -> bool:
    sender = f"{message.sender_name} <{message.sender_email}>"
    return (
        _matches(template.match.sender_regex, sender)
        and _matches(template.match.subject_regex, message.subject)
        and _matches(template.match.body_regex, message.body)
    )


def select_template(templates: tuple[TemplateSpec, ...], message: IncomingMessage) -> TemplateSpec | None:
    matches = [template for template in templates if template_matches(template, message)]
    if len(matches) > 1:
        ids = ", ".join(template.id for template in matches)
        raise TemplateError(f"multiple approved templates match one email: {ids}")
    return matches[0] if matches else None


def _required_placeholders(value: str) -> set[str]:
    try:
        return placeholders(value)
    except ValueError as exc:
        raise TemplateError(f"invalid template braces: {exc}") from exc


def render_template(
    template: TemplateSpec,
    message: IncomingMessage,
    *,
    supplied_values: dict[str, str] | None = None,
) -> tuple[str, str]:
    extracted, missing_required = extract_fields(template.fields, message)
    if supplied_values:
        extracted.update({key: value for key, value in supplied_values.items() if value})
    if missing_required:
        still_missing = tuple(name for name in missing_required if not extracted.get(name))
        if still_missing:
            raise TemplateError(f"required fields are missing: {', '.join(still_missing)}")
    values = template_values(message, extracted)
    names = _required_placeholders(template.reply_subject) | _required_placeholders(template.reply_body)
    missing = sorted(name for name in names if not values.get(name))
    if missing:
        raise TemplateError(f"template placeholders have no value: {', '.join(missing)}")
    try:
        return render(template.reply_subject, values), render(template.reply_body, values)
    except (KeyError, ValueError) as exc:
        raise TemplateError(f"cannot render template: {exc}") from exc


def save_draft(
    drafts_dir: Path,
    message: IncomingMessage,
    template: TemplateSpec,
    *,
    status: str,
    supplied_values: dict[str, str] | None = None,
) -> DraftResult:
    subject, body = render_template(template, message, supplied_values=supplied_values)
    day_dir = drafts_dir / message.received_at.strftime("%Y-%m-%d")
    content = "\n".join(
        (
            "# Reply draft",
            "",
            f"- Status: `{status}`",
            f"- Template: `{template.id}`",
            f"- Source mailbox: `{message.account_id}`",
            f"- Source message: `{message.message_key}`",
            "",
            "## Subject",
            "",
            subject,
            "",
            "## Body",
            "",
            body,
            "",
        )
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    path = day_dir / f"{message.message_key}-{digest}.md"
    # Previews and duplicate deliveries cannot replace a previously referenced draft.
    write_text_atomic(path, content)
    extracted, _ = extract_fields(template.fields, message)
    extracted.update(supplied_values or {})
    return DraftResult(
        path=path,
        template_id=template.id,
        status=status,
        subject=subject,
        body=body,
        context_digest=context_digest(template),
        extracted=extracted,
    )
