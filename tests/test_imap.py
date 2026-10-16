from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from tests.support import fixture

from mail_to_workchat.models import Checkpoint, MailAccount
from mail_to_workchat.sources.imap import ImapSource


class FakeImap:
    def __init__(self, uids=(1, 2), validity="777"):
        self.uids = tuple(uids)
        self.validity = validity
        self.calls = []
        self.raw = fixture().read_bytes()

    def login(self, username, password):  # noqa: ANN001
        self.calls.append(("login", username, password))
        return "OK", [b"logged in"]

    def select(self, folder, readonly=False):  # noqa: ANN001
        self.calls.append(("select", folder, readonly))
        return "OK", [str(len(self.uids)).encode()]

    def response(self, name):  # noqa: ANN001
        self.calls.append(("response", name))
        return b"UIDVALIDITY", [self.validity.encode()]

    def uid(self, command, *args):  # noqa: ANN001
        self.calls.append(("uid", command, *args))
        if command == "search":
            return "OK", [" ".join(str(uid) for uid in self.uids).encode()]
        if command == "fetch":
            uid = int(args[0])
            return "OK", [(f"{uid} (BODY[] {{{len(self.raw)}}})".encode(), self.raw), b")"]
        raise AssertionError(command)

    def close(self):
        self.calls.append(("close",))

    def logout(self):
        self.calls.append(("logout",))


class ImapTests(unittest.TestCase):
    def setUp(self):
        self.account = MailAccount(
            id="test-mailbox",
            label="Test mailbox",
            host="imap.example.com",
            port=993,
            username="operator@example.com",
            password_env="TEST_MAILBOX_PASSWORD",
            max_messages_per_run=100,
        )

    def test_first_run_baselines_without_fetching_messages(self):
        fake = FakeImap((4, 8, 12))
        source = ImapSource(initial_sync="baseline", client_factory=lambda account: fake)
        with patch.dict(os.environ, {"TEST_MAILBOX_PASSWORD": "synthetic-password"}, clear=False):
            batch = source.scan(self.account, None)
        self.assertTrue(batch.baseline_only)
        self.assertEqual(batch.final_uid, 12)
        self.assertFalse(any(call[0:2] == ("uid", "fetch") for call in fake.calls))

    def test_incremental_scan_uses_uid_fetch_and_stable_key(self):
        fake = FakeImap((10, 11, 12))
        source = ImapSource(initial_sync="baseline", client_factory=lambda account: fake)
        checkpoint = Checkpoint("test-mailbox", "INBOX", "777", 10)
        with patch.dict(os.environ, {"TEST_MAILBOX_PASSWORD": "synthetic-password"}, clear=False):
            batch = source.scan(self.account, checkpoint)
        self.assertEqual([message.uid for message in batch.messages], [11, 12])
        self.assertEqual(batch.final_uid, 12)
        self.assertEqual(batch.messages[0].message_key, batch.messages[1].message_key)
        fetch_calls = [call for call in fake.calls if call[0:2] == ("uid", "fetch")]
        self.assertEqual([call[2] for call in fetch_calls], ["11", "12"])
        self.assertEqual(fetch_calls[0][3], "(BODY.PEEK[]<0.1048576>)")

    def test_uidvalidity_change_is_safely_rebaselined(self):
        fake = FakeImap((1, 2), validity="new-generation")
        source = ImapSource(initial_sync="baseline", client_factory=lambda account: fake)
        checkpoint = Checkpoint("test-mailbox", "INBOX", "old-generation", 999)
        with patch.dict(os.environ, {"TEST_MAILBOX_PASSWORD": "synthetic-password"}, clear=False):
            batch = source.scan(self.account, checkpoint)
        self.assertTrue(batch.baseline_only)
        self.assertEqual(batch.final_uid, 2)


if __name__ == "__main__":
    unittest.main()
