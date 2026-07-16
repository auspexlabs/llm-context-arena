"""Compatibility wrappers over the canonical :class:`StorageService`."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional

from .storage_service import StorageService


@lru_cache()
def _service() -> StorageService:
    return StorageService()


def ensure_data_dir() -> None:
    _service().data_dir.mkdir(parents=True, exist_ok=True)


def get_conversation_path(conversation_id: str) -> str:
    return str(_service()._get_conversation_path(conversation_id))


def create_conversation(conversation_id: str, mode: str = "council") -> Dict[str, Any]:
    return _service().create_conversation(conversation_id, mode)


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    return _service().get_conversation(conversation_id)


def save_conversation(conversation: Dict[str, Any]) -> None:
    _service().save_conversation(conversation)


def list_conversations() -> List[Dict[str, Any]]:
    return _service().list_conversations()


def add_user_message(conversation_id: str, content: str) -> None:
    _service().add_user_message(conversation_id, content)


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any],
    context_sources: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    _service().add_assistant_message(
        conversation_id,
        stage1,
        stage2,
        stage3,
        context_sources,
        metadata,
    )


def update_conversation_title(conversation_id: str, title: str) -> None:
    _service().update_conversation_title(conversation_id, title)


def reset_conversation(conversation_id: str) -> None:
    _service().reset_conversation(conversation_id)
