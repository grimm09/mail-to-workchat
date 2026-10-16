from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..models import Checkpoint, IncomingMessage, Notification
from ..security import SecurityError


@dataclass(frozen=True)
class OutboxJob:
    id: int
    dedupe_key: str
    notifier_id: str
    notification: Notification
    attempts: int


@dataclass(frozen=True)
class OutboxSummary:
    id: int
    notifier_id: str
    status: str
    attempts: int
    last_error: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class CaseSnapshot:
    account_label: str
    sender_email: str
    subject: str
    snippet: str
    extracted: dict[str, str]
    draft_path: str = ""
    draft_status: str = ""
    template_id: str = ""
    sender_name: str = ""
    template_context_digest: str = ""


@dataclass(frozen=True)
class CaseRecord:
    message_key: str
    case_ref: str
    account_id: str
    account_label: str
    rule_id: str
    status: str
    sender_email: str
    subject: str
    snippet: str
    extracted: dict[str, str]
    draft_path: str
    draft_status: str
    template_id: str
    received_at: str
    created_at: float
    updated_at: float
    sender_name: str = ""
    template_context_digest: str = ""


@dataclass(frozen=True)
class InteractionAudit:
    event_id: str
    bot_id: str
    platform: str
    user_hash: str
    command: str
    target: str
    outcome: str
    created_at: float


@dataclass(frozen=True)
class TemplateChangeRecord:
    change_id: str
    template_id: str
    base_digest: str
    reply_subject: str
    reply_body: str
    status: str
    created_by_hash: str
    source_event_id: str
    created_at: float
    applied_at: float | None
    revision: int | None


@dataclass(frozen=True)
class TemplateRevisionRecord:
    template_id: str
    revision: int
    content_toml: str
    content_digest: str
    changed_by_hash: str
    reason: str
    created_at: float


