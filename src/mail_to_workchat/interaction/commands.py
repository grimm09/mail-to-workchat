from __future__ import annotations

import re
from dataclasses import dataclass


class CommandError(ValueError):
    pass


@dataclass(frozen=True)
class Command:
    name: str
    target: str = ""
    reply_subject: str | None = None
    reply_body: str = ""
    revision: int | None = None


_CASE_RE = r"(?:m-)?[0-9a-fA-F]{8,32}"
_TEMPLATE_RE = r"[a-z][a-z0-9_-]{1,63}"
_CHANGE_RE = r"c-[0-9a-f]{12}"


def _template_update(lines: list[str], first_line: str) -> Command:
    found = re.fullmatch(rf"模板更新\s+({_TEMPLATE_RE})", first_line, flags=re.IGNORECASE)
    if not found:
        raise CommandError("格式：模板更新 <模板ID>，下一行可写主题，再用“正文:”开始正文")
    subject: str | None = None
    body_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        stripped = line.strip()
        if stripped.startswith("主题:") or stripped.startswith("主题："):
            subject = stripped[3:].strip()
        elif stripped in {"正文:", "正文："}:
            body_index = index + 1
            break
    if body_index is None:
        raise CommandError("模板更新必须包含单独一行“正文:”")
    body = "\n".join(lines[body_index:]).strip()
    if not body:
        raise CommandError("模板正文不能为空")
    if subject is not None and not subject:
        raise CommandError("模板主题不能为空")
    return Command(
        name="template_update",
        target=found.group(1).lower(),
        reply_subject=subject,
        reply_body=body,
    )


def parse_command(text: str) -> Command:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized or "\x00" in normalized:
        raise CommandError("指令不能为空")
    if len(normalized) > 12000:
        raise CommandError("指令过长")
    lines = normalized.split("\n")
    first = lines[0].strip()
    if not first.startswith("模板更新") and any(line.strip() for line in lines[1:]):
        raise CommandError("请每次只发送一条单行指令；模板更新除外")

    if first.lower() in {"帮助", "help", "?", "指令"}:
        return Command(name="help")

    found = re.fullmatch(rf"(?:查询|查|query)(?:\s+({_CASE_RE}))?", first, flags=re.IGNORECASE)
    if found:
        return Command(name="query", target=(found.group(1) or "").lower())

    found = re.fullmatch(rf"(?:回复|草稿|reply)\s+({_CASE_RE})", first, flags=re.IGNORECASE)
    if found:
        return Command(name="reply", target=found.group(1).lower())

    found = re.fullmatch(rf"(?:忽略|ignore)\s+({_CASE_RE})", first, flags=re.IGNORECASE)
    if found:
        return Command(name="ignore", target=found.group(1).lower())

    if first.startswith("模板更新"):
        return _template_update(lines, first)

    found = re.fullmatch(rf"模板确认\s+({_CHANGE_RE})", first, flags=re.IGNORECASE)
    if found:
        return Command(name="template_confirm", target=found.group(1).lower())

    found = re.fullmatch(rf"模板取消\s+({_CHANGE_RE})", first, flags=re.IGNORECASE)
    if found:
        return Command(name="template_cancel", target=found.group(1).lower())

    found = re.fullmatch(rf"模板历史\s+({_TEMPLATE_RE})", first, flags=re.IGNORECASE)
    if found:
        return Command(name="template_history", target=found.group(1).lower())

    found = re.fullmatch(
        rf"模板回滚\s+({_TEMPLATE_RE})\s+(\d+)",
        first,
        flags=re.IGNORECASE,
    )
    if found:
        revision = int(found.group(2))
        if revision <= 0:
            raise CommandError("模板版本必须为正整数")
        return Command(
            name="template_rollback",
            target=found.group(1).lower(),
            revision=revision,
        )

    raise CommandError("无法识别该指令。发送“帮助”查看可用格式。")
