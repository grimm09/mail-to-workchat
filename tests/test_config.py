from __future__ import annotations

import unittest
from pathlib import Path

from tests.support import PROJECT_ROOT, config_text, workspace_tempdir

from mail_to_workchat.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def _load(self, content: str):
        temporary = workspace_tempdir()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "config.toml"
        path.write_text(content, encoding="utf-8")
        return load_config(path)

    def test_minimal_config_loads_and_resolves_paths(self):
        config = self._load(config_text())
        self.assertEqual(config.accounts[0].id, "test-mailbox")
        self.assertEqual(config.rules[0].fields["case_id"].source, "body")
        self.assertTrue(config.app.data_dir.is_absolute())
        self.assertEqual(config.app.poll_interval_seconds, 300)

    def test_example_config_is_valid(self):
        config = load_config(PROJECT_ROOT / "config" / "config.example.toml")
        self.assertEqual({item.kind for item in config.notifiers}, {"dingtalk", "feishu", "generic"})
        self.assertEqual(config.app.initial_sync, "baseline")

    def test_literal_password_is_rejected(self):
        content = config_text().replace(
            'password_env = "TEST_MAILBOX_PASSWORD"',
            'password_env = "TEST_MAILBOX_PASSWORD"\npassword = "do-not-store-this"',
        )
        with self.assertRaisesRegex(ConfigError, "forbidden"):
            self._load(content)

    def test_generic_webhook_requires_host_allowlist(self):
        notifier = '''
[[notifiers]]
id = "generic-main"
kind = "generic"
webhook_env = "GENERIC_WEBHOOK_URL"
enabled = true
'''
        with self.assertRaisesRegex(ConfigError, "allowed_hosts"):
            self._load(config_text(notifier=notifier))

    def test_enabled_notifier_must_be_explicitly_selected_by_rule(self):
        notifier = '''
[[notifiers]]
id = "chat-main"
kind = "dingtalk"
webhook_env = "TEST_WEBHOOK_URL"
enabled = true
'''
        with self.assertRaisesRegex(ConfigError, "explicitly name"):
            self._load(config_text(notifier=notifier))

    def test_rule_cannot_reference_unknown_notifier(self):
        content = config_text().replace(
            'notification_title = "Action required"',
            'notification_title = "Action required"\nnotifier_ids = ["missing-target"]',
        )
        with self.assertRaisesRegex(ConfigError, "unknown notifiers"):
            self._load(content)

    def test_unknown_key_is_rejected_instead_of_silently_ignored(self):
        content = config_text().replace(
            'host = "imap.example.com"',
            'host = "imap.example.com"\nhots = "typo.example.com"',
        )
        with self.assertRaisesRegex(ConfigError, "unknown keys"):
            self._load(content)

    def test_unknown_reply_placeholder_is_rejected(self):
        content = config_text().replace("{case_id}", "{unconfigured_value}")
        with self.assertRaisesRegex(ConfigError, "unknown placeholders"):
            self._load(content)

    def test_enabled_interaction_requires_an_enabled_bot(self):
        content = config_text() + "\n[interaction]\nenabled = true\n"
        with self.assertRaisesRegex(ConfigError, "enabled.*bot"):
            self._load(content)

    def test_bot_admins_must_be_in_user_allowlist(self):
        content = config_text() + '''

[interaction]
enabled = true

[[bots]]
id = "test-bot"
platform = "dingtalk"
app_id_env = "TEST_APP_ID"
app_secret_env = "TEST_APP_SECRET"
allowed_chat_ids = ["chat-example"]
allowed_user_ids = ["viewer-example"]
admin_user_ids = ["admin-example"]
'''
        with self.assertRaisesRegex(ConfigError, "subset"):
            self._load(content)


if __name__ == "__main__":
    unittest.main()
