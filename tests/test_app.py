from __future__ import annotations

import unittest
from pathlib import Path

from tests.support import config_text, fixture, workspace_tempdir

from mail_to_workchat.app import Application
from mail_to_workchat.config import load_config
from mail_to_workchat.mail import parse_email_bytes
from mail_to_workchat.models import ScanBatch


class FakeSource:
    def __init__(self, batch):  # noqa: ANN001
        self.batch = batch
        self.checkpoints = []

    def scan(self, account, checkpoint):  # noqa: ANN001
        self.checkpoints.append(checkpoint)
        return self.batch


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        temporary = workspace_tempdir()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        path = self.root / "config.toml"
        path.write_text(config_text(), encoding="utf-8")
        self.config = load_config(path)
        self.message = parse_email_bytes(
            fixture().read_bytes(),
            account_id="test-mailbox",
            account_label="Test mailbox",
            folder="INBOX",
            uid=20,
            uid_validity="900",
        )

    def test_run_once_records_message_and_checkpoint_without_network(self):
        batch = ScanBatch(
            account_id="test-mailbox",
            folder="INBOX",
            uid_validity="900",
            messages=(self.message,),
            final_uid=20,
        )
        app = Application(self.config, source=FakeSource(batch))
        report = app.run_once(send=False)
        self.assertEqual(report.matched_messages, 1)
        self.assertEqual(app.database.processed_count(), 1)
        self.assertEqual(app.database.get_checkpoint("test-mailbox", "INBOX").last_uid, 20)

    def test_duplicate_message_is_not_queued_twice(self):
        batch = ScanBatch(
            account_id="test-mailbox",
            folder="INBOX",
            uid_validity="900",
            messages=(self.message,),
            final_uid=20,
        )
        source = FakeSource(batch)
        app = Application(self.config, source=source)
        app.run_once(send=False)
        report = app.run_once(send=False)
        self.assertEqual(report.duplicate_messages, 1)
        self.assertEqual(app.database.processed_count(), 1)

    def test_baseline_batch_does_not_process_messages(self):
        batch = ScanBatch(
            account_id="test-mailbox",
            folder="INBOX",
            uid_validity="900",
            messages=(),
            final_uid=500,
            baseline_only=True,
        )
        app = Application(self.config, source=FakeSource(batch))
        report = app.run_once(send=False)
        self.assertEqual(report.baselined_accounts, ["test-mailbox"])
        self.assertEqual(app.database.processed_count(), 0)


if __name__ == "__main__":
    unittest.main()
