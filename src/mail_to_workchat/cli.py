from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from .app import Application
from .config import ConfigError, load_config
from .interaction.dingtalk import DingTalkConnectorError, run_dingtalk_stream
from .interaction.models import ChatEvent
from .interaction.service import InteractionService
from .security import SecurityError, read_secret, validate_webhook_url
from .templates.repository import TemplateError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mail-to-workchat",
        description="Route standard IMAP email to work-chat webhooks and local reply drafts.",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("MAIL_TO_WORKCHAT_CONFIG", "config/config.toml"),
        help="path to the TOML configuration file",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check-config", help="validate configuration without connecting")
    check.add_argument("--check-secrets", action="store_true", help="also verify referenced secrets exist")

    run = commands.add_parser("run-once", help="poll enabled mailboxes once")
    run.add_argument("--no-send", action="store_true", help="queue notifications but do not call webhooks")
    run.add_argument("--outbox-limit", type=int, default=20)

    continuous = commands.add_parser("run", help="poll continuously until interrupted")
    continuous.add_argument("--interval", type=int, help="seconds between polls")
    continuous.add_argument("--outbox-limit", type=int, default=20)

    preview = commands.add_parser("preview-eml", help="process one local .eml without network calls")
    preview.add_argument("file", type=Path)
    preview.add_argument("--account-id")

    templates = commands.add_parser("templates", help="inspect or approve reply templates")
    template_commands = templates.add_subparsers(dest="template_command", required=True)
    template_commands.add_parser("list", help="list proposals and approved templates")
    approve = template_commands.add_parser("approve", help="approve an edited local proposal")
    approve.add_argument("proposal_id")
    approve.add_argument("--overwrite", action="store_true")

    commands.add_parser("outbox-status", help="show local outbox counts")
    failures = commands.add_parser("mail-failures", help="list quarantined UID metadata, never email bodies")
    failures.add_argument("--limit", type=int, default=20)
    listing = commands.add_parser("outbox-list", help="list delivery metadata without message bodies")
    listing.add_argument("--status", choices=("pending", "sent", "dead_letter", "cancelled"), default="dead_letter")
    listing.add_argument("--limit", type=int, default=20)
    retry = commands.add_parser("outbox-retry", help="move one dead-letter job back to pending")
    retry.add_argument("job_id", type=int)
    flush = commands.add_parser("flush-outbox", help="send ready queued notifications")
    flush.add_argument("--limit", type=int, default=20)

    chat_event = commands.add_parser(
        "chat-event",
        help="process one normalized chat event JSON file (offline adapter test)",
    )
    chat_event.add_argument("file", type=Path)

    bot_run = commands.add_parser("bot-run", help="run an enabled application bot connector")
    bot_run.add_argument("bot_id")

    chat_audit = commands.add_parser("chat-audit", help="show pseudonymized interaction audit rows")
    chat_audit.add_argument("--limit", type=int, default=20)
    return parser


def _check_secrets(config) -> None:  # noqa: ANN001
    for account in config.accounts:
        if account.enabled:
            read_secret(account.password_env)
    for notifier in config.notifiers:
        if not notifier.enabled:
            continue
        url = read_secret(notifier.webhook_env)
        validate_webhook_url(url, allowed_hosts=notifier.allowed_hosts, provider=notifier.kind)
        if notifier.secret_env:
            read_secret(notifier.secret_env)
    if config.interaction.enabled:
        for bot in config.bots:
            if bot.enabled:
                read_secret(bot.app_id_env)
                read_secret(bot.app_secret_env)


