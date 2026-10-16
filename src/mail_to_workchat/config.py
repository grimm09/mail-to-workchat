from __future__ import annotations

import re
import math
import tomllib
from pathlib import Path
from typing import Any

from .models import (
    AppConfig,
    AppSettings,
    BotConfig,
    FieldSpec,
    InteractionSettings,
    MailAccount,
    MatchSpec,
    NotifierConfig,
    RuleConfig,
)
from .security import SecurityError, validate_env_name
from .templates.formatting import placeholders


class ConfigError(ValueError):
    pass


_FORBIDDEN_LITERAL_KEYS = {
    "password",
    "passwd",
    "webhook",
    "webhook_url",
    "api_key",
    "access_token",
    "client_secret",
}
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


def _fail(message: str) -> None:
    raise ConfigError(message)


def _audit_no_literal_secrets(value: Any, path: str = "config") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            looks_sensitive = any(
                marker in normalized
                for marker in ("password", "passwd", "webhook", "api_key", "access_token", "secret")
            )
            if normalized in _FORBIDDEN_LITERAL_KEYS or (looks_sensitive and not normalized.endswith("_env")):
                _fail(f"{path}.{key} is forbidden; reference an environment variable instead")
            _audit_no_literal_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _audit_no_literal_secrets(child, f"{path}[{index}]")


