from __future__ import annotations

from ..models import RuleConfig, TemplateSpec


def _default_korean_body(field_names: tuple[str, ...]) -> str:
    lines = [
        "안녕하세요.",
        "",
        "보내주신 메일을 확인했습니다.",
        "- 제목: {subject}",
    ]
    for name in field_names:
        lines.append(f"- {name}: {{{name}}}")
    lines.extend(
        (
            "",
            "관련 내용을 검토한 후 필요한 조치를 진행하겠습니다.",
            "",
            "감사합니다.",
        )
    )
    return "\n".join(lines)


def build_proposal(rule: RuleConfig, values: dict[str, str]) -> TemplateSpec:
    available_fields = tuple(name for name in rule.fields if values.get(name))
    body = rule.reply_body_seed.strip() or _default_korean_body(available_fields)
    return TemplateSpec(
        id=rule.id,
        description=f"Generated from the first message that matched rule {rule.id}; review before approval.",
        approved=False,
        language=rule.reply_language,
        match=rule.match,
        fields=rule.fields,
        reply_subject=rule.reply_subject_seed,
        reply_body=body,
    )
