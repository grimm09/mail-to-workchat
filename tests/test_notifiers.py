from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from tests.support import PROJECT_ROOT  # noqa: F401 - initializes src path

from mail_to_workchat.models import Notification, NotifierConfig
from mail_to_workchat.notifiers.webhook import WebhookNotifier


class CaptureTransport:
    def __init__(self, response=None):
        self.response = response or {}
        self.calls = []

    def __call__(self, url, payload, timeout):  # noqa: ANN001
        self.calls.append((url, payload, timeout))
        return self.response


def notice() -> Notification:
    return Notification(
        event_key="mail:synthetic",
        title="Synthetic title",
        text="Synthetic text",
        message_key="synthetic",
        metadata={"rule_id": "rule-one"},
    )


class NotifierTests(unittest.TestCase):
    def test_dingtalk_payload_and_signature_are_generated_at_send_time(self):
        transport = CaptureTransport({"errcode": 0})
        config = NotifierConfig(
            id="ding",
            kind="dingtalk",
            webhook_env="TEST_DING_URL",
            secret_env="TEST_DING_SECRET",
            allowed_hosts=("oapi.dingtalk.com",),
        )
        with patch.dict(
            os.environ,
            {
                "TEST_DING_URL": "https://oapi.dingtalk.com/robot/send?access_token=synthetic",
                "TEST_DING_SECRET": "synthetic-signing-secret",
            },
            clear=False,
        ):
            outcome = WebhookNotifier(config, transport=transport, clock=lambda: 1234.5).send(notice())
        self.assertTrue(outcome.success)
        url, payload, timeout = transport.calls[0]
        self.assertIn("timestamp=1234500", url)
        self.assertIn("sign=", url)
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertEqual(payload["markdown"]["title"], "Synthetic title")
        self.assertEqual(timeout, 10.0)

    def test_feishu_uses_interactive_card_shape(self):
        transport = CaptureTransport({"code": 0})
        config = NotifierConfig(
            id="fei",
            kind="feishu",
            webhook_env="TEST_FEI_URL",
            secret_env="TEST_FEI_SECRET",
            allowed_hosts=("open.feishu.cn",),
        )
        with patch.dict(
            os.environ,
            {
                "TEST_FEI_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/synthetic",
                "TEST_FEI_SECRET": "synthetic-signing-secret",
            },
            clear=False,
        ):
            outcome = WebhookNotifier(config, transport=transport, clock=lambda: 1234.5).send(notice())
        self.assertTrue(outcome.success)
        _, payload, _ = transport.calls[0]
        self.assertEqual(payload["msg_type"], "interactive")
        self.assertEqual(payload["card"]["schema"], "2.0")
        self.assertEqual(payload["card"]["body"]["elements"][0]["tag"], "markdown")
        self.assertEqual(payload["timestamp"], "1234")
        self.assertTrue(payload["sign"])

    def test_generic_webhook_shape(self):
        transport = CaptureTransport({})
        config = NotifierConfig(
            id="generic",
            kind="generic",
            webhook_env="TEST_GENERIC_URL",
            allowed_hosts=("hooks.example.com",),
        )
        with patch.dict(
            os.environ,
            {"TEST_GENERIC_URL": "https://hooks.example.com/mail"},
            clear=False,
        ):
            outcome = WebhookNotifier(config, transport=transport).send(notice())
        self.assertTrue(outcome.success)
        _, payload, _ = transport.calls[0]
        self.assertEqual(payload["event"], "mail.notification")
        self.assertEqual(payload["message_key"], "synthetic")

    def test_disallowed_host_never_reaches_transport(self):
        transport = CaptureTransport({})
        config = NotifierConfig(
            id="generic",
            kind="generic",
            webhook_env="TEST_GENERIC_URL",
            allowed_hosts=("hooks.example.com",),
        )
        with patch.dict(
            os.environ,
            {"TEST_GENERIC_URL": "https://untrusted.invalid/collect?access_token=secret-value"},
            clear=False,
        ):
            outcome = WebhookNotifier(config, transport=transport).send(notice())
        self.assertFalse(outcome.success)
        self.assertEqual(transport.calls, [])
        self.assertNotIn("secret-value", outcome.detail)

    def test_provider_rejection_is_reported_without_response_text(self):
        transport = CaptureTransport({"errcode": 310000, "errmsg": "contains provider detail"})
        config = NotifierConfig(
            id="ding",
            kind="dingtalk",
            webhook_env="TEST_DING_URL",
            allowed_hosts=("oapi.dingtalk.com",),
        )
        with patch.dict(
            os.environ,
            {"TEST_DING_URL": "https://oapi.dingtalk.com/robot/send?access_token=synthetic"},
            clear=False,
        ):
            outcome = WebhookNotifier(config, transport=transport).send(notice())
        self.assertFalse(outcome.success)
        self.assertIn("310000", outcome.detail)
        self.assertNotIn("provider detail", outcome.detail)


if __name__ == "__main__":
    unittest.main()
