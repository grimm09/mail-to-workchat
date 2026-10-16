from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

__version__ = "0.2.1"


@dataclass(frozen=True)
class AppSettings:
    name: str
    data_dir: Path
    templates_dir: Path
    snippet_chars: int = 500
    poll_interval_seconds: int = 300
    outbox_max_attempts: int = 6
    initial_sync: str = "baseline"
    auto_propose_templates: bool = True
    default_reply_language: str = "ko"


@dataclass(frozen=True)
class MailAccount:
    id: str
    label: str
    host: str
    port: int
    username: str
    password_env: str
    folder: str = "INBOX"
    security: str = "ssl"
    enabled: bool = True
    initial_sync: str | None = None
    max_messages_per_run: int = 100
    max_message_bytes: int = 1_048_576
    timeout_seconds: float = 20.0


@dataclass(frozen=True)
class NotifierConfig:
    id: str
    kind: str
    webhook_env: str
    enabled: bool = True
    secret_env: str | None = None
    allowed_hosts: tuple[str, ...] = ()
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class InteractionSettings:
    enabled: bool = False
    event_ttl_seconds: int = 600
    response_chars: int = 3500
    template_confirmation_required: bool = True


@dataclass(frozen=True)
class BotConfig:
    id: str
    platform: str
    app_id_env: str
    app_secret_env: str
    allowed_chat_ids: tuple[str, ...]
    allowed_user_ids: tuple[str, ...]
    admin_user_ids: tuple[str, ...]
    enabled: bool = True
    require_mention: bool = True


@dataclass(frozen=True)
class FieldSpec:
    source: str
    pattern: str
    required: bool = False


@dataclass(frozen=True)
class MatchSpec:
    sender_regex: str = ""
    subject_regex: str = ""
    body_regex: str = ""


@dataclass(frozen=True)
class RuleConfig:
    id: str
    name: str
    match: MatchSpec
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    enabled: bool = True
    notifier_ids: tuple[str, ...] = ()
    notification_title: str = "New email"
    reply_enabled: bool = True
    reply_language: str = "ko"
    reply_subject_seed: str = "Re: {subject}"
    reply_body_seed: str = ""


@dataclass(frozen=True)
class AppConfig:
    source_path: Path
    app: AppSettings
    accounts: tuple[MailAccount, ...]
    notifiers: tuple[NotifierConfig, ...]
    rules: tuple[RuleConfig, ...]
    interaction: InteractionSettings = field(default_factory=InteractionSettings)
    bots: tuple[BotConfig, ...] = ()


@dataclass(frozen=True)
class IncomingMessage:
    account_id: str
    account_label: str
    folder: str
    uid: int
    uid_validity: str
    message_key: str
    message_id: str
    sender_name: str
    sender_email: str
    subject: str
    body: str
    received_at: datetime


@dataclass(frozen=True)
class Checkpoint:
    account_id: str
    folder: str
    uid_validity: str
    last_uid: int


@dataclass(frozen=True)
class ScanFailure:
    uid: int
    reason: str


@dataclass(frozen=True)
class ScanBatch:
    account_id: str
    folder: str
    uid_validity: str
    messages: tuple[IncomingMessage, ...]
    final_uid: int
    baseline_only: bool = False
    failures: tuple[ScanFailure, ...] = ()


@dataclass(frozen=True)
class Notification:
    event_key: str
    title: str
    text: str
    message_key: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "title": self.title,
            "text": self.text,
            "message_key": self.message_key,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Notification":
        return cls(
            event_key=str(value["event_key"]),
            title=str(value["title"]),
            text=str(value["text"]),
            message_key=str(value["message_key"]),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    description: str
    approved: bool
    language: str
    match: MatchSpec
    fields: dict[str, FieldSpec]
    reply_subject: str
    reply_body: str
    source_path: Path | None = None


@dataclass(frozen=True)
class DraftResult:
    path: Path
    template_id: str
    status: str
    subject: str
    body: str
    context_digest: str = ""
    extracted: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryOutcome:
    success: bool
    detail: str = ""
