from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

from ..models import __version__


class WebhookTransportError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": f"mail-to-workchat/{__version__}"},
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirect(),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(32769)
            if len(raw) > 32768:
                raise WebhookTransportError("webhook response exceeded 32 KiB")
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                raise WebhookTransportError(f"webhook returned HTTP {status}")
    except urllib.error.HTTPError as exc:
        raise WebhookTransportError(f"webhook returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise WebhookTransportError("webhook connection failed") from exc
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise WebhookTransportError("webhook response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise WebhookTransportError("webhook response must be a JSON object")
    return value
