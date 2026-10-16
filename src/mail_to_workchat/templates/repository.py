from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import tomllib
from dataclasses import asdict
from pathlib import Path

from ..models import FieldSpec, MatchSpec, TemplateSpec
from ..security import resolve_under
from ..storage.locking import file_lock
from .formatting import placeholders


class TemplateError(ValueError):
    pass


_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_BUILTIN_PLACEHOLDERS = {
    "subject",
    "sender_name",
    "sender_email",
    "account_id",
    "account_label",
    "received_at",
}


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass


def template_to_toml(template: TemplateSpec) -> str:
    lines = [
        f"id = {_quoted(template.id)}",
        f"description = {_quoted(template.description)}",
        f"approved = {'true' if template.approved else 'false'}",
        f"language = {_quoted(template.language)}",
        f"reply_subject = {_quoted(template.reply_subject)}",
        f"reply_body = {_quoted(template.reply_body)}",
        "",
        "[match]",
        f"sender_regex = {_quoted(template.match.sender_regex)}",
        f"subject_regex = {_quoted(template.match.subject_regex)}",
        f"body_regex = {_quoted(template.match.body_regex)}",
    ]
    for name, spec in template.fields.items():
        lines.extend(
            (
                "",
                f"[fields.{name}]",
                f"source = {_quoted(spec.source)}",
                f"pattern = {_quoted(spec.pattern)}",
                f"required = {'true' if spec.required else 'false'}",
            )
        )
    return "\n".join(lines) + "\n"


def context_digest(template: TemplateSpec) -> str:
    # A saved extraction can only be reused if its matching/extraction contract is unchanged.
    value = {"match": asdict(template.match), "fields": {k: asdict(v) for k, v in template.fields.items()}}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def validate_template(template: TemplateSpec, *, source_name: str = "template") -> TemplateSpec:
    if not _ID_RE.fullmatch(template.id):
        raise TemplateError(f"invalid template id in {source_name}")
    if not template.reply_body.strip():
        raise TemplateError(f"template {source_name} has an empty reply_body")
    try:
        names = placeholders(template.reply_subject) | placeholders(template.reply_body)
    except ValueError as exc:
        raise TemplateError(f"invalid braces in {source_name}: {exc}") from exc
    unknown = sorted(names - (_BUILTIN_PLACEHOLDERS | set(template.fields)))
    if unknown:
        raise TemplateError(f"unknown placeholders in {source_name}: {', '.join(unknown)}")
    for label, pattern in (
        ("sender_regex", template.match.sender_regex),
        ("subject_regex", template.match.subject_regex),
        ("body_regex", template.match.body_regex),
    ):
        try:
            re.compile(pattern)
        except re.error as exc:
            raise TemplateError(f"invalid {label} in {source_name}: {exc}") from exc
    for name, spec in template.fields.items():
        try:
            re.compile(spec.pattern)
        except re.error as exc:
            raise TemplateError(f"invalid pattern for {name} in {source_name}: {exc}") from exc
    return template


def _parse_template(path: Path) -> TemplateSpec:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TemplateError(f"cannot read template {path.name}: {exc}") from exc
    if not isinstance(raw.get("approved", False), bool):
        raise TemplateError("approved must be a TOML boolean")
    template_id = str(raw.get("id", ""))
    if not _ID_RE.fullmatch(template_id):
        raise TemplateError(f"invalid template id in {path.name}")
    match_raw = raw.get("match") or {}
    fields_raw = raw.get("fields") or {}
    if not isinstance(match_raw, dict) or not isinstance(fields_raw, dict):
        raise TemplateError(f"invalid match or fields table in {path.name}")
    match = MatchSpec(
        sender_regex=str(match_raw.get("sender_regex", "")),
        subject_regex=str(match_raw.get("subject_regex", "")),
        body_regex=str(match_raw.get("body_regex", "")),
    )
    fields: dict[str, FieldSpec] = {}
    for name, value in fields_raw.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", str(name)) or not isinstance(value, dict):
            raise TemplateError(f"invalid field in {path.name}: {name}")
        if not isinstance(value.get("required", False), bool):
            raise TemplateError("required must be a TOML boolean")
        source = str(value.get("source", "body"))
        if source not in {"subject", "body", "sender", "headers"}:
            raise TemplateError(f"invalid source for {name} in {path.name}")
        fields[str(name)] = FieldSpec(
            source=source,
            pattern=str(value.get("pattern", "")),
            required=bool(value.get("required", False)),
        )
    template = TemplateSpec(
        id=template_id,
        description=str(raw.get("description", "")),
        approved=bool(raw.get("approved", False)),
        language=str(raw.get("language", "ko")),
        match=match,
        fields=fields,
        reply_subject=str(raw.get("reply_subject", "Re: {subject}")),
        reply_body=str(raw.get("reply_body", "")),
        source_path=path,
    )
    return validate_template(template, source_name=path.name)


