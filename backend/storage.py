"""Legacy module API routed through Curia's canonical storage boundary.

New code should inject :class:`StorageService`. These names remain for older callers and
scripts while all mutation, locking, and session projection work stays inside the service.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .storage_service import StorageService


@lru_cache(maxsize=1)
def default_storage() -> StorageService:
    """Return the process-local compatibility service."""
    return StorageService()


class _StorageCompatibility:
    @property
    def service(self) -> StorageService:
        return default_storage()

    def ensure_data_dir(self) -> None:
        self.service.data_dir.mkdir(parents=True, exist_ok=True)

    def get_conversation_path(self, conversation_id: str) -> str:
        return str(self.service._get_conversation_path(conversation_id))

    def create_conversation(
        self,
        conversation_id: str,
        mode: str = "council",
    ) -> dict[str, Any]:
        return self.service.create_conversation(conversation_id, mode)

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self.service.get_conversation(conversation_id)

    def save_conversation(self, conversation: dict[str, Any]) -> None:
        self.service.save_conversation(conversation)

    def list_conversations(self) -> list[dict[str, Any]]:
        return self.service.list_conversations()

    def add_user_message(self, conversation_id: str, content: str) -> None:
        self.service.add_user_message(conversation_id, content)

    def add_assistant_message(
        self,
        conversation_id: str,
        stage1: list[dict[str, Any]],
        stage2: list[dict[str, Any]],
        stage3: dict[str, Any],
        context_sources: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.service.add_assistant_message(
            conversation_id,
            stage1,
            stage2,
            stage3,
            context_sources,
            metadata,
        )

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        self.service.update_conversation_title(conversation_id, title)

    def reset_conversation(self, conversation_id: str) -> None:
        self.service.reset_conversation(conversation_id)


_compat = _StorageCompatibility()

# Preserve the original import surface without duplicating persistence behavior.
ensure_data_dir = _compat.ensure_data_dir
get_conversation_path = _compat.get_conversation_path
create_conversation = _compat.create_conversation
get_conversation = _compat.get_conversation
save_conversation = _compat.save_conversation
list_conversations = _compat.list_conversations
add_user_message = _compat.add_user_message
add_assistant_message = _compat.add_assistant_message
update_conversation_title = _compat.update_conversation_title
reset_conversation = _compat.reset_conversation
