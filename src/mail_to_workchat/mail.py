from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import Message
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from .models import IncomingMessage


class MailParseError(ValueError):
    """A permanent, content-free reason suitable for the quarantine ledger."""


class _TextHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: str | None = None

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in {"script", "style"}:
            self.hidden = tag
        elif not self.hidden and tag in {"br", "p", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag == self.hidden:
            self.hidden = None
        elif not self.hidden and tag in {"p", "div"}:
            self.parts.append("\n")

    def handle_data(self, data):  # noqa: ANN001
        if not self.hidden:
            self.parts.append(data)


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except (LookupError, UnicodeError, ValueError):
        return str(value).strip()


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    parser = _TextHTMLParser()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


def message_body(message: Message) -> str:
    plain: list[str] = []
    html_parts: list[str] = []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        if disposition == "attachment":
            continue
        content_type = part.get_content_type().lower()
        if content_type == "text/plain":
            plain.append(_decode_part(part))
        elif content_type == "text/html":
            html_parts.append(_html_to_text(_decode_part(part)))
    chosen = "\n".join(plain).strip() or "\n".join(html_parts).strip()
    chosen = chosen.replace("\x00", "")
    # Avoid quadratic backtracking on long whitespace runs without a following newline.
    chosen = "\n".join(line.rstrip(" \t") for line in chosen.split("\n"))
    chosen = re.sub(r"\n{4,}", "\n\n\n", chosen)
    return chosen.strip()


def normalize_message_id(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", value).strip("<>").lower()


def stable_message_key(
    account_id: str,
    message_id: str,
    uid_validity: str,
    uid: int,
) -> str:
    normalized = normalize_message_id(message_id)
    identity = f"mid:{normalized}" if normalized else f"uid:{uid_validity}:{uid}"
    digest = hashlib.sha256(f"{account_id}\n{identity}".encode("utf-8")).hexdigest()
    return digest[:32]


def _received_at(value: str | None) -> datetime:
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass
    return datetime.now(timezone.utc)


def _parse_email_bytes(
    raw: bytes,
    *,
    account_id: str,
    account_label: str,
    folder: str,
    uid: int,
    uid_validity: str,
) -> IncomingMessage:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    stack = [(message, 0)]
    parts = 0
    while stack:
        part, depth = stack.pop()
        parts += 1
        if depth > 50 or parts > 1000:
            raise MailParseError("mime_structure_limit")
        if part.is_multipart():
            stack.extend((child, depth + 1) for child in part.get_payload())
    sender_name, sender_email = parseaddr(decode_mime_header(message.get("From")))
    message_id = str(message.get("Message-ID", ""))
    return IncomingMessage(
        account_id=account_id,
        account_label=account_label,
        folder=folder,
        uid=uid,
        uid_validity=uid_validity,
        message_key=stable_message_key(account_id, message_id, uid_validity, uid),
        message_id=normalize_message_id(message_id),
        sender_name=decode_mime_header(sender_name),
        sender_email=sender_email.strip().lower(),
        subject=decode_mime_header(message.get("Subject")),
        body=message_body(message),
        received_at=_received_at(str(message.get("Date", ""))),
    )


def parse_email_bytes(raw: bytes, **metadata) -> IncomingMessage:
    try:
        return _parse_email_bytes(raw, **metadata)
    except MailParseError:
        raise
    except (RecursionError, ValueError, UnicodeError, LookupError) as exc:
        # Do not persist exception text: malformed headers can contain private data.
        raise MailParseError("invalid_mime") from exc