class TemplateRepository:
    def __init__(self, templates_dir: Path, proposals_dir: Path):
        self.templates_dir = templates_dir.resolve()
        self.proposals_dir = proposals_dir.resolve()

    def write_lock(self):
        return file_lock(self.templates_dir / ".writer.lock")

    def load_approved(self) -> tuple[TemplateSpec, ...]:
        if not self.templates_dir.exists():
            return ()
        templates = []
        for path in sorted(self.templates_dir.glob("*.toml")):
            template = _parse_template(path)
            if template.approved:
                templates.append(template)
        return tuple(templates)

    def approved_path(self, template_id: str) -> Path:
        if not _ID_RE.fullmatch(template_id):
            raise TemplateError("template id is invalid")
        return resolve_under(self.templates_dir, self.templates_dir / f"{template_id}.toml")

    def load_approved_by_id(self, template_id: str) -> TemplateSpec:
        path = self.approved_path(template_id)
        if not path.is_file():
            raise TemplateError(f"approved template not found: {template_id}")
        template = _parse_template(path)
        if not template.approved:
            raise TemplateError(f"template is not approved: {template_id}")
        return template

    def replace_approved(self, template: TemplateSpec) -> Path:
        with self.write_lock():
            return self._replace_approved_locked(template)

    def _replace_approved_locked(self, template: TemplateSpec) -> Path:
        """Caller must hold write_lock across read, validation and replacement."""
        if not template.approved:
            raise TemplateError("replacement template must remain approved")
        validate_template(template, source_name=template.id)
        target = self.approved_path(template.id)
        if not target.is_file():
            raise TemplateError(f"approved template not found: {template.id}")
        _atomic_write(target, template_to_toml(template))
        return target

    def list_proposals(self) -> tuple[TemplateSpec, ...]:
        if not self.proposals_dir.exists():
            return ()
        return tuple(_parse_template(path) for path in sorted(self.proposals_dir.glob("*.toml")))

    def proposal_path(self, template_id: str) -> Path:
        if not _ID_RE.fullmatch(template_id):
            raise TemplateError("proposal id is invalid")
        return resolve_under(self.proposals_dir, self.proposals_dir / f"{template_id}.toml")

    def save_proposal_if_absent(self, template: TemplateSpec) -> tuple[Path, bool]:
        with self.write_lock():
            path = self.proposal_path(template.id)
            if path.exists():
                return path, False
            _atomic_write(path, template_to_toml(template))
            return path, True

    def load_proposal(self, template_id: str) -> TemplateSpec:
        path = self.proposal_path(template_id)
        if not path.is_file():
            raise TemplateError(f"proposal not found: {template_id}")
        return _parse_template(path)

    def approve(self, template_id: str, *, overwrite: bool = False) -> Path:
        with self.write_lock():
            return self._approve_locked(template_id, overwrite=overwrite)

    def _approve_locked(self, template_id: str, *, overwrite: bool) -> Path:
        proposal = self.load_proposal(template_id)
        approved = TemplateSpec(
            id=proposal.id,
            description=proposal.description,
            approved=True,
            language=proposal.language,
            match=proposal.match,
            fields=proposal.fields,
            reply_subject=proposal.reply_subject,
            reply_body=proposal.reply_body,
        )
        target = self.approved_path(approved.id)
        if target.exists() and not overwrite:
            raise TemplateError(f"approved template already exists: {approved.id}")
        _atomic_write(target, template_to_toml(approved))
        return target


def write_text_atomic(path: Path, content: str) -> None:
    _atomic_write(path, content)
