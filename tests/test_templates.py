from __future__ import annotations

import unittest
from pathlib import Path

from tests.support import config_text, fixture, workspace_tempdir

from mail_to_workchat.app import Application
from mail_to_workchat.config import load_config
from mail_to_workchat.mail import parse_email_bytes
from mail_to_workchat.models import MatchSpec, TemplateSpec
from mail_to_workchat.templates.engine import render_template, select_template
from mail_to_workchat.templates.repository import TemplateError


class TemplateWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = workspace_tempdir()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        config_path = self.root / "config.toml"
        config_path.write_text(config_text(), encoding="utf-8")
        self.config = load_config(config_path)
        self.application = Application(self.config)

    def _message(self, raw: bytes | None = None):
        return parse_email_bytes(
            raw or fixture().read_bytes(),
            account_id="test-mailbox",
            account_label="Test mailbox",
            folder="INBOX",
            uid=7,
            uid_validity="100",
        )

    def test_first_match_creates_reviewable_proposal_and_draft(self):
        result = self.application.preview(self._message())
        self.assertEqual(result.draft_status, "needs_review")
        self.assertTrue(result.proposal_path.is_file())
        self.assertTrue(result.draft.path.is_file())
        proposal = result.proposal_path.read_text(encoding="utf-8")
        self.assertIn("{case_id}", proposal)
        self.assertNotIn("EX-1001", proposal)
        self.assertIn("EX-1001", result.draft.body)

    def test_approval_changes_future_draft_to_ready(self):
        first = self.application.preview(self._message())
        target = self.application.templates.approve(first.rule_id)
        self.assertTrue(target.is_file())
        second = self.application.preview(self._message())
        self.assertEqual(second.draft_status, "ready")
        self.assertEqual(second.draft.template_id, "action-required")

    def test_missing_required_value_blocks_draft(self):
        raw = fixture().read_text(encoding="utf-8").replace("Case ID: EX-1001", "Case reference unavailable").encode()
        # Keep the body matcher true while making the extractor fail.
        raw = raw.replace(b"Please review", b"Case ID is not yet assigned. Please review")
        result = self.application.preview(self._message(raw))
        self.assertEqual(result.draft_status, "blocked")
        self.assertIn("required fields", result.error)

    def test_multiple_matching_approved_templates_are_rejected(self):
        generic = TemplateSpec(
            id="template-one",
            description="",
            approved=True,
            language="ko",
            match=MatchSpec(),
            fields={},
            reply_subject="Re: {subject}",
            reply_body="ok",
        )
        second = TemplateSpec(
            id="template-two",
            description="",
            approved=True,
            language="ko",
            match=MatchSpec(),
            fields={},
            reply_subject="Re: {subject}",
            reply_body="ok",
        )
        with self.assertRaisesRegex(TemplateError, "multiple"):
            select_template((generic, second), self._message())

    def test_unsafe_placeholder_syntax_is_rejected(self):
        template = TemplateSpec(
            id="unsafe-template",
            description="",
            approved=True,
            language="ko",
            match=MatchSpec(),
            fields={},
            reply_subject="{sender_name.upper}",
            reply_body="ok",
        )
        with self.assertRaisesRegex(TemplateError, "unsafe placeholder"):
            render_template(template, self._message())


if __name__ == "__main__":
    unittest.main()
