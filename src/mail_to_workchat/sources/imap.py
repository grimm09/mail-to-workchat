from __future__ import annotations

import imaplib
import ssl
from collections.abc import Callable

from ..mail import MailParseError, parse_email_bytes
from ..models import Checkpoint, MailAccount, ScanBatch, ScanFailure
from ..security import read_secret


class ImapError(RuntimeError):
    pass


def _parse_uids(data: object) -> list[int]:
    if not isinstance(data, (list, tuple)):
        return []
    tokens: list[bytes] = []
    for item in data:
        if isinstance(item, bytes):
            tokens.extend(item.split())
        elif isinstance(item, str):
            tokens.extend(item.encode("ascii", errors="ignore").split())
    result = []
    for token in tokens:
        try:
            result.append(int(token))
        except ValueError:
            continue
    return sorted(set(result))


def _uid_validity(mail: imaplib.IMAP4) -> str:
    response = mail.response("UIDVALIDITY")
    candidates: list[object] = []
    if isinstance(response, tuple):
        candidates.extend(response[1] or [])
    for value in candidates:
        if isinstance(value, bytes):
            text = value.decode("ascii", errors="ignore")
        else:
            text = str(value)
        digits = "".join(character for character in text if character.isdigit())
        if digits:
            return digits
    return "unknown"


def _raw_message(data: object) -> bytes:
    if isinstance(data, (list, tuple)):
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return item[1]
    raise ImapError("IMAP FETCH returned no message body")


class ImapSource:
    def __init__(
        self,
        *,
        initial_sync: str = "baseline",
        client_factory: Callable[[MailAccount], imaplib.IMAP4] | None = None,
    ):
        self.initial_sync = initial_sync
        self.client_factory = client_factory

    def _connect(self, account: MailAccount) -> imaplib.IMAP4:
        if self.client_factory:
            return self.client_factory(account)
        context = ssl.create_default_context()
        if account.security == "ssl":
            return imaplib.IMAP4_SSL(
                account.host,
                account.port,
                ssl_context=context,
                timeout=account.timeout_seconds,
            )
        client = imaplib.IMAP4(account.host, account.port, timeout=account.timeout_seconds)
        client.starttls(ssl_context=context)
        return client

    def scan(self, account: MailAccount, checkpoint: Checkpoint | None) -> ScanBatch:
        password = read_secret(account.password_env)
        mail = self._connect(account)
        selected = False
        try:
            status, _ = mail.login(account.username, password)
            if status != "OK":
                raise ImapError("IMAP login failed")
            status, _ = mail.select(account.folder, readonly=True)
            if status != "OK":
                raise ImapError("IMAP folder selection failed")
            selected = True
            validity = _uid_validity(mail)
            same_generation = (
                checkpoint is not None
                and checkpoint.folder == account.folder
                and checkpoint.uid_validity == validity
            )
            last_uid = checkpoint.last_uid if same_generation and checkpoint else 0
            criteria = f"UID {last_uid + 1}:*" if same_generation else "ALL"
            status, data = mail.uid("search", None, criteria)
            if status != "OK":
                raise ImapError("IMAP UID search failed")
            all_uids = _parse_uids(data)
            highest_uid = all_uids[-1] if all_uids else last_uid
            sync_mode = account.initial_sync or self.initial_sync
            if not same_generation and sync_mode == "baseline":
                return ScanBatch(
                    account_id=account.id,
                    folder=account.folder,
                    uid_validity=validity,
                    messages=(),
                    final_uid=highest_uid,
                    baseline_only=True,
                )

            candidate_uids = [uid for uid in all_uids if uid > last_uid]
            candidate_uids = candidate_uids[: account.max_messages_per_run]
            messages = []
            failures = []
            final_uid = last_uid
            for uid in candidate_uids:
                status, fetch_data = mail.uid(
                    "fetch",
                    str(uid),
                    f"(BODY.PEEK[]<0.{account.max_message_bytes}>)",
                )
                if status != "OK":
                    raise ImapError(f"IMAP UID fetch failed for UID {uid}")
                raw = _raw_message(fetch_data)
                try:
                    if len(raw) >= account.max_message_bytes:
                        raise MailParseError("message_size_limit")
                    message = parse_email_bytes(
                        raw,
                        account_id=account.id,
                        account_label=account.label,
                        folder=account.folder,
                        uid=uid,
                        uid_validity=validity,
                    )
                    messages.append(message)
                except MailParseError as exc:
                    failures.append(ScanFailure(uid, str(exc)))
                final_uid = uid
            return ScanBatch(
                account_id=account.id,
                folder=account.folder,
                uid_validity=validity,
                messages=tuple(messages),
                final_uid=final_uid,
                baseline_only=False,
                failures=tuple(failures),
            )
        except imaplib.IMAP4.error as exc:
            raise ImapError("IMAP protocol operation failed") from exc
        finally:
            try:
                if selected:
                    mail.close()
            except (imaplib.IMAP4.error, OSError):
                pass
            try:
                mail.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
