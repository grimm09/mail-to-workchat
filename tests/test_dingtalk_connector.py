from __future__ import annotations

import importlib.util
import logging
import os
import socket
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_interaction as interaction_fixture
from mail_to_workchat.interaction import dingtalk as connector
from mail_to_workchat.notifiers.http import WebhookTransportError


def complete_without_io(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    finally:
        coroutine.close()
    raise AssertionError("unexpected asynchronous I/O")


@unittest.skipUnless(importlib.util.find_spec("dingtalk_stream"), "optional DingTalk SDK is not installed")
class DingTalkConnectorTests(unittest.TestCase):
    def setUp(self):
        import dingtalk_stream
        self.sdk = dingtalk_stream
        fixture = interaction_fixture.InteractionTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.fixture = fixture
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("real network is forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        clients = []
        with patch.dict(os.environ, {"TEST_DINGTALK_APP_ID": "synthetic-id", "TEST_DINGTALK_APP_SECRET": "synthetic-secret"}), patch.object(dingtalk_stream.DingTalkStreamClient, "start_forever", lambda client: clients.append(client)):
            connector.run_dingtalk_stream(fixture.config.bots[0], fixture.service)
        self.client = clients[0]
        self.handler = self.client.callback_handler_map[dingtalk_stream.ChatbotMessage.TOPIC]
        self.payload = {
            "msgId": "sdk-event", "senderStaffId": "admin-example", "senderId": "opaque-sender",
            "conversationId": "chat-example", "conversationType": "2", "msgtype": "text",
            "text": {"content": "查询"}, "createAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "isInAtList": True, "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=synthetic",
        }

    def dispatch(self, payload=None):
        return complete_without_io(self.handler.process(SimpleNamespace(
            data=self.payload if payload is None else payload,
            headers=SimpleNamespace(message_id="header-id"),
        )))

    def test_sdk_staff_id_and_bounded_reply_transport(self):
        with patch.object(connector, "post_json", return_value={"errcode": 0}) as post, patch.object(self.sdk.ChatbotHandler, "reply_text", side_effect=AssertionError("unsafe SDK helper used")):
            self.assertEqual(self.dispatch()[0], 200)
        self.assertIn("最近待处理邮件", post.call_args.args[1]["text"]["content"])
        self.assertEqual(post.call_args.args[2], 10.0)

    def test_sdk_message_header_fallback(self):
        payload = dict(self.payload)
        payload.pop("msgId")
        with patch.object(connector, "post_json", return_value={"errcode": 0}):
            self.assertEqual(self.dispatch(payload)[0], 200)

    def test_missing_timestamp_is_rejected_not_replaced_with_now(self):
        payload = dict(self.payload)
        payload.pop("createAt")
        with patch.object(connector, "post_json") as post:
            self.assertEqual(self.dispatch(payload)[0], 400)
        post.assert_not_called()

    def test_missing_mention_denies_instead_of_executing(self):
        payload = dict(self.payload)
        payload.pop("isInAtList")
        with patch.object(connector, "post_json", return_value={"errcode": 0}) as post:
            self.assertEqual(self.dispatch(payload)[0], 200)
        self.assertIn("拒绝执行", post.call_args.args[1]["text"]["content"])

    def test_failed_reply_requests_retry_and_reuses_result(self):
        with patch.object(connector, "post_json", side_effect=WebhookTransportError("synthetic failure")):
            self.assertEqual(self.dispatch()[0], 500)
        count = len(self.fixture.application.database.list_interaction_audit())
        with patch.object(connector, "post_json", return_value={"errcode": 0}):
            self.assertEqual(self.dispatch()[0], 200)
        self.assertEqual(len(self.fixture.application.database.list_interaction_audit()), count)

    def test_invalid_provider_reply_is_not_acknowledged_as_success(self):
        with patch.object(connector, "post_json", return_value={}):
            self.assertEqual(self.dispatch()[0], 500)

    def test_untrusted_session_url_never_reaches_transport(self):
        payload = {**self.payload, "sessionWebhook": "https://attacker.invalid/collect"}
        with patch.object(connector, "post_json") as post:
            self.assertEqual(self.dispatch(payload)[0], 400)
        post.assert_not_called()

    def test_identity_swap_cannot_replay_sensitive_response(self):
        payload = {**self.payload, "text": {"content": "回复 " + self.fixture.case_ref}}
        with patch.object(connector, "post_json", return_value={"errcode": 0}) as post:
            self.dispatch(payload)
            self.dispatch({**payload, "senderStaffId": "blocked-user", "conversationId": "blocked-chat"})
        last_reply = post.call_args.args[1]["text"]["content"]
        self.assertIn("拒绝执行", last_reply)
        self.assertNotIn("EX-1001", last_reply)

    def test_sdk_logs_suppress_ticket_body_and_exception(self):
        logger = self.client.logger
        self.assertIs(logger, self.handler.logger)
        self.assertIs(logger, self.client.system_handler.logger)
        with self.assertLogs(logger, logging.INFO) as captured:
            logger.info("endpoint is %s", {"ticket": "SYNTHETIC_PRIVATE_TICKET"})
            try:
                raise RuntimeError("SYNTHETIC_PRIVATE_EXCEPTION")
            except RuntimeError:
                logger.exception("SYNTHETIC_PRIVATE_BODY")
        self.assertNotIn("SYNTHETIC_PRIVATE", " ".join(captured.output))

    def test_bootstrap_uses_timeout_and_official_endpoint(self):
        result = {"endpoint": "wss://wss-open-connection.dingtalk.com/connect", "ticket": "synthetic"}
        with patch.object(self.client, "get_host_ip", return_value="127.0.0.1"), patch.object(connector, "post_json", return_value=result) as post:
            self.assertEqual(self.client.open_connection(), result)
        self.assertEqual(post.call_args.args[0], self.sdk.DingTalkStreamClient.OPEN_CONNECTION_API)
        self.assertEqual(post.call_args.args[2], 15.0)

    def test_bootstrap_rejects_untrusted_websocket_destination(self):
        with patch.object(self.client, "get_host_ip", return_value="127.0.0.1"), patch.object(connector, "post_json", return_value={"endpoint": "wss://attacker.invalid/connect", "ticket": "synthetic"}), self.assertRaises(connector.DingTalkConnectorError):
            self.client.open_connection()


if __name__ == "__main__":
    unittest.main()
