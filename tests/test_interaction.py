from __future__ import annotations

import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.support import config_text, fixture, workspace_tempdir

from mail_to_workchat.app import Application
from mail_to_workchat.config import load_config
from mail_to_workchat.interaction.models import ChatEvent
from mail_to_workchat.interaction.service import InteractionService
from mail_to_workchat.mail import parse_email_bytes


def interaction_config() -> str:
    return config_text() + '''

[interaction]
enabled = true
event_ttl_seconds = 600
response_chars = 3500
template_confirmation_required = true

[[bots]]
id = "personal-bot"
platform = "dingtalk"
app_id_env = "TEST_DINGTALK_APP_ID"
app_secret_env = "TEST_DINGTALK_APP_SECRET"
allowed_chat_ids = ["chat-example"]
allowed_user_ids = ["admin-example", "viewer-example"]
admin_user_ids = ["admin-example"]
enabled = true
require_mention = true
'''


class InteractionTests(unittest.TestCase):
    def setUp(self):
        temporary = workspace_tempdir()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        config_path = self.root / "config.toml"
        config_path.write_text(interaction_config(), encoding="utf-8")
        self.config = load_config(config_path)
        self.application = Application(self.config)
        self.message = parse_email_bytes(
            fixture().read_bytes(),
            account_id="test-mailbox",
            account_label="Test mailbox",
            folder="INBOX",
            uid=33,
            uid_validity="900",
        )
        first = self.application.preview(self.message)
        self.application.templates.approve(first.rule_id)
        preview, inserted = self.application.process_message(self.message)
        self.assertTrue(inserted)
        self.assertEqual(preview.draft_status, "ready")
        self.case_ref = f"m-{self.message.message_key[:12]}"
        self.service = InteractionService(
            self.config,
            self.application.database,
            self.application.templates,
        )

    def event(
        self,
        text: str,
        *,
        event_id: str,
        user_id: str = "admin-example",
        chat_id: str = "chat-example",
        occurred_at: datetime | None = None,
        mentioned_bot: bool = True,
    ) -> ChatEvent:
        return ChatEvent(
            event_id=event_id,
            bot_id="personal-bot",
            platform="dingtalk",
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            is_group=True,
            mentioned_bot=mentioned_bot,
        )

    def test_query_and_reply_show_local_case_and_draft(self):
        query = self.service.handle(self.event(f"查询 {self.case_ref}", event_id="evt-query"))
        self.assertEqual(query.outcome, "ok")
        self.assertIn(self.case_ref, query.text)
        self.assertIn("EX-1001", query.text)

        reply = self.service.handle(self.event(f"回复 {self.case_ref}", event_id="evt-reply"))
        self.assertEqual(reply.outcome, "ok")
        self.assertIn("仅供人工复制", reply.text)
        self.assertIn("EX-1001", reply.text)

    def test_non_admin_cannot_ignore_and_admin_action_is_idempotent(self):
        denied = self.service.handle(
            self.event(
                f"忽略 {self.case_ref}",
                event_id="evt-viewer-ignore",
                user_id="viewer-example",
            )
        )
        self.assertEqual(denied.outcome, "denied")
        self.assertEqual(self.application.database.find_case(self.case_ref).status, "open")

        event = self.event(f"忽略 {self.case_ref}", event_id="evt-admin-ignore")
        accepted = self.service.handle(event)
        duplicate = self.service.handle(event)
        self.assertEqual(accepted.outcome, "ok")
        self.assertEqual(duplicate.outcome, "duplicate")
        self.assertEqual(accepted.text, duplicate.text)
        self.assertEqual(self.application.database.find_case(self.case_ref).status, "ignored")

    def test_allowlist_mention_and_freshness_are_enforced(self):
        wrong_chat = self.service.handle(
            self.event("查询", event_id="evt-wrong-chat", chat_id="chat-blocked")
        )
        no_mention = self.service.handle(
            self.event("查询", event_id="evt-no-mention", mentioned_bot=False)
        )
        stale = self.service.handle(
            self.event(
                "查询",
                event_id="evt-stale",
                occurred_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        self.assertEqual(wrong_chat.outcome, "denied")
        self.assertEqual(no_mention.outcome, "denied")
        self.assertEqual(stale.outcome, "denied")
        self.assertNotIn(b"chat-blocked", self.application.database.path.read_bytes())

    def test_template_update_requires_confirmation_and_can_roll_back(self):
        original = self.application.templates.load_approved_by_id("action-required")
        update = self.service.handle(
            self.event(
                "模板更新 action-required\n"
                "主题: Re: {subject}\n"
                "正文:\n"
                "안녕하세요.\n\n요청 {case_id}의 새 승인 초안입니다.\n\n감사합니다.",
                event_id="evt-template-update",
            )
        )
        self.assertEqual(update.outcome, "ok")
        change_id = re.search(r"c-[0-9a-f]{12}", update.text).group(0)
        before_confirm = self.application.templates.load_approved_by_id("action-required")
        self.assertEqual(before_confirm.reply_body, original.reply_body)

        confirmed = self.service.handle(
            self.event(f"模板确认 {change_id}", event_id="evt-template-confirm")
        )
        self.assertEqual(confirmed.outcome, "ok")
        self.assertIn("v2", confirmed.text)
        changed = self.application.templates.load_approved_by_id("action-required")
        self.assertIn("새 승인 초안", changed.reply_body)

        rollback = self.service.handle(
            self.event("模板回滚 action-required 1", event_id="evt-template-rollback")
        )
        rollback_id = re.search(r"c-[0-9a-f]{12}", rollback.text).group(0)
        self.service.handle(
            self.event(f"模板确认 {rollback_id}", event_id="evt-template-rollback-confirm")
        )
        restored = self.application.templates.load_approved_by_id("action-required")
        self.assertEqual(restored.reply_body, original.reply_body)

    def test_template_placeholder_validation_blocks_bad_update(self):
        response = self.service.handle(
            self.event(
                "模板更新 action-required\n正文:\n{unknown_value}",
                event_id="evt-invalid-template",
            )
        )
        self.assertEqual(response.outcome, "rejected")
        self.assertIn("unknown placeholders", response.text)

    def test_audit_rows_do_not_store_raw_user_or_chat_ids(self):
        self.service.handle(self.event("查询", event_id="evt-audit"))
        audit = self.application.database.list_interaction_audit()
        self.assertEqual(audit[0].command, "query")
        self.assertTrue(audit[0].user_hash.startswith("sha256:"))
        database_bytes = self.application.database.path.read_bytes()
        self.assertNotIn(b"admin-example", database_bytes)
        self.assertNotIn(b"chat-example", database_bytes)


if __name__ == "__main__":
    unittest.main()