def _print_report(report) -> None:  # noqa: ANN001
    print(
        "run complete: "
        f"baselined={len(report.baselined_accounts)} "
        f"scanned={report.scanned_messages} matched={report.matched_messages} "
        f"ignored={report.ignored_messages} duplicates={report.duplicate_messages} "
        f"quarantined={report.quarantined_messages} "
        f"sent={report.delivery.sent} retried={report.delivery.retried} "
        f"dead_lettered={report.delivery.dead_lettered} errors={len(report.errors)}"
    )
    for error in report.errors:
        print(f"error: {error}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "check-config":
            if args.check_secrets:
                _check_secrets(config)
            print(
                f"configuration ok: {len(config.accounts)} account(s), "
                f"{len(config.rules)} rule(s), {len(config.notifiers)} notifier(s), "
                f"{len(config.bots)} bot connector(s)"
            )
            return 0

        application = Application(config)
        if args.command == "run-once":
            if args.outbox_limit <= 0:
                raise ValueError("--outbox-limit must be positive")
            report = application.run_once(send=not args.no_send, outbox_limit=args.outbox_limit)
            _print_report(report)
            return 1 if report.errors else 0

        if args.command == "run":
            interval = args.interval or config.app.poll_interval_seconds
            if interval <= 0 or args.outbox_limit <= 0:
                raise ValueError("interval and outbox limit must be positive")
            try:
                while True:
                    _print_report(application.run_once(send=True, outbox_limit=args.outbox_limit))
                    time.sleep(interval)
            except KeyboardInterrupt:
                print("stopped")
                return 0

        if args.command == "preview-eml":
            result = application.preview_eml(args.file.resolve(), account_id=args.account_id)
            if not result.matched:
                print("no rule matched")
                return 2
            print(f"matched rule: {result.rule_id}")
            print(f"draft status: {result.draft_status or 'disabled'}")
            if result.proposal_path:
                print(f"proposal: {result.proposal_path}")
            if result.draft:
                print(f"draft: {result.draft.path}")
            if result.error:
                print(f"blocked: {result.error}")
                return 2
            return 0

        if args.command == "templates":
            if args.template_command == "list":
                proposals = application.templates.list_proposals()
                approved = application.templates.load_approved()
                print("proposals:")
                for template in proposals:
                    print(f"  {template.id} ({template.language})")
                print("approved:")
                for template in approved:
                    print(f"  {template.id} ({template.language})")
                return 0
            target = application.templates.approve(args.proposal_id, overwrite=args.overwrite)
            print(f"approved template: {target}")
            refreshed, blocked = application.refresh_pending_drafts(args.proposal_id)
            print(f"existing drafts: refreshed={refreshed} require_local_review={blocked}")
            return 0

        if args.command == "mail-failures":
            for item in application.database.list_inbound_failures(args.limit):
                print(
                    f"account={item['account_id']} folder={item['folder']} "
                    f"uid_validity={item['uid_validity']} uid={item['uid']} reason={item['reason']}"
                )
            return 0

        if args.command == "outbox-status":
            counts = application.database.outbox_counts()
            print(" ".join(f"{key}={value}" for key, value in sorted(counts.items())))
            return 0

        if args.command == "outbox-list":
            if args.limit <= 0:
                raise ValueError("--limit must be positive")
            for item in application.database.list_outbox(args.status, args.limit):
                print(
                    f"id={item.id} notifier={item.notifier_id} status={item.status} "
                    f"attempts={item.attempts} error={item.last_error or '-'}"
                )
            return 0

        if args.command == "outbox-retry":
            if args.job_id <= 0:
                raise ValueError("job_id must be positive")
            if not application.database.retry_dead_letter(args.job_id):
                raise ValueError("dead-letter job was not found")
            print(f"job {args.job_id} moved to pending; run flush-outbox to send it")
            return 0

        if args.command == "flush-outbox":
            if args.limit <= 0:
                raise ValueError("--limit must be positive")
            result = application.dispatcher.flush(args.limit)
            print(
                f"sent={result.sent} retried={result.retried} dead_lettered={result.dead_lettered}"
            )
            return 0

        if args.command == "chat-event":
            path = args.file.resolve()
            if path.stat().st_size > 65_536:
                raise ValueError("chat event file is too large")
            try:
                raw_event = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"chat event is not valid JSON: {exc}") from exc
            event = ChatEvent.from_dict(raw_event)
            response = InteractionService(
                config,
                application.database,
                application.templates,
            ).handle(event)
            print(response.text)
            return 0 if response.outcome in {"ok", "duplicate"} else 2

        if args.command == "bot-run":
            if not config.interaction.enabled:
                raise ValueError("interaction mode is not enabled")
            bot = next((item for item in config.bots if item.id == args.bot_id), None)
            if bot is None or not bot.enabled:
                raise ValueError(f"enabled bot was not found: {args.bot_id}")
            if bot.platform != "dingtalk":
                raise ValueError(f"unsupported bot platform: {bot.platform}")
            service = InteractionService(config, application.database, application.templates)
            run_dingtalk_stream(bot, service)
            return 0

        if args.command == "chat-audit":
            if args.limit <= 0:
                raise ValueError("--limit must be positive")
            for item in application.database.list_interaction_audit(args.limit):
                event_hash = hashlib.sha256(item.event_id.encode("utf-8")).hexdigest()[:12]
                print(
                    f"time={int(item.created_at)} event={event_hash} bot={item.bot_id} "
                    f"actor={item.user_hash[-8:]} command={item.command} "
                    f"target={item.target or '-'} outcome={item.outcome}"
                )
            return 0
        return 2
    except (
        ConfigError,
        DingTalkConnectorError,
        SecurityError,
        TemplateError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
