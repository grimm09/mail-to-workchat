from __future__ import annotations

import unittest

from tests.support import fixture

from mail_to_workchat.mail import parse_email_bytes
from mail_to_workchat.models import FieldSpec, MatchSpec, RuleConfig
from mail_to_workchat.processors.rules import build_notification, first_matching_rule


class MailAndRuleTests(unittest.TestCase):
    def _message(self, uid: int = 10):
        return parse_email_bytes(
            fixture().read_bytes(),
            account_id="test-mailbox",
            account_label="Test mailbox",
            folder="INBOX",
            uid=uid,
            uid_validity="777",
        )

    def _rule(self):
        return RuleConfig(
            id="action-required",
            name="Action required",
            match=MatchSpec(sender_regex=r"alerts@example\.com", subject_regex="action required", body_regex="case id"),
            fields={"case_id": FieldSpec("body", r"(?im)^case id\s*:\s*(?P<value>[A-Z0-9-]+)", True)},
        )

    def test_parser_extracts_plain_text_and_headers(self):
        message = self._message()
        self.assertEqual(message.sender_email, "alerts@example.com")
        self.assertIn("EX-1001", message.body)
        self.assertEqual(message.subject, "[Action Required] Review case EX-1001")

    def test_message_id_key_is_stable_when_uid_changes(self):
        self.assertEqual(self._message(10).message_key, self._message(999).message_key)

    def test_rule_extracts_named_value(self):
        match = first_matching_rule((self._rule(),), self._message())
        self.assertIsNotNone(match)
        self.assertEqual(match.values["case_id"], "EX-1001")
        self.assertEqual(match.missing_required, ())

    def test_notification_is_bounded_and_escapes_markdown(self):
        message = self._message()
        match = first_matching_rule((self._rule(),), message)
        notification = build_notification(message, match, snippet_chars=35, draft_status="ready")
        self.assertIn("Reply draft: `ready`", notification.text)
        self.assertLess(len(notification.text), 900)
        self.assertNotIn("Please review the supplied information before the deadline", notification.text)


if __name__ == "__main__":
    unittest.main()