def _known_keys(value: dict[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _fail(f"{name} contains unknown keys: {', '.join(unknown)}")


def _string(value: Any, name: str, *, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip():
        _fail(f"{name} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, name: str) -> str:
    result = _string(value, name)
    if not _ID_RE.fullmatch(result):
        _fail(f"{name} must start with a letter and contain only lowercase letters, numbers, _ or -")
    return result


def _positive_int(value: Any, name: str, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        _fail(f"{name} must be a positive integer")
    return value


def _positive_float(value: Any, name: str, default: float) -> float:
    if value is None:
        return default
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        _fail(f"{name} must be a positive number")
    return float(value)


def _boolean(value: Any, name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        _fail(f"{name} must be a TOML boolean (true or false, without quotes)")
    return value


def _string_list(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        _fail(f"{name} must be an array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        _fail(f"{name} must contain only non-empty strings")
    result = tuple(item.strip() for item in value)
    if len(result) != len(set(result)):
        _fail(f"{name} must not contain duplicate values")
    return result


def _relative_or_absolute(base: Path, value: Any, name: str, default: str) -> Path:
    raw = Path(_string(value, name, default=default)).expanduser()
    return (base / raw).resolve() if not raw.is_absolute() else raw.resolve()


def _compile_regex(pattern: str, name: str) -> str:
    if not pattern:
        return pattern
    try:
        re.compile(pattern)
    except re.error as exc:
        _fail(f"{name} is not a valid regular expression: {exc}")
    return pattern


def _validate_reply_placeholders(subject: str, body: str, fields: set[str], name: str) -> None:
    allowed = {
        "subject",
        "sender_name",
        "sender_email",
        "account_id",
        "account_label",
        "received_at",
    } | fields
    try:
        names = placeholders(subject) | placeholders(body)
    except ValueError as exc:
        _fail(f"{name} contains invalid braces: {exc}")
    unknown = sorted(names - allowed)
    if unknown:
        _fail(f"{name} contains unknown placeholders: {', '.join(unknown)}")


def _parse_match(value: Any, name: str) -> MatchSpec:
    raw = value or {}
    if not isinstance(raw, dict):
        _fail(f"{name} must be a table")
    _known_keys(raw, {"sender_regex", "subject_regex", "body_regex"}, name)
    return MatchSpec(
        sender_regex=_compile_regex(str(raw.get("sender_regex", "")), f"{name}.sender_regex"),
        subject_regex=_compile_regex(str(raw.get("subject_regex", "")), f"{name}.subject_regex"),
        body_regex=_compile_regex(str(raw.get("body_regex", "")), f"{name}.body_regex"),
    )


def _parse_fields(value: Any, name: str) -> dict[str, FieldSpec]:
    raw = value or {}
    if not isinstance(raw, dict):
        _fail(f"{name} must be a table")
    result: dict[str, FieldSpec] = {}
    for field_name, spec in raw.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", str(field_name)):
            _fail(f"{name}.{field_name} is not a valid placeholder name")
        if not isinstance(spec, dict):
            _fail(f"{name}.{field_name} must be a table")
        _known_keys(spec, {"source", "pattern", "required"}, f"{name}.{field_name}")
        source = _string(spec.get("source"), f"{name}.{field_name}.source")
        if source not in {"subject", "body", "sender", "headers"}:
            _fail(f"{name}.{field_name}.source must be subject, body, sender, or headers")
        pattern = _compile_regex(
            _string(spec.get("pattern"), f"{name}.{field_name}.pattern"),
            f"{name}.{field_name}.pattern",
        )
        result[str(field_name)] = FieldSpec(
            source=source,
            pattern=pattern,
            required=_boolean(spec.get("required"), f"{name}.{field_name}.required", False),
        )
    return result


def load_config(path: str | Path) -> AppConfig:
    source_path = Path(path).expanduser().resolve()
    try:
        raw = tomllib.loads(source_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file does not exist: {source_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"configuration is not valid TOML: {exc}") from exc
    _audit_no_literal_secrets(raw)
    _known_keys(raw, {"app", "accounts", "notifiers", "rules", "interaction", "bots"}, "config")
    base = source_path.parent

    app_raw = raw.get("app") or {}
    if not isinstance(app_raw, dict):
        _fail("app must be a table")
    _known_keys(
        app_raw,
        {
            "name",
            "data_dir",
            "templates_dir",
            "snippet_chars",
            "poll_interval_seconds",
            "outbox_max_attempts",
            "initial_sync",
            "auto_propose_templates",
            "default_reply_language",
        },
        "app",
    )
    initial_sync = str(app_raw.get("initial_sync", "baseline"))
    if initial_sync not in {"baseline", "process_existing"}:
        _fail("app.initial_sync must be baseline or process_existing")
    app = AppSettings(
        name=_string(app_raw.get("name"), "app.name", default="Mail to Workchat"),
        data_dir=_relative_or_absolute(base, app_raw.get("data_dir"), "app.data_dir", "../.runtime"),
        templates_dir=_relative_or_absolute(
            base, app_raw.get("templates_dir"), "app.templates_dir", "../templates"
        ),
        snippet_chars=_positive_int(app_raw.get("snippet_chars"), "app.snippet_chars", 500),
        poll_interval_seconds=_positive_int(
            app_raw.get("poll_interval_seconds"), "app.poll_interval_seconds", 300
        ),
        outbox_max_attempts=_positive_int(
            app_raw.get("outbox_max_attempts"), "app.outbox_max_attempts", 6
        ),
        initial_sync=initial_sync,
        auto_propose_templates=_boolean(app_raw.get("auto_propose_templates"), "app.auto_propose_templates", True),
        default_reply_language=_string(
            app_raw.get("default_reply_language"), "app.default_reply_language", default="ko"
        ),
    )

    interaction_raw = raw.get("interaction") or {}
    if not isinstance(interaction_raw, dict):
        _fail("interaction must be a table")
    _known_keys(
        interaction_raw,
        {
            "enabled",
            "event_ttl_seconds",
            "response_chars",
            "template_confirmation_required",
        },
        "interaction",
    )
    interaction = InteractionSettings(
        enabled=_boolean(interaction_raw.get("enabled"), "interaction.enabled", False),
        event_ttl_seconds=_positive_int(
            interaction_raw.get("event_ttl_seconds"),
            "interaction.event_ttl_seconds",
            600,
        ),
        response_chars=_positive_int(
            interaction_raw.get("response_chars"),
            "interaction.response_chars",
            3500,
        ),
        template_confirmation_required=_boolean(
            interaction_raw.get("template_confirmation_required"), "interaction.template_confirmation_required", True
        ),
    )
    if interaction.response_chars < 500 or interaction.response_chars > 12000:
        _fail("interaction.response_chars must be between 500 and 12000")

    bots: list[BotConfig] = []
    bot_ids: set[str] = set()
    for index, item in enumerate(raw.get("bots") or []):
        name = f"bots[{index}]"
        if not isinstance(item, dict):
            _fail(f"{name} must be a table")
        _known_keys(
            item,
            {
                "id",
                "platform",
                "app_id_env",
                "app_secret_env",
                "allowed_chat_ids",
                "allowed_user_ids",
                "admin_user_ids",
                "enabled",
                "require_mention",
            },
            name,
        )
        bot_id = _identifier(item.get("id"), f"{name}.id")
        if bot_id in bot_ids:
            _fail(f"duplicate bot id: {bot_id}")
        bot_ids.add(bot_id)
        platform = str(item.get("platform", "")).strip().lower()
        if platform != "dingtalk":
            _fail(f"{name}.platform must be dingtalk in this release")
        app_id_env = _string(item.get("app_id_env"), f"{name}.app_id_env")
        app_secret_env = _string(item.get("app_secret_env"), f"{name}.app_secret_env")
        try:
            validate_env_name(app_id_env, field_name=f"{name}.app_id_env")
            validate_env_name(app_secret_env, field_name=f"{name}.app_secret_env")
        except SecurityError as exc:
            raise ConfigError(str(exc)) from exc
        allowed_chat_ids = _string_list(item.get("allowed_chat_ids"), f"{name}.allowed_chat_ids")
        allowed_user_ids = _string_list(item.get("allowed_user_ids"), f"{name}.allowed_user_ids")
        admin_user_ids = _string_list(item.get("admin_user_ids"), f"{name}.admin_user_ids")
        enabled = _boolean(item.get("enabled"), f"{name}.enabled", True)
        if enabled and (not allowed_chat_ids or not allowed_user_ids or not admin_user_ids):
            _fail(
                f"{name} must define non-empty chat, user, and admin allowlists when enabled"
            )
        unknown_admins = sorted(set(admin_user_ids) - set(allowed_user_ids))
        if unknown_admins:
            _fail(f"{name}.admin_user_ids must be a subset of allowed_user_ids")
        bots.append(
            BotConfig(
                id=bot_id,
                platform=platform,
                app_id_env=app_id_env,
                app_secret_env=app_secret_env,
                allowed_chat_ids=allowed_chat_ids,
                allowed_user_ids=allowed_user_ids,
                admin_user_ids=admin_user_ids,
                enabled=enabled,
                require_mention=_boolean(item.get("require_mention"), f"{name}.require_mention", True),
            )
        )

    if interaction.enabled and not any(bot.enabled for bot in bots):
        _fail("interaction.enabled requires at least one enabled [[bots]] entry")

    accounts: list[MailAccount] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw.get("accounts") or []):
        name = f"accounts[{index}]"
        if not isinstance(item, dict):
            _fail(f"{name} must be a table")
        _known_keys(
            item,
            {
                "id",
                "label",
                "host",
                "port",
                "username",
                "password_env",
                "folder",
                "security",
                "enabled",
                "initial_sync",
                "max_messages_per_run",
                "max_message_bytes",
                "timeout_seconds",
            },
            name,
        )
        account_id = _identifier(item.get("id"), f"{name}.id")
        if account_id in seen_ids:
            _fail(f"duplicate account id: {account_id}")
        seen_ids.add(account_id)
        password_env = _string(item.get("password_env"), f"{name}.password_env")
        try:
            validate_env_name(password_env, field_name=f"{name}.password_env")
        except SecurityError as exc:
            raise ConfigError(str(exc)) from exc
        security = str(item.get("security", "ssl")).lower()
        if security not in {"ssl", "starttls"}:
            _fail(f"{name}.security must be ssl or starttls")
        account_sync = item.get("initial_sync")
        if account_sync is not None and account_sync not in {"baseline", "process_existing"}:
            _fail(f"{name}.initial_sync must be baseline or process_existing")
        accounts.append(
            MailAccount(
                id=account_id,
                label=_string(item.get("label"), f"{name}.label", default=account_id),
                host=_string(item.get("host"), f"{name}.host"),
                port=_positive_int(item.get("port"), f"{name}.port", 993 if security == "ssl" else 143),
                username=_string(item.get("username"), f"{name}.username"),
                password_env=password_env,
                folder=_string(item.get("folder"), f"{name}.folder", default="INBOX"),
                security=security,
                enabled=_boolean(item.get("enabled"), f"{name}.enabled", True),
                initial_sync=account_sync,
                max_messages_per_run=_positive_int(
                    item.get("max_messages_per_run"), f"{name}.max_messages_per_run", 100
                ),
                max_message_bytes=_positive_int(
                    item.get("max_message_bytes"), f"{name}.max_message_bytes", 1_048_576
                ),
                timeout_seconds=_positive_float(
                    item.get("timeout_seconds"), f"{name}.timeout_seconds", 20.0
                ),
            )
        )

    notifiers: list[NotifierConfig] = []
    notifier_ids: set[str] = set()
    defaults = {
        "dingtalk": ("oapi.dingtalk.com", "api.dingtalk.com"),
        "feishu": ("open.feishu.cn", "open.larksuite.com"),
        "generic": (),
    }
    for index, item in enumerate(raw.get("notifiers") or []):
        name = f"notifiers[{index}]"
        if not isinstance(item, dict):
            _fail(f"{name} must be a table")
        _known_keys(
            item,
            {
                "id",
                "kind",
                "webhook_env",
                "secret_env",
                "allowed_hosts",
                "timeout_seconds",
                "enabled",
            },
            name,
        )
        notifier_id = _identifier(item.get("id"), f"{name}.id")
        if notifier_id in notifier_ids:
            _fail(f"duplicate notifier id: {notifier_id}")
        notifier_ids.add(notifier_id)
        kind = str(item.get("kind", "")).lower()
        if kind not in defaults:
            _fail(f"{name}.kind must be dingtalk, feishu, or generic")
        webhook_env = _string(item.get("webhook_env"), f"{name}.webhook_env")
        secret_env_value = item.get("secret_env")
        secret_env = str(secret_env_value).strip() if secret_env_value else None
        try:
            validate_env_name(webhook_env, field_name=f"{name}.webhook_env")
            if secret_env:
                validate_env_name(secret_env, field_name=f"{name}.secret_env")
        except SecurityError as exc:
            raise ConfigError(str(exc)) from exc
        configured_hosts = item.get("allowed_hosts", defaults[kind])
        if not isinstance(configured_hosts, (list, tuple)):
            _fail(f"{name}.allowed_hosts must be an array")
        allowed_hosts = tuple(str(host).strip().lower() for host in configured_hosts if str(host).strip())
        if kind == "generic" and not allowed_hosts:
            _fail(f"{name}.allowed_hosts is required for generic webhooks")
        notifiers.append(
            NotifierConfig(
                id=notifier_id,
                kind=kind,
                webhook_env=webhook_env,
                enabled=_boolean(item.get("enabled"), f"{name}.enabled", True),
                secret_env=secret_env,
                allowed_hosts=allowed_hosts,
                timeout_seconds=_positive_float(
                    item.get("timeout_seconds"), f"{name}.timeout_seconds", 10.0
                ),
            )
        )

    rules: list[RuleConfig] = []
    rule_ids: set[str] = set()
    for index, item in enumerate(raw.get("rules") or []):
        name = f"rules[{index}]"
        if not isinstance(item, dict):
            _fail(f"{name} must be a table")
        _known_keys(
            item,
            {
                "id",
                "name",
                "enabled",
                "notifier_ids",
                "notification_title",
                "reply_enabled",
                "reply_language",
                "reply_subject_seed",
                "reply_body_seed",
                "match",
                "fields",
            },
            name,
        )
        rule_id = _identifier(item.get("id"), f"{name}.id")
        if rule_id in rule_ids:
            _fail(f"duplicate rule id: {rule_id}")
        rule_ids.add(rule_id)
        targets_raw = item.get("notifier_ids") or []
        if not isinstance(targets_raw, list):
            _fail(f"{name}.notifier_ids must be an array")
        targets = tuple(str(target) for target in targets_raw)
        unknown = sorted(set(targets) - notifier_ids)
        if unknown:
            _fail(f"{name}.notifier_ids references unknown notifiers: {', '.join(unknown)}")
        if _boolean(item.get("enabled"), f"{name}.enabled", True) and any(notifier.enabled for notifier in notifiers) and not targets:
            _fail(f"{name}.notifier_ids must explicitly name each notification target")
        fields = _parse_fields(item.get("fields"), f"{name}.fields")
        reply_subject_seed = _string(
            item.get("reply_subject_seed"),
            f"{name}.reply_subject_seed",
            default="Re: {subject}",
        )
        reply_body_seed = str(item.get("reply_body_seed", ""))
        _validate_reply_placeholders(
            reply_subject_seed,
            reply_body_seed,
            set(fields),
            name,
        )
        rules.append(
            RuleConfig(
                id=rule_id,
                name=_string(item.get("name"), f"{name}.name", default=rule_id),
                match=_parse_match(item.get("match"), f"{name}.match"),
                fields=fields,
                enabled=_boolean(item.get("enabled"), f"{name}.enabled", True),
                notifier_ids=targets,
                notification_title=_string(
                    item.get("notification_title"), f"{name}.notification_title", default="New email"
                ),
                reply_enabled=_boolean(item.get("reply_enabled"), f"{name}.reply_enabled", True),
                reply_language=_string(
                    item.get("reply_language"),
                    f"{name}.reply_language",
                    default=app.default_reply_language,
                ),
                reply_subject_seed=reply_subject_seed,
                reply_body_seed=reply_body_seed,
            )
        )

    if not accounts:
        _fail("at least one [[accounts]] entry is required")
    if not rules:
        _fail("at least one [[rules]] entry is required")
    return AppConfig(
        source_path=source_path,
        app=app,
        accounts=tuple(accounts),
        notifiers=tuple(notifiers),
        rules=tuple(rules),
        interaction=interaction,
        bots=tuple(bots),
    )
