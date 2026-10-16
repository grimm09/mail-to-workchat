from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class ChatEventError(ValueError):
    pass


def _event_time(value: Any) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000.0
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError) as exc:
            raise ChatEventError("event timestamp is invalid") from exc
    if isinstance(value, str) and value.strip():
        normalized = value.strip()
        if normalized.isdigit():
            try:
                return _event_time(int(normalized))
            except ValueError as exc:
                raise ChatEventError("event timestamp is invalid") from exc
        normalized = normalized.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ChatEventError("event timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise ChatEventError("event timestamp must include a timezone")
        try:
            return parsed.astimezone(timezone.utc)
        except (OverflowError, ValueError) as exc:
            raise ChatEventError("event timestamp is invalid") from exc
    raise ChatEventError("event timestamp is required")


def _required_text(value: Any, name: str, *, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ChatEventError(f"{name} is required")
    result = value.strip()
    if "\x00" in result or len(result) > limit:
        raise ChatEventError(f"{name} is invalid")
    return result


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ChatEventError(f"{name} must be a boolean")
    return value


@dataclass(frozen=True)
class ChatEvent:
    event_id: str
    bot_id: str
    platform: str
    chat_id: str
    user_id: str
    text: str
    occurred_at: datetime
    is_group: bool = True
    mentioned_bot: bool = False

    @property
    def canonical_id(self) -> str:
        return f"{self.platform}:{self.bot_id}:{self.event_id}"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ChatEvent":
        if not isinstance(value, dict):
            raise ChatEventError("event must be a JSON object")
        platform = _required_text(value.get("platform"), "platform", limit=32).lower()
        return cls(
            event_id=_required_text(value.get("event_id"), "event_id"),
            bot_id=_required_text(value.get("bot_id"), "bot_id", limit=64),
            platform=platform,
            chat_id=_required_text(value.get("chat_id"), "chat_id"),
            user_id=_required_text(value.get("user_id"), "user_id"),
            text=_required_text(value.get("text"), "text", limit=12000),
            occurred_at=_event_time(value.get("occurred_at")),
            is_group=_boolean(value.get("is_group", True), "is_group"),
            mentioned_bot=_boolean(value.get("mentioned_bot", False), "mentioned_bot"),
        )


@dataclass(frozen=True)
class ChatResponse:
    text: str
    outcome: str = "ok"
