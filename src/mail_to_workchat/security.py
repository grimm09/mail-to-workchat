from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOKEN_LIKE_RE = re.compile(
    r"(?i)(access[_-]?token|api[_-]?key|authorization|secret|password)(\s*[:=]\s*)([^\s,;]+)"
)


class SecurityError(ValueError):
    pass


def validate_env_name(name: str, *, field_name: str) -> str:
    if not name or not ENV_NAME_RE.fullmatch(name):
        raise SecurityError(f"{field_name} must be an environment-variable name")
    return name


def read_secret(name: str) -> str:
    validate_env_name(name, field_name="secret reference")
    value = os.environ.get(name, "")
    if not value:
        raise SecurityError(f"required environment variable is not set: {name}")
    return value


def sanitize_error(value: object, limit: int = 240) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = TOKEN_LIKE_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", text)
    text = re.sub(r"https?://[^\s]+", _redact_url_match, text)
    return text[:limit]


def _redact_url_match(match: re.Match[str]) -> str:
    try:
        parts = urlsplit(match.group(0))
        return urlunsplit((parts.scheme, parts.hostname or "redacted", "/***", "", ""))
    except ValueError:
        return "<redacted-url>"


def validate_webhook_url(
    url: str,
    *,
    allowed_hosts: tuple[str, ...],
    provider: str,
) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise SecurityError("webhook URL is invalid") from exc
    if parsed.scheme.lower() != "https":
        raise SecurityError("webhook URL must use HTTPS")
    if parsed.username or parsed.password:
        raise SecurityError("webhook URL must not contain user info")
    if parsed.fragment:
        raise SecurityError("webhook URL must not contain a fragment")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise SecurityError("webhook URL must include a host")
    normalized = tuple(item.lower().rstrip(".") for item in allowed_hosts if item)
    if not normalized:
        raise SecurityError(f"{provider} notifier has no allowed hosts")
    if not any(host == item or host.endswith(f".{item}") for item in normalized):
        raise SecurityError(f"webhook host is not allowed for {provider}: {host}")
    return url


def resolve_under(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    resolved = candidate.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise SecurityError(f"path escapes the expected directory: {candidate}")
    return resolved
