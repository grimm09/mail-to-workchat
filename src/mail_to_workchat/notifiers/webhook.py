from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..models import DeliveryOutcome, Notification, NotifierConfig
from ..security import read_secret, sanitize_error, validate_webhook_url
from .http import post_json


Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


def provider_success(response: dict[str, Any], kind: str) -> DeliveryOutcome:
    key = "errcode" if kind == "dingtalk" else "code"
    code = response.get(key, response.get("StatusCode") if kind == "feishu" else None)
    if (type(code) is int and code == 0) or (isinstance(code, str) and code == "0"):
        return DeliveryOutcome(True, "sent")
    if type(code) is int or (isinstance(code, str) and len(code) <= 12 and code.isdigit()):
        return DeliveryOutcome(False, f"provider rejected request (code {code})")
    return DeliveryOutcome(False, "provider response has no valid success status")


def _query_url(url: str, values: dict[str, str]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


class WebhookNotifier:
    def __init__(
        self,
        config: NotifierConfig,
        *,
        transport: Transport = post_json,
        clock: Callable[[], float] = time.time,
    ):
        self.id = config.id
        self.config = config
        self.transport = transport
        self.clock = clock

    def _credentials(self) -> tuple[str, str]:
        url = read_secret(self.config.webhook_env)
        validate_webhook_url(
            url,
            allowed_hosts=self.config.allowed_hosts,
            provider=self.config.kind,
        )
        secret = read_secret(self.config.secret_env) if self.config.secret_env else ""
        return url, secret

    def _request(self, notification: Notification, url: str, secret: str) -> tuple[str, dict[str, Any]]:
        if self.config.kind == "dingtalk":
            if secret:
                timestamp = str(int(self.clock() * 1000))
                signature = base64.b64encode(
                    hmac.new(
                        secret.encode("utf-8"),
                        f"{timestamp}\n{secret}".encode("utf-8"),
                        hashlib.sha256,
                    ).digest()
                ).decode("ascii")
                url = _query_url(url, {"timestamp": timestamp, "sign": signature})
            return url, {
                "msgtype": "markdown",
                "markdown": {"title": notification.title, "text": notification.text},
            }
        if self.config.kind == "feishu":
            payload: dict[str, Any] = {
                "msg_type": "interactive",
                "card": {
                    "schema": "2.0",
                    "header": {"title": {"tag": "plain_text", "content": notification.title}},
                    "body": {
                        "elements": [{"tag": "markdown", "content": notification.text}],
                    },
                },
            }
            if secret:
                timestamp = str(int(self.clock()))
                key = f"{timestamp}\n{secret}".encode("utf-8")
                signature = base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode("ascii")
                payload.update({"timestamp": timestamp, "sign": signature})
            return url, payload
        return url, {
            "event": "mail.notification",
            "title": notification.title,
            "text": notification.text,
            "message_key": notification.message_key,
            "metadata": notification.metadata,
        }

    def send(self, notification: Notification) -> DeliveryOutcome:
        try:
            url, secret = self._credentials()
            request_url, payload = self._request(notification, url, secret)
            if self.config.kind == "feishu":
                payload_bytes = len(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                )
                if payload_bytes > 20 * 1024:
                    return DeliveryOutcome(False, "payload exceeds Feishu custom-bot limit")
            response = self.transport(request_url, payload, self.config.timeout_seconds)
            if self.config.kind in {"dingtalk", "feishu"}:
                return provider_success(response, self.config.kind)
            return DeliveryOutcome(True, "sent")
        except Exception as exc:  # delivery errors are converted into bounded retry details
            return DeliveryOutcome(False, sanitize_error(exc))
