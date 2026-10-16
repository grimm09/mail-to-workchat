from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tests import test_app as app_fixture, test_interaction as interaction_fixture
from tests.test_imap import FakeImap
from tests.support import PROJECT_ROOT, fixture
from mail_to_workchat.app import Application
from mail_to_workchat.config import ConfigError, load_config
from mail_to_workchat.interaction.models import ChatEvent, ChatEventError
from mail_to_workchat.interaction.service import InteractionService
from mail_to_workchat.mail import MailParseError, parse_email_bytes
from mail_to_workchat.models import NotifierConfig
from mail_to_workchat.notifiers.webhook import provider_success
from mail_to_workchat.security import sanitize_error
from mail_to_workchat.sources.imap import ImapSource
from mail_to_workchat.storage.database import Database
from mail_to_workchat.templates.engine import render_template
from mail_to_workchat.templates.repository import TemplateError, validate_template


def deep_mime(depth=1100):
    lines = ["From: alerts@example.com", "Subject: Action Required", "Message-ID: <deep@example.com>"]
    for index in range(depth):
        lines += [f'Content-Type: multipart/mixed; boundary="b{index}"', "", f"--b{index}"]
    lines += ["Content-Type: text/plain", "", "Case ID: EX-1001"]
    lines += [f"--b{index}--" for index in reversed(range(depth))]
    return ("\r\n".join(lines) + "\r\n").encode()


