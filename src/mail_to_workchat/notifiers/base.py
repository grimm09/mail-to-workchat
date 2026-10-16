from __future__ import annotations

from typing import Protocol

from ..models import DeliveryOutcome, Notification


class Notifier(Protocol):
    id: str

    def send(self, notification: Notification) -> DeliveryOutcome: ...
