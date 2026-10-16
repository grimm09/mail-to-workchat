from __future__ import annotations

from dataclasses import dataclass

from ..notifiers.base import Notifier
from ..security import sanitize_error
from .database import Database


@dataclass(frozen=True)
class FlushResult:
    sent: int = 0
    retried: int = 0
    dead_lettered: int = 0


class OutboxDispatcher:
    def __init__(self, database: Database, notifiers: dict[str, Notifier], *, max_attempts: int):
        self.database = database
        self.notifiers = notifiers
        self.max_attempts = max_attempts

    def flush(self, limit: int = 20) -> FlushResult:
        sent = retried = dead_lettered = 0
        for _ in range(limit):
            claimed = self.database.claim_ready_jobs(1)
            if not claimed:
                break
            job = claimed[0]
            notifier = self.notifiers.get(job.notifier_id)
            if notifier is None:
                outcome_success = False
                detail = f"notifier is unavailable: {job.notifier_id}"
            else:
                try:
                    outcome = notifier.send(job.notification)
                    outcome_success = outcome.success
                    detail = outcome.detail
                except Exception as exc:  # defensive boundary for third-party adapters
                    outcome_success = False
                    detail = sanitize_error(exc)
            if outcome_success:
                self.database.mark_sent(job.id)
                sent += 1
            else:
                status = self.database.mark_failed(
                    job.id,
                    sanitize_error(detail),
                    max_attempts=self.max_attempts,
                )
                if status == "dead_letter":
                    dead_lettered += 1
                elif status == "pending":
                    retried += 1
        return FlushResult(sent=sent, retried=retried, dead_lettered=dead_lettered)
