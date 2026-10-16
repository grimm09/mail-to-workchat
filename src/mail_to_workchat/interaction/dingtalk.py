from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlsplit

from ..models import BotConfig, __version__
from ..notifiers.http import post_json, WebhookTransportError
from ..notifiers.webhook import provider_success
from ..security import SecurityError, read_secret, validate_webhook_url
from .models import ChatEvent, ChatEventError
from .service import InteractionService


class DingTalkConnectorError(RuntimeError):
    pass


class _SDKLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Upstream logs can include tickets, URLs and entire callback bodies.
        record.msg = "DingTalk SDK transport event (private details suppressed)"
        record.args = ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


def _sdk_logger() -> logging.Logger:
    logger = logging.getLogger("mail_to_workchat.dingtalk.sdk")
    logger.setLevel(logging.WARNING)
    if not any(isinstance(item, _SDKLogFilter) for item in logger.filters):
        logger.addFilter(_SDKLogFilter())
    return logger


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        if len(value) > 65_536:
            raise ChatEventError("DingTalk event data is too large")
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ChatEventError("DingTalk event data is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ChatEventError("DingTalk event data is invalid")
    return value


def _event(callback: Any, bot: BotConfig) -> tuple[ChatEvent, dict[str, Any]]:
    data = _payload(callback.data)
    headers = getattr(callback, "headers", None)
    header_id = headers.get("messageId") if isinstance(headers, dict) else getattr(headers, "message_id", None)
    content = data.get("text")
    if data.get("msgtype") != "text" or not isinstance(content, dict):
        raise ChatEventError("only text commands are supported")
    group_type = str(data.get("conversationType", ""))
    if group_type not in {"1", "2"}:
        raise ChatEventError("conversation type is required")
    event = ChatEvent.from_dict({
        "event_id": data.get("msgId") or header_id,
        "bot_id": bot.id,
        "platform": "dingtalk",
        "chat_id": data.get("conversationId"),
        "user_id": data.get("senderStaffId") or data.get("senderId"),
        "text": content.get("content"),
        "occurred_at": data.get("createAt"),
        "is_group": group_type == "2",
        "mentioned_bot": data.get("isInAtList", False),
    })
    return event, data


def _reply(text: str, data: dict[str, Any]) -> None:
    url = data.get("sessionWebhook")
    if not isinstance(url, str):
        raise SecurityError("session reply destination is missing")
    validate_webhook_url(url, allowed_hosts=("oapi.dingtalk.com", "api.dingtalk.com"), provider="dingtalk")
    payload = {"msgtype": "text", "text": {"content": text}}
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 16_000:
        raise SecurityError("reply exceeds this connector's payload limit")
    result = provider_success(post_json(url, payload, 10.0), "dingtalk")
    if not result.success:
        raise WebhookTransportError(result.detail)


def run_dingtalk_stream(bot: BotConfig, service: InteractionService) -> None:
    try:
        import dingtalk_stream  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DingTalkConnectorError("DingTalk support is not installed; run: pip install -e .[dingtalk]") from exc

    logger = _sdk_logger()

    class SafeStreamClient(dingtalk_stream.DingTalkStreamClient):
        def open_connection(self):
            # Upstream bootstrap has no HTTP timeout. Use the bounded, no-redirect transport.
            request = {
                "clientId": self.credential.client_id,
                "clientSecret": self.credential.client_secret,
                "subscriptions": [{"type": "CALLBACK", "topic": topic} for topic in self.callback_handler_map],
                "ua": f"mail-to-workchat/{__version__}",
                "localIp": self.get_host_ip(),
            }
            response = post_json(self.OPEN_CONNECTION_API, request, 15.0)
            endpoint, ticket = response.get("endpoint"), response.get("ticket")
            if not isinstance(endpoint, str) or not isinstance(ticket, str) or not ticket or len(ticket) > 4096:
                raise DingTalkConnectorError("invalid Stream connection response")
            parts = urlsplit(endpoint)
            host = (parts.hostname or "").lower()
            if parts.scheme != "wss" or not host.endswith(".dingtalk.com") or parts.username or parts.password or parts.fragment or parts.query:
                raise DingTalkConnectorError("untrusted Stream connection endpoint")
            return response

    class CommandHandler(dingtalk_stream.ChatbotHandler):
        async def process(self, callback):  # noqa: ANN001
            try:
                event, data = _event(callback, bot)
                response = service.handle(event)
                if response.outcome in {"retry", "error"}:
                    return dingtalk_stream.AckMessage.STATUS_SYSTEM_EXCEPTION, "RETRY"
                _reply(response.text, data)
            except (ChatEventError, SecurityError):
                return dingtalk_stream.AckMessage.STATUS_BAD_REQUEST, "INVALID"
            except Exception:
                logger.warning("callback processing or delivery failed")
                return dingtalk_stream.AckMessage.STATUS_SYSTEM_EXCEPTION, "RETRY"
            return dingtalk_stream.AckMessage.STATUS_OK, "OK"

    credential = dingtalk_stream.Credential(read_secret(bot.app_id_env), read_secret(bot.app_secret_env))
    client = SafeStreamClient(credential, logger=logger)
    handler = CommandHandler()
    handler.logger = logger
    client.event_handler.logger = logger
    client.system_handler.logger = logger
    client.register_callback_handler(dingtalk_stream.ChatbotMessage.TOPIC, handler)
    client.start_forever()
