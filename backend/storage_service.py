"""Storage service for conversation persistence.

Wraps storage operations in a service class for dependency injection.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DATA_DIR


class StorageService:
    """Service for conversation storage operations."""

    def __init__(self, data_dir: str = DATA_DIR):
        """
        Initialize the storage service.

        Args:
            data_dir: Directory path for storing conversation files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _get_conversation_path(self, conversation_id: str) -> Path:
        """Get the file path for a conversation."""
        return self.data_dir / f"{conversation_id}.json"

    def create_conversation(self, conversation_id: str, mode: str = "council") -> Dict[str, Any]:
        """
        Create a new conversation.

        Args:
            conversation_id: Unique identifier for the conversation
            mode: Arena mode for the conversation

        Returns:
            New conversation dict
        """
        conversation = {
            "id": conversation_id,
            "created_at": datetime.utcnow().isoformat(),
            "title": "New Conversation",
            "messages": [],
            "mode": mode,
        }

        path = self._get_conversation_path(conversation_id)
        with open(path, "w") as f:
            json.dump(conversation, f, indent=2)

        return conversation

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a conversation from storage.

        Args:
            conversation_id: Unique identifier for the conversation

        Returns:
            Conversation dict or None if not found
        """
        path = self._get_conversation_path(conversation_id)

        if not path.exists():
            return None

        with open(path, "r") as f:
            return json.load(f)

    def save_conversation(self, conversation: Dict[str, Any]) -> None:
        """
        Save a conversation to storage.

        Args:
            conversation: Conversation dict to save
        """
        path = self._get_conversation_path(conversation["id"])
        with open(path, "w") as f:
            json.dump(conversation, f, indent=2)

    def list_conversations(self) -> List[Dict[str, Any]]:
        """
        List all conversations (metadata only).

        Returns:
            List of conversation metadata dicts, sorted newest first
        """
        conversations = []
        for filename in os.listdir(self.data_dir):
            if filename.endswith(".json"):
                path = self.data_dir / filename
                with open(path, "r") as f:
                    data = json.load(f)
                    conversations.append({
                        "id": data["id"],
                        "created_at": data["created_at"],
                        "title": data.get("title", "New Conversation"),
                        "message_count": len(data["messages"]),
                        "mode": data.get("mode", "council"),
                    })

        conversations.sort(key=lambda x: x["created_at"], reverse=True)
        return conversations

    def add_user_message(self, conversation_id: str, content: str) -> None:
        """
        Add a user message to a conversation.

        Args:
            conversation_id: Conversation identifier
            content: User message content

        Raises:
            ValueError: If conversation not found
        """
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["messages"].append({
            "role": "user",
            "content": content,
        })

        self.save_conversation(conversation)

    def add_assistant_message(
        self,
        conversation_id: str,
        stage1: List[Dict[str, Any]],
        stage2: List[Dict[str, Any]],
        stage3: Dict[str, Any],
        context_sources: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add an assistant message with all 3 stages to a conversation.

        Args:
            conversation_id: Conversation identifier
            stage1: List of individual model responses
            stage2: List of model rankings
            stage3: Final synthesized response
            context_sources: Optional list of context sources used
            metadata: Optional execution metadata

        Raises:
            ValueError: If conversation not found
        """
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["messages"].append({
            "role": "assistant",
            "stage1": stage1,
            "stage2": stage2,
            "stage3": stage3,
            "context_sources": context_sources or [],
            "metadata": metadata or {},
        })

        self.save_conversation(conversation)

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        """
        Update the title of a conversation.

        Args:
            conversation_id: Conversation identifier
            title: New title for the conversation

        Raises:
            ValueError: If conversation not found
        """
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["title"] = title
        self.save_conversation(conversation)

    def reset_conversation(self, conversation_id: str) -> None:
        """
        Clear messages in a conversation but keep metadata.

        Args:
            conversation_id: Conversation identifier

        Raises:
            ValueError: If conversation not found
        """
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["messages"] = []
        self.save_conversation(conversation)

    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if deleted, False if not found
        """
        path = self._get_conversation_path(conversation_id)
        if not path.exists():
            return False

        path.unlink()
        return True
