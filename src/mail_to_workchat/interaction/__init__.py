"""Optional, allowlisted work-chat command handling for personal deployments."""

from .models import ChatEvent, ChatResponse
from .service import InteractionService

__all__ = ["ChatEvent", "ChatResponse", "InteractionService"]
