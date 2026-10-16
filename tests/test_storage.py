from __future__ import annotations

import unittest
import time
from pathlib import Path

from tests.support import fixture, workspace_tempdir

from mail_to_workchat.mail import parse_email_bytes
from mail_to_workchat.models import DeliveryOutcome, Notification
from mail_to_workchat.storage.database import Database
from mail_to_workchat.storage.outbox import OutboxDispatcher


class FakeNotifier:
    def __init__(self, notifier_id: str, success: bool):
        self.id = notifier_id
        self.success = success
        self.calls = 0

    def send(self, notification):  # noqa: ANN001
        self.calls += 1
        return DeliveryOutcome(self.success, "synthetic failure" if not self.success else "sent")


class StorageTests(unittest.TestCase):
    def setUp(self):
        temporary = workspace_tempdir()
        self.addCleanup(temporary.cleanup)
        self.database = Database(Path(temporary.name) / "state.sqlite3")
        self.message = parse_email_bytes(
            fixture().read_bytes(),
            account_id="test-mailbox",
            account_label="Test mailbox",
            folder="INBOX",
            uid=10,
            uid_validity="1",
        )
        self.notification = Notification(
            event_key=f"mail:{self.message.message_key}",
            title="Synthetic notice",
            text="Synthetic body",
            message_key=self.message.message_key,
        )

    def test_message_and_outbox_are_idempotent(self):
        first = self.database.record_message(
            self.message,
            rule_id="rule-one",
            status="matched",
            notification=self.notification,
            notifier_ids=("chat",),
        )
        second = self.database.record_message(
            self.message,
            rule_id="rule-one",
            status="matched",
            notification=self.notification,
            notifier_ids=("chat",),
        )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(self.database.ready_jobs()), 1)

    def test_successful_delivery_is_marked_sent(self):
        self.database.record_message(
            self.message,
            rule_id="rule-one",
            status="matched",
            notification=self.notification,
            notifier_ids=("chat",),
        )
        notifier = FakeNotifier("chat", True)
        result = OutboxDispatcher(self.database, {"chat": notifier}, max_attempts=3).flush()
        self.assertEqual(result.sent, 1)
        self.assertEqual(self.database.outbox_counts()["sent"], 1)
        self.assertEqual(notifier.calls, 1)

    def test_failed_delivery_reaches_dead_letter_limit(self):
        self.database.record_message(
            self.message,
            rule_id="rule-one",
            status="matched",
            notification=self.notification,
            notifier_ids=("chat",),
        )
        result = OutboxDispatcher(
            self.database,
            {"chat": FakeNotifier("chat", False)},
            max_attempts=1,
        ).flush()
        self.assertEqual(result.dead_lettered, 1)
        self.assertEqual(self.database.outbox_counts()["dead_letter"], 1)

        listed = self.database.list_outbox("dead_letter")
        self.assertEqual(len(listed), 1)
        self.assertNotIn("Synthetic body", listed[0].last_error)
        self.assertTrue(self.database.retry_dead_letter(listed[0].id))
        self.assertEqual(self.database.outbox_counts()["pending"], 1)
        self.assertFalse(self.database.retry_dead_letter(listed[0].id))

    def test_checkpoint_round_trip(self):
        self.database.set_checkpoint("test-mailbox", "INBOX", "123", 45)
        checkpoint = self.database.get_checkpoint("test-mailbox", "INBOX")
        self.assertEqual((checkpoint.uid_validity, checkpoint.last_uid), ("123", 45))

    def test_claim_lease_prevents_two_dispatchers_from_taking_same_job(self):
        self.database.record_message(
            self.message,
            rule_id="rule-one",
            status="matched",
            notification=self.notification,
            notifier_ids=("chat",),
        )
        baseline = time.time() + 1.0
        first = self.database.claim_ready_jobs(now=baseline, lease_seconds=60.0)
        second = self.database.claim_ready_jobs(now=baseline, lease_seconds=60.0)
        recovered = self.database.claim_ready_jobs(now=baseline + 61.0, lease_seconds=60.0)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, ())
        self.assertEqual(len(recovered), 1)


if __name__ == "__main__":
    unittest.main()