class SecurityRegressionTests(unittest.TestCase):
    def prepare(self, cls=interaction_fixture.InteractionTests):
        test = cls()
        self.addCleanup(test.doCleanups)
        test.setUp()
        return test

    def propose(self, test, body, event_id):
        response = test.service.handle(test.event(f"模板更新 action-required\n正文:\n{body}", event_id=event_id))
        self.assertEqual(response.outcome, "ok", response.text)
        return re.search(r"c-[0-9a-f]{12}", response.text).group()

    def test_duplicate_and_preview_cannot_change_referenced_draft(self):
        test = self.prepare()
        original = test.application.database.find_case(test.case_ref)
        original_bytes = Path(original.draft_path).read_bytes()
        raw = fixture().read_bytes().replace(b"EX-1001", b"EX-9999")
        changed = parse_email_bytes(raw, account_id=test.message.account_id, account_label="Test mailbox", folder="INBOX", uid=34, uid_validity="900")
        _, inserted = test.application.process_message(changed)
        self.assertFalse(inserted)
        test.application.preview(changed)
        self.assertEqual(Path(original.draft_path).read_bytes(), original_bytes)
        reply = test.service.handle(test.event("回复 " + test.case_ref, event_id="safe-duplicate"))
        self.assertIn("EX-1001", reply.text)
        self.assertNotIn("EX-9999", reply.text)

    def test_first_case_can_be_refreshed_after_approval(self):
        test = self.prepare(app_fixture.ApplicationTests)
        app = Application(test.config)
        preview, _ = app.process_message(test.message)
        app.templates.approve(preview.rule_id)
        self.assertEqual(app.refresh_pending_drafts(preview.rule_id), (1, 0))
        case = app.database.find_case(test.message.message_key)
        self.assertEqual(case.draft_status, "ready")
        self.assertIn("EX-1001", Path(case.draft_path).read_text(encoding="utf-8"))

    def test_refresh_does_not_guess_fields_after_contract_change(self):
        test = self.prepare(app_fixture.ApplicationTests)
        app = Application(test.config)
        preview, _ = app.process_message(test.message)
        app.templates.approve(preview.rule_id)
        approved = app.templates.load_approved_by_id(preview.rule_id)
        app.templates.replace_approved(replace(approved, match=replace(approved.match, body_regex="changed")))
        self.assertEqual(app.refresh_pending_drafts(preview.rule_id), (0, 1))
        self.assertEqual(app.database.find_case(test.message.message_key).draft_status, "needs_review")

    def test_deep_mime_quarantines_one_uid_and_advances_past_it(self):
        test = self.prepare(app_fixture.ApplicationTests)
        raw = deep_mime()
        class PoisonImap(FakeImap):
            def uid(self, command, *args):
                if command == "fetch" and int(args[0]) == 2:
                    return "OK", [(b"2 (BODY[])", raw), b")"]
                result = super().uid(command, *args)
                if command == "fetch" and int(args[0]) == 3:
                    return "OK", [(b"3 (BODY[])", self.raw.replace(b"Message-ID: <", b"Message-ID: <third-")), b")"]
                return result
        fake = PoisonImap((1, 2, 3))
        app = Application(test.config, source=ImapSource(initial_sync="process_existing", client_factory=lambda account: fake))
        with patch.dict(os.environ, {"TEST_MAILBOX_PASSWORD": "synthetic"}):
            report = app.run_once(send=False)
            again = app.run_once(send=False)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.quarantined_messages, 1)
        self.assertEqual(app.database.get_checkpoint("test-mailbox", "INBOX").last_uid, 3)
        self.assertEqual(app.database.processed_count(), 2)
        self.assertEqual(again.scanned_messages, 0)
        self.assertEqual(len(app.database.list_inbound_failures()), 1)
        self.assertNotIn("Case ID", str(app.database.list_inbound_failures()))

    def test_size_capped_mime_is_not_parsed_as_a_complete_message(self):
        test = self.prepare(app_fixture.ApplicationTests)
        account = replace(test.config.accounts[0], max_message_bytes=128)
        source = ImapSource(initial_sync="process_existing", client_factory=lambda account: FakeImap((1,)))
        with patch.dict(os.environ, {"TEST_MAILBOX_PASSWORD": "synthetic"}):
            batch = source.scan(account, None)
        self.assertEqual(batch.messages, ())
        self.assertEqual(batch.failures[0].reason, "message_size_limit")

    def test_malformed_html_completes_with_a_bounded_child_process(self):
        command = "import sys;sys.path.insert(0,'src');from mail_to_workchat.mail import _html_to_text;assert len(_html_to_text('<'*200000))==200000"
        subprocess.run([sys.executable, "-B", "-c", command], cwd=PROJECT_ROOT, check=True, timeout=8, capture_output=True)

    def test_long_whitespace_body_completes_with_a_bounded_child_process(self):
        command = (
            "import sys;sys.path.insert(0,'src');"
            "from email.message import Message;from mail_to_workchat.mail import message_body;"
            "m=Message();m.set_payload('A'+' '*200000+'B');assert len(message_body(m))==200002"
        )
        subprocess.run([sys.executable, "-B", "-c", command], cwd=PROJECT_ROOT, check=True, timeout=8, capture_output=True)

    def test_transient_imap_failure_does_not_quarantine_or_advance_checkpoint(self):
        test = self.prepare(app_fixture.ApplicationTests)
        class BrokenImap(FakeImap):
            def uid(self, command, *args):
                if command == "fetch" and int(args[0]) == 2:
                    raise OSError("synthetic private server detail")
                return super().uid(command, *args)
        app = Application(test.config, source=ImapSource(initial_sync="process_existing", client_factory=lambda account: BrokenImap((1, 2))))
        app.database.set_checkpoint("test-mailbox", "INBOX", "777", 0)
        with patch.dict(os.environ, {"TEST_MAILBOX_PASSWORD": "synthetic"}):
            report = app.run_once(send=False)
        self.assertEqual(len(report.errors), 1)
        self.assertNotIn("private server", report.errors[0])
        self.assertEqual(app.database.get_checkpoint("test-mailbox", "INBOX").last_uid, 0)
        self.assertEqual(app.database.list_inbound_failures(), ())

    def test_large_draft_is_refused_instead_of_returning_truncated_reply(self):
        test = self.prepare()
        case = test.application.database.find_case(test.case_ref)
        with patch.object(Path, "open", unittest.mock.mock_open(read_data="x" * 5000)):
            response = test.service.handle(test.event("回复 " + case.case_ref, event_id="large-draft"))
        self.assertEqual(response.outcome, "rejected")
        self.assertNotIn("xxx", response.text)

    def test_untrusted_mime_exception_has_no_message_body(self):
        with self.assertRaises(MailParseError) as caught:
            parse_email_bytes(deep_mime(), account_id="test", account_label="test", folder="INBOX", uid=1, uid_validity="1")
        self.assertIn(str(caught.exception), {"invalid_mime", "mime_structure_limit"})

    def test_rejected_identity_never_gets_cached_draft(self):
        test = self.prepare()
        event = test.event("回复 " + test.case_ref, event_id="private-cache")
        good = test.service.handle(event)
        denied = test.service.handle(replace(event, user_id="blocked", chat_id="blocked"))
        self.assertEqual(denied.outcome, "denied")
        self.assertNotIn("EX-1001", denied.text)
        self.assertNotEqual(good.text, denied.text)

    def test_allowed_viewer_cannot_reuse_admin_event_cache(self):
        test = self.prepare()
        event = test.event("查询 " + test.case_ref, event_id="bound-cache")
        test.service.handle(event)
        self.assertEqual(test.service.handle(replace(event, user_id="viewer-example")).outcome, "denied")
        self.assertEqual(test.service.handle(replace(event, text="回复 " + test.case_ref)).outcome, "denied")

    def test_removed_admin_role_is_checked_before_replay(self):
        test = self.prepare()
        event = test.event("忽略 " + test.case_ref, event_id="role-revoked")
        test.service.handle(event)
        config = replace(test.config, bots=(replace(test.config.bots[0], admin_user_ids=("viewer-example",)),))
        service = InteractionService(config, test.application.database, test.application.templates)
        self.assertEqual(service.handle(event).outcome, "denied")

    def test_interrupted_event_can_be_reclaimed_after_lease(self):
        test = self.prepare()
        event = test.event("忽略 " + test.case_ref, event_id="lease-recovery")
        test.service._reserve(event, "ignore", test.case_ref)
        self.assertEqual(test.service.handle(event).outcome, "retry")
        future = time.time() + 61
        with patch("mail_to_workchat.storage.database.time.time", return_value=future):
            response = test.service.handle(event)
        self.assertEqual(response.outcome, "ok", response.text)
        self.assertEqual(test.application.database.find_case(test.case_ref).status, "ignored")

    def test_event_boolean_is_strict_and_missing_mention_fails_closed(self):
        test = self.prepare()
        raw = {"event_id": "bool", "bot_id": "personal-bot", "platform": "dingtalk", "chat_id": "chat-example", "user_id": "admin-example", "text": "查询", "occurred_at": test.message.received_at.isoformat()}
        self.assertFalse(ChatEvent.from_dict(raw).mentioned_bot)
        for key in ("mentioned_bot", "is_group"):
            with self.assertRaises(ChatEventError):
                ChatEvent.from_dict({**raw, key: "false"})

    def test_config_string_boolean_does_not_enable_interaction(self):
        test = self.prepare()
        raw = test.config.source_path.read_text(encoding="utf-8").replace("[interaction]\nenabled = true", '[interaction]\nenabled = "false"')
        with patch.object(Path, "read_text", return_value=raw), self.assertRaises(ConfigError):
            load_config(test.config.source_path)

    def test_extreme_timestamps_are_validation_errors_not_transient_failures(self):
        raw = {"event_id": "timestamp", "bot_id": "personal-bot", "platform": "dingtalk", "chat_id": "chat-example", "user_id": "admin-example", "text": "查询"}
        for value in (10 ** 400, "9" * 5000, float("nan"), float("inf"), "9999-12-31T23:59:59-01:00"):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ChatEventError):
                ChatEvent.from_dict({**raw, "occurred_at": value})

    def test_template_format_expansions_are_rejected(self):
        test = self.prepare()
        template = test.application.templates.load_approved_by_id("action-required")
        for text in ("{case_id:>2000000}", "{subject:{unknown}}", "{subject!r}", "{}", "{subject.__class__}"):
            with self.subTest(text=text), self.assertRaises(TemplateError):
                validate_template(replace(template, reply_body=text))

    def test_render_size_is_checked_before_allocating_expansion(self):
        test = self.prepare()
        template = test.application.templates.load_approved_by_id("action-required")
        with self.assertRaises(TemplateError):
            render_template(replace(template, reply_body="{subject}" * 100), replace(test.message, subject="x" * 2000))

    def test_empty_or_malformed_provider_status_is_not_success(self):
        for provider, key in (("dingtalk", "errcode"), ("feishu", "code")):
            for value in (None, False, True, [], {}, "bad"):
                self.assertFalse(provider_success({key: value}, provider).success)
            self.assertFalse(provider_success({}, provider).success)
            self.assertTrue(provider_success({key: 0}, provider).success)

    def test_multiline_mutation_is_not_silently_executed(self):
        test = self.prepare()
        response = test.service.handle(test.event("忽略 " + test.case_ref + "\n请不要执行", event_id="multiline"))
        self.assertEqual(response.outcome, "invalid")
        self.assertEqual(test.application.database.find_case(test.case_ref).status, "open")

    def test_parallel_template_confirmation_rejects_stale_proposal(self):
        test = self.prepare()
        ids = [self.propose(test, name + " {case_id}", "parallel-" + name) for name in ("A", "B")]
        barrier = threading.Barrier(2)
        def apply(change_id):
            barrier.wait(timeout=5)
            try:
                test.service.template_manager.apply(change_id, actor_hash="synthetic")
                return "applied"
            except TemplateError:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(apply, ids))
        self.assertCountEqual(results, ["applied", "conflict"])

    def test_template_write_recovers_after_interruption(self):
        test = self.prepare()
        change_id = self.propose(test, "UPDATED {case_id}", "interrupted-change")
        database = test.application.database
        record = database.record_template_revision
        def interrupted(**kwargs):
            if kwargs["reason"].startswith("applied"):
                raise SystemExit("synthetic interruption")
            return record(**kwargs)
        with patch.object(database, "record_template_revision", side_effect=interrupted), self.assertRaises(SystemExit):
            test.service.template_manager.apply(change_id, actor_hash="synthetic")
        self.assertEqual(database.get_template_change(change_id).status, "applying")
        revision = test.service.template_manager.apply(change_id, actor_hash="synthetic")
        self.assertEqual(revision, 2)
        self.assertEqual(database.get_template_change(change_id).status, "applied")
        self.assertEqual(test.service.template_manager.apply(change_id, actor_hash="synthetic"), revision)

    def test_existing_template_proposal_is_reused_on_event_retry(self):
        test = self.prepare()
        event = test.event("模板更新 action-required\n正文:\nNEW {case_id}", event_id="proposal-retry")
        test.service._reserve(event, "template_update", "action-required")
        first = test.service.template_manager.propose_update("action-required", reply_subject=None, reply_body="NEW {case_id}", actor_hash="synthetic", event_id=event.canonical_id)
        second = test.service.template_manager.propose_update("action-required", reply_subject=None, reply_body="NEW {case_id}", actor_hash="synthetic", event_id=event.canonical_id)
        self.assertEqual(first.change_id, second.change_id)

    def test_oversized_template_diff_is_cancelled_not_truncated(self):
        test = self.prepare()
        response = test.service.handle(test.event("模板更新 action-required\n正文:\n" + "z" * 4000, event_id="large-diff"))
        self.assertEqual(response.outcome, "rejected")
        change = test.application.database.template_change_for_event("dingtalk:personal-bot:large-diff")
        self.assertEqual(change.status, "cancelled")

    def test_ignore_cancels_pending_notification(self):
        test = self.prepare(app_fixture.ApplicationTests)
        notifier = NotifierConfig("sink", "generic", "SYNTHETIC_WEBHOOK", allowed_hosts=("example.com",))
        config = replace(test.config, notifiers=(notifier,), rules=(replace(test.config.rules[0], notifier_ids=("sink",)),))
        app = Application(config)
        app.process_message(test.message)
        database = app.database
        database.reserve_interaction_event(event_id="ignore", bot_id="bot", platform="test", chat_hash="hash", user_hash="hash", command="ignore", target="")
        database.set_case_status(test.message.message_key, status="ignored", event_id="ignore", actor_hash="hash", action="ignore")
        self.assertEqual(database.outbox_counts()["pending"], 0)
        self.assertEqual(database.outbox_counts()["cancelled"], 1)

    def test_case_prefixes_of_supported_lengths_work(self):
        test = self.prepare()
        for length in (8, 12, 16, 24, 32):
            self.assertIsNotNone(test.application.database.find_case(test.message.message_key[:length]))

    def test_schema_upgrade_preserves_existing_records(self):
        test = self.prepare()
        path = test.application.database.path
        with sqlite3.connect(path) as connection:
            for table, column in (("case_records", "sender_name"), ("case_records", "template_context_digest"), ("interaction_events", "request_hash"), ("interaction_events", "lease_until")):
                connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        migrated = Database(path)
        self.assertEqual(migrated.processed_count(), 1)
        self.assertEqual(migrated.find_case(test.case_ref).template_context_digest, "")
        Database(path)

    def test_error_url_redaction_removes_userinfo_and_query(self):
        safe = sanitize_error("https://operator:synthetic-secret@example.com/private?token=synthetic")
        self.assertNotIn("operator", safe)
        self.assertNotIn("synthetic", safe)


if __name__ == "__main__":
    unittest.main()
