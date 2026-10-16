from __future__ import annotations

from ..models import NotifierConfig
from .base import Notifier
from .webhook import WebhookNotifier


def build_notifiers(configs: tuple[NotifierConfig, ...]) -> dict[str, Notifier]:
    return {
        config.id: WebhookNotifier(config)
        for config in configs
        if config.enabled
    }