class Database:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    account_id TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    uid_validity TEXT NOT NULL,
                    last_uid INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (account_id, folder)
                );

                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_key TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    uid INTEGER NOT NULL,
                    rule_id TEXT,
                    status TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    notifier_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS outbox_ready_idx
                ON outbox(status, available_at, id);

                CREATE TABLE IF NOT EXISTS case_records (
                    message_key TEXT PRIMARY KEY,
                    case_ref TEXT NOT NULL UNIQUE,
                    account_id TEXT NOT NULL,
                    account_label TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    sender_email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    extracted_json TEXT NOT NULL DEFAULT '{}',
                    draft_path TEXT NOT NULL DEFAULT '',
                    draft_status TEXT NOT NULL DEFAULT '',
                    template_id TEXT NOT NULL DEFAULT '',
                    received_at TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(message_key) REFERENCES processed_messages(message_key)
                );

                CREATE INDEX IF NOT EXISTS case_records_status_idx
                ON case_records(status, received_at DESC);

                CREATE TABLE IF NOT EXISTS interaction_events (
                    event_id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    chat_hash TEXT NOT NULL,
                    user_hash TEXT NOT NULL,
                    command TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL DEFAULT 'processing',
                    response TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    completed_at REAL
                );

                CREATE INDEX IF NOT EXISTS interaction_events_created_idx
                ON interaction_events(created_at DESC);

                CREATE TABLE IF NOT EXISTS case_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    message_key TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES interaction_events(event_id),
                    FOREIGN KEY(message_key) REFERENCES case_records(message_key)
                );

                CREATE TABLE IF NOT EXISTS template_changes (
                    change_id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    base_digest TEXT NOT NULL,
                    reply_subject TEXT NOT NULL,
                    reply_body TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_by_hash TEXT NOT NULL,
                    source_event_id TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    applied_at REAL,
                    revision INTEGER,
                    FOREIGN KEY(source_event_id) REFERENCES interaction_events(event_id)
                );

                CREATE INDEX IF NOT EXISTS template_changes_status_idx
                ON template_changes(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS template_revisions (
                    template_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    content_toml TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    changed_by_hash TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(template_id, revision),
                    UNIQUE(template_id, content_digest)
                );

                CREATE TABLE IF NOT EXISTS inbound_failures (
                    account_id TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    uid_validity TEXT NOT NULL,
                    uid INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(account_id, folder, uid_validity, uid)
                );
                """
            )
            connection.commit()
        with self._transaction() as connection:
            migrations = {
                "case_records": {"sender_name": "TEXT NOT NULL DEFAULT ''", "template_context_digest": "TEXT NOT NULL DEFAULT ''"},
                "interaction_events": {"request_hash": "TEXT NOT NULL DEFAULT ''", "lease_until": "REAL NOT NULL DEFAULT 0"},
            }
            for table, columns in migrations.items():
                existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                for name, definition in columns.items():
                    if name not in existing:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def is_processed(self, message_key: str) -> bool:
        with closing(self._connect()) as connection:
            return connection.execute("SELECT 1 FROM processed_messages WHERE message_key=?", (message_key,)).fetchone() is not None

    def quarantine(self, account_id: str, folder: str, validity: str, uid: int, reason: str) -> None:
        if reason not in {"invalid_mime", "mime_structure_limit", "message_size_limit"}:
            raise ValueError("unsupported quarantine reason")
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO inbound_failures VALUES(?, ?, ?, ?, ?, ?)",
                (account_id, folder, validity, uid, reason, time.time()),
            )

    def list_inbound_failures(self, limit: int = 20) -> tuple[dict, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("failure list limit must be between 1 and 200")
        with closing(self._connect()) as connection:
            return tuple(dict(row) for row in connection.execute(
                "SELECT * FROM inbound_failures ORDER BY created_at DESC LIMIT ?", (limit,)
            ))

    def get_checkpoint(self, account_id: str, folder: str) -> Checkpoint | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT account_id, folder, uid_validity, last_uid FROM checkpoints "
                "WHERE account_id=? AND folder=?",
                (account_id, folder),
            ).fetchone()
        if row is None:
            return None
        return Checkpoint(
            account_id=str(row["account_id"]),
            folder=str(row["folder"]),
            uid_validity=str(row["uid_validity"]),
            last_uid=int(row["last_uid"]),
        )

    def set_checkpoint(self, account_id: str, folder: str, uid_validity: str, last_uid: int) -> None:
        now = time.time()
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints(account_id, folder, uid_validity, last_uid, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(account_id, folder) DO UPDATE SET
                    uid_validity=excluded.uid_validity,
                    last_uid=excluded.last_uid,
                    updated_at=excluded.updated_at
                """,
                (account_id, folder, uid_validity, last_uid, now),
            )

    def record_message(
        self,
        message: IncomingMessage,
        *,
        rule_id: str | None,
        status: str,
        notification: Notification | None = None,
        notifier_ids: tuple[str, ...] = (),
        case_snapshot: CaseSnapshot | None = None,
    ) -> bool:
        now = time.time()
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO processed_messages(
                    message_key, account_id, folder, uid, rule_id, status, received_at, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.message_key,
                    message.account_id,
                    message.folder,
                    message.uid,
                    rule_id,
                    status,
                    message.received_at.isoformat(),
                    now,
                ),
            )
            inserted = cursor.rowcount == 1
            if inserted and rule_id is not None and case_snapshot is not None:
                connection.execute(
                    """
                    INSERT INTO case_records(
                        message_key, case_ref, account_id, account_label, rule_id, status,
                        sender_email, subject, snippet, extracted_json, draft_path,
                        draft_status, template_id, received_at, created_at, updated_at,
                        sender_name, template_context_digest
                    ) VALUES(?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.message_key,
                        f"m-{message.message_key[:12]}",
                        message.account_id,
                        case_snapshot.account_label,
                        rule_id,
                        case_snapshot.sender_email,
                        case_snapshot.subject,
                        case_snapshot.snippet,
                        json.dumps(
                            case_snapshot.extracted,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        case_snapshot.draft_path,
                        case_snapshot.draft_status,
                        case_snapshot.template_id,
                        message.received_at.isoformat(),
                        now,
                        now,
                        case_snapshot.sender_name,
                        case_snapshot.template_context_digest,
                    ),
                )
            if inserted and notification is not None:
                payload = json.dumps(notification.as_dict(), ensure_ascii=False, separators=(",", ":"))
                for notifier_id in notifier_ids:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO outbox(
                            dedupe_key, notifier_id, event_json, status, attempts,
                            available_at, last_error, created_at, updated_at
                        ) VALUES(?, ?, ?, 'pending', 0, ?, '', ?, ?)
                        """,
                        (
                            f"{notification.event_key}:{notifier_id}",
                            notifier_id,
                            payload,
                            now,
                            now,
                            now,
                        ),
                    )
        return inserted

    def ready_jobs(self, limit: int = 20, *, now: float | None = None) -> tuple[OutboxJob, ...]:
        timestamp = time.time() if now is None else now
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, dedupe_key, notifier_id, event_json, attempts
                FROM outbox
                WHERE status='pending' AND available_at<=?
                ORDER BY id
                LIMIT ?
                """,
                (timestamp, limit),
            ).fetchall()
        return self._jobs_from_rows(rows)

    @staticmethod
    def _jobs_from_rows(rows) -> tuple[OutboxJob, ...]:  # noqa: ANN001
        result = []
        for row in rows:
            result.append(
                OutboxJob(
                    id=int(row["id"]),
                    dedupe_key=str(row["dedupe_key"]),
                    notifier_id=str(row["notifier_id"]),
                    notification=Notification.from_dict(json.loads(str(row["event_json"]))),
                    attempts=int(row["attempts"]),
                )
            )
        return tuple(result)

    def claim_ready_jobs(
        self,
        limit: int = 20,
        *,
        now: float | None = None,
        lease_seconds: float = 60.0,
    ) -> tuple[OutboxJob, ...]:
        timestamp = time.time() if now is None else now
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT id, dedupe_key, notifier_id, event_json, attempts
                FROM outbox
                WHERE status='pending' AND available_at<=?
                ORDER BY id
                LIMIT ?
                """,
                (timestamp, limit),
            ).fetchall()
            if rows:
                connection.executemany(
                    "UPDATE outbox SET available_at=?, updated_at=? WHERE id=? AND status='pending'",
                    ((timestamp + lease_seconds, timestamp, int(row["id"])) for row in rows),
                )
        return self._jobs_from_rows(rows)

    def mark_sent(self, job_id: int) -> None:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE outbox SET status='sent', updated_at=?, last_error='' WHERE id=? AND status='pending'",
                (time.time(), job_id),
            )

    def mark_failed(self, job_id: int, error: str, *, max_attempts: int) -> str:
        now = time.time()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT attempts FROM outbox WHERE id=? AND status='pending'", (job_id,)
            ).fetchone()
            if row is None:
                return "unchanged"
            attempts = int(row["attempts"]) + 1
            status = "dead_letter" if attempts >= max_attempts else "pending"
            delay = min(3600, 30 * (2 ** max(0, attempts - 1)))
            connection.execute(
                """
                UPDATE outbox
                SET status=?, attempts=?, available_at=?, last_error=?, updated_at=?
                WHERE id=?
                """,
                (status, attempts, now + delay, error[:240], now, job_id),
            )
        return status

    def outbox_counts(self) -> dict[str, int]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM outbox GROUP BY status"
            ).fetchall()
        result = {"pending": 0, "sent": 0, "dead_letter": 0, "cancelled": 0}
        result.update({str(row["status"]): int(row["count"]) for row in rows})
        return result

    def list_outbox(self, status: str, limit: int = 20) -> tuple[OutboxSummary, ...]:
        if status not in {"pending", "sent", "dead_letter", "cancelled"}:
            raise ValueError("unsupported outbox status")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, notifier_id, status, attempts, last_error, created_at, updated_at
                FROM outbox
                WHERE status=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        return tuple(
            OutboxSummary(
                id=int(row["id"]),
                notifier_id=str(row["notifier_id"]),
                status=str(row["status"]),
                attempts=int(row["attempts"]),
                last_error=str(row["last_error"]),
                created_at=float(row["created_at"]),
                updated_at=float(row["updated_at"]),
            )
            for row in rows
        )

    def retry_dead_letter(self, job_id: int) -> bool:
        now = time.time()
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE outbox
                SET status='pending', attempts=0, available_at=?, last_error='', updated_at=?
                WHERE id=? AND status='dead_letter'
                """,
                (now, now, job_id),
            )
        return cursor.rowcount == 1

    def processed_count(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM processed_messages").fetchone()
        return int(row["count"]) if row else 0

    @staticmethod
    def _case_from_row(row: sqlite3.Row) -> CaseRecord:
        try:
            extracted = json.loads(str(row["extracted_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            extracted = {}
        return CaseRecord(
            message_key=str(row["message_key"]),
            case_ref=str(row["case_ref"]),
            account_id=str(row["account_id"]),
            account_label=str(row["account_label"]),
            rule_id=str(row["rule_id"]),
            status=str(row["status"]),
            sender_email=str(row["sender_email"]),
            subject=str(row["subject"]),
            snippet=str(row["snippet"]),
            extracted={str(key): str(value) for key, value in dict(extracted).items()},
            draft_path=str(row["draft_path"]),
            draft_status=str(row["draft_status"]),
            template_id=str(row["template_id"]),
            received_at=str(row["received_at"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            sender_name=str(row["sender_name"]),
            template_context_digest=str(row["template_context_digest"]),
        )

    def find_case(self, reference: str) -> CaseRecord | None:
        normalized = reference.strip().strip("`").lower()
        if re.fullmatch(r"[0-9a-f]{8,32}", normalized):
            normalized = f"m-{normalized}"
        if not re.fullmatch(r"m-[0-9a-f]{8,32}", normalized):
            raise ValueError("case reference must look like m- followed by at least 8 hex characters")
        with closing(self._connect()) as connection:
            if len(normalized) == 34:
                rows = connection.execute(
                    "SELECT * FROM case_records WHERE case_ref=? OR message_key=?",
                    (normalized, normalized[2:]),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM case_records WHERE message_key LIKE ? ORDER BY received_at DESC LIMIT 2",
                    (f"{normalized[2:]}%",),
                ).fetchall()
        if len(rows) > 1:
            raise ValueError("case reference is ambiguous; provide more characters")
        return self._case_from_row(rows[0]) if rows else None

    def list_cases(self, *, status: str | None = "open", limit: int = 10) -> tuple[CaseRecord, ...]:
        if limit <= 0 or limit > 100:
            raise ValueError("case list limit must be between 1 and 100")
        with closing(self._connect()) as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM case_records ORDER BY received_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM case_records WHERE status=? ORDER BY received_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
        return tuple(self._case_from_row(row) for row in rows)

    def pending_drafts(self, template_id: str) -> tuple[CaseRecord, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM case_records WHERE template_id=? AND draft_status='needs_review'", (template_id,)).fetchall()
        return tuple(self._case_from_row(row) for row in rows)

    def update_case_draft(self, message_key: str, path: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE case_records SET draft_path=?, draft_status='ready', updated_at=? WHERE message_key=? AND draft_status='needs_review'",
                (path, time.time(), message_key),
            )

    def set_case_status(
        self,
        message_key: str,
        *,
        status: str,
        event_id: str,
        actor_hash: str,
        action: str,
    ) -> bool:
        if status not in {"open", "ignored", "resolved"}:
            raise ValueError("unsupported case status")
        now = time.time()
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE case_records SET status=?, updated_at=? WHERE message_key=?",
                (status, now, message_key),
            )
            if cursor.rowcount != 1:
                return False
            if status == "ignored":
                connection.execute(
                    "UPDATE outbox SET status='cancelled', updated_at=? WHERE status='pending' AND dedupe_key LIKE ?",
                    (now, f"mail:{message_key}:%"),
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO case_actions(event_id, message_key, action, actor_hash, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (event_id, message_key, action, actor_hash, now),
            )
            connection.execute(
                "UPDATE processed_messages SET status=? WHERE message_key=?",
                (status, message_key),
            )
        return True

    def reserve_interaction_event(
        self,
        *,
        event_id: str,
        bot_id: str,
        platform: str,
        chat_hash: str,
        user_hash: str,
        command: str,
        target: str,
        request_hash: str = "",
        lease_seconds: float = 60.0,
    ) -> tuple[bool, str]:
        now = time.time()
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO interaction_events(
                    event_id, bot_id, platform, chat_hash, user_hash, command,
                    target, outcome, response, created_at, request_hash, lease_until
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 'processing', '', ?, ?, ?)
                """,
                (event_id, bot_id, platform, chat_hash, user_hash, command, target, now, request_hash, now + lease_seconds),
            )
            if cursor.rowcount == 1:
                return True, ""
            row = connection.execute(
                "SELECT * FROM interaction_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if row is None:
                return False, ""
            expected = (bot_id, platform, chat_hash, user_hash, request_hash)
            actual = tuple(row[key] for key in ("bot_id", "platform", "chat_hash", "user_hash", "request_hash"))
            if actual != expected:
                raise SecurityError("事件编号与原始身份或内容不一致")
            if row["outcome"] in {"processing", "error"}:
                if float(row["lease_until"]) > now:
                    return False, ""
                connection.execute(
                    "UPDATE interaction_events SET outcome='processing', response='', lease_until=? WHERE event_id=?",
                    (now + lease_seconds, event_id),
                )
                return True, ""
            return False, str(row["response"])

    def complete_interaction_event(self, event_id: str, *, outcome: str, response: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE interaction_events
                SET outcome=?, response=?, completed_at=?, lease_until=?
                WHERE event_id=?
                """,
                (outcome[:80], response[:12000], time.time(), time.time() + 2 if outcome == "error" else 0, event_id),
            )

    def list_interaction_audit(self, limit: int = 20) -> tuple[InteractionAudit, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("audit limit must be between 1 and 200")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT event_id, bot_id, platform, user_hash, command, target, outcome, created_at
                FROM interaction_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(
            InteractionAudit(
                event_id=str(row["event_id"]),
                bot_id=str(row["bot_id"]),
                platform=str(row["platform"]),
                user_hash=str(row["user_hash"]),
                command=str(row["command"]),
                target=str(row["target"]),
                outcome=str(row["outcome"]),
                created_at=float(row["created_at"]),
            )
            for row in rows
        )

    def create_template_change(
        self,
        *,
        change_id: str,
        template_id: str,
        base_digest: str,
        reply_subject: str,
        reply_body: str,
        created_by_hash: str,
        source_event_id: str,
    ) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO template_changes(
                    change_id, template_id, base_digest, reply_subject, reply_body,
                    status, created_by_hash, source_event_id, created_at
                ) VALUES(?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    change_id,
                    template_id,
                    base_digest,
                    reply_subject,
                    reply_body,
                    created_by_hash,
                    source_event_id,
                    time.time(),
                ),
            )

    @staticmethod
    def _template_change_from_row(row: sqlite3.Row) -> TemplateChangeRecord:
        return TemplateChangeRecord(
            change_id=str(row["change_id"]),
            template_id=str(row["template_id"]),
            base_digest=str(row["base_digest"]),
            reply_subject=str(row["reply_subject"]),
            reply_body=str(row["reply_body"]),
            status=str(row["status"]),
            created_by_hash=str(row["created_by_hash"]),
            source_event_id=str(row["source_event_id"]),
            created_at=float(row["created_at"]),
            applied_at=float(row["applied_at"]) if row["applied_at"] is not None else None,
            revision=int(row["revision"]) if row["revision"] is not None else None,
        )

    def get_template_change(self, change_id: str) -> TemplateChangeRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM template_changes WHERE change_id=?",
                (change_id,),
            ).fetchone()
        return self._template_change_from_row(row) if row else None

    def template_change_for_event(self, event_id: str) -> TemplateChangeRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM template_changes WHERE source_event_id=?", (event_id,)).fetchone()
        return self._template_change_from_row(row) if row else None

    def applying_changes(self, template_id: str) -> tuple[TemplateChangeRecord, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM template_changes WHERE template_id=? AND status='applying'", (template_id,)).fetchall()
        return tuple(self._template_change_from_row(row) for row in rows)

    def mark_template_change_applying(self, change_id: str) -> bool:
        with self._transaction() as connection:
            result = connection.execute("UPDATE template_changes SET status='applying' WHERE change_id=? AND status='pending'", (change_id,))
        return result.rowcount == 1

    def cancel_template_change(self, change_id: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE template_changes SET status='cancelled', applied_at=?
                WHERE change_id=? AND status='pending'
                """,
                (time.time(), change_id),
            )
        return cursor.rowcount == 1

    def mark_template_change_applied(self, change_id: str, revision: int) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE template_changes
                SET status='applied', applied_at=?, revision=?
                WHERE change_id=? AND status='applying'
                """,
                (time.time(), revision, change_id),
            )
        return cursor.rowcount == 1

    def record_template_revision(
        self,
        *,
        template_id: str,
        content_toml: str,
        content_digest: str,
        changed_by_hash: str,
        reason: str,
    ) -> int:
        with self._transaction() as connection:
            existing = connection.execute(
                """
                SELECT revision FROM template_revisions
                WHERE template_id=? AND content_digest=?
                """,
                (template_id, content_digest),
            ).fetchone()
            if existing is not None:
                return int(existing["revision"])
            row = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision FROM template_revisions WHERE template_id=?",
                (template_id,),
            ).fetchone()
            revision = int(row["revision"]) + 1
            connection.execute(
                """
                INSERT INTO template_revisions(
                    template_id, revision, content_toml, content_digest,
                    changed_by_hash, reason, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    revision,
                    content_toml,
                    content_digest,
                    changed_by_hash,
                    reason[:240],
                    time.time(),
                ),
            )
        return revision

    def list_template_revisions(self, template_id: str) -> tuple[TemplateRevisionRecord, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM template_revisions
                WHERE template_id=? ORDER BY revision DESC
                """,
                (template_id,),
            ).fetchall()
        return tuple(self._template_revision_from_row(row) for row in rows)

    def get_template_revision(
        self,
        template_id: str,
        revision: int,
    ) -> TemplateRevisionRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM template_revisions
                WHERE template_id=? AND revision=?
                """,
                (template_id, revision),
            ).fetchone()
        return self._template_revision_from_row(row) if row else None

    @staticmethod
    def _template_revision_from_row(row: sqlite3.Row) -> TemplateRevisionRecord:
        return TemplateRevisionRecord(
            template_id=str(row["template_id"]),
            revision=int(row["revision"]),
            content_toml=str(row["content_toml"]),
            content_digest=str(row["content_digest"]),
            changed_by_hash=str(row["changed_by_hash"]),
            reason=str(row["reason"]),
            created_at=float(row["created_at"]),
        )
