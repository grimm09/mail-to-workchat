from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import FieldSpec, IncomingMessage, Notification, RuleConfig


@dataclass(frozen=True)
class RuleMatch:
    rule: RuleConfig
    values: dict[str, str]
    missing_required: tuple[str, ...]


def _matches(pattern: str, value: str) -> bool:
    return not pattern or re.search(pattern, value, flags=re.IGNORECASE | re.MULTILINE) is not None


def rule_matches(rule: RuleConfig, message: IncomingMessage) -> bool:
    if not rule.enabled:
        return False
    sender = f"{message.sender_name} <{message.sender_email}>"
    return (
        _matches(rule.match.sender_regex, sender)
        and _matches(rule.match.subject_regex, message.subject)
        and _matches(rule.match.body_regex, message.body)
    )


def _source_text(message: IncomingMessage, source: str) -> str:
    if source == "subject":
        return message.subject
    if source == "body":
        return message.body
    if source == "sender":
        return f"{message.sender_name} <{message.sender_email}>"
    if source == "headers":
        return "\n".join(
            (
                f"From: {message.sender_name} <{message.sender_email}>",
                f"Subject: {message.subject}",
                f"Message-ID: {message.message_id}",
            )
        )
    raise ValueError(f"unsupported field source: {source}")


def extract_field(spec: FieldSpec, message: IncomingMessage) -> str:
    found = re.search(
        spec.pattern,
        _source_text(message, spec.source),
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not found:
        return ""
    if "value" in found.groupdict():
        value = found.group("value")
    elif found.lastindex:
        value = found.group(1)
    else:
        value = found.group(0)
    return re.sub(r"\s+", " ", value or "").strip()


def extract_fields(specs: dict[str, FieldSpec], message: IncomingMessage) -> tuple[dict[str, str], tuple[str, ...]]:
    values: dict[str, str] = {}
    missing: list[str] = []
    for name, spec in specs.items():
        value = extract_field(spec, message)
        if value:
            values[name] = value
        elif spec.required:
            missing.append(name)
    return values, tuple(missing)


def first_matching_rule(rules: tuple[RuleConfig, ...], message: IncomingMessage) -> RuleMatch | None:
    for rule in rules:
        if rule_matches(rule, message):
            values, missing = extract_fields(rule.fields, message)
            return RuleMatch(rule=rule, values=values, missing_required=missing)
    return None


def template_values(message: IncomingMessage, extracted: dict[str, str]) -> dict[str, str]:
    values = {
        "subject": message.subject,
        "sender_name": message.sender_name,
        "sender_email": message.sender_email,
        "account_id": message.account_id,
        "account_label": message.account_label,
        "received_at": message.received_at.isoformat(),
    }
    values.update(extracted)
    return values


def _clean_inline(value: str, limit: int = 300) -> str:
    value = " ".join(value.replace("\x00", "").split())
    for character in ("\\", "`", "*", "_", "[", "]", "<", ">"):
        value = value.replace(character, f"\\{character}")
    return value[:limit]


def build_notification(
    message: IncomingMessage,
    match: RuleMatch,
    *,
    snippet_chars: int,
    draft_status: str,
) -> Notification:
    lines = [
        f"### {_clean_inline(match.rule.notification_title, 120)}",
        "",
        f"- Case: `m-{message.message_key[:12]}`",
        f"- Rule: `{match.rule.id}`",
        f"- Mailbox: {_clean_inline(message.account_label, 120)}",
        f"- From: {_clean_inline(message.sender_email or message.sender_name, 180)}",
        f"- Subject: {_clean_inline(message.subject, 240)}",
        f"- Received: `{message.received_at.isoformat()}`",
    ]
    for key, value in match.values.items():
        lines.append(f"- {key}: {_clean_inline(value, 240)}")
    if match.missing_required:
        lines.append(f"- Missing required fields: `{', '.join(match.missing_required)}`")
    if draft_status:
        lines.append(f"- Reply draft: `{draft_status}`")
    snippet = _clean_inline(message.body, snippet_chars)
    if snippet:
        lines.extend(("", "> " + snippet.replace("\n", "\n> ")))
    return Notification(
        event_key=f"mail:{message.message_key}",
        title=match.rule.notification_title,
        text="\n".join(lines),
        message_key=message.message_key,
        metadata={
            "account_id": message.account_id,
            "case_ref": f"m-{message.message_key[:12]}",
            "rule_id": match.rule.id,
            "draft_status": draft_status,
        },
    )
