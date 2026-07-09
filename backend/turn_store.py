"""Persistent turn state for agent step API."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DATA_DIR
from .models import TurnRecord, TurnStatus


class TurnStore:
    """JSON sidecar storage: data/conversations/turns/{conversation_id}/{turn_id}.json"""

    def __init__(self, base_dir: str = DATA_DIR):
        self.base_dir = Path(base_dir) / "turns"

    def _conversation_dir(self, conversation_id: str) -> Path:
        path = self.base_dir / conversation_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _turn_path(self, conversation_id: str, turn_id: str) -> Path:
        return self._conversation_dir(conversation_id) / f"{turn_id}.json"

    def save(self, turn: TurnRecord) -> TurnRecord:
        turn.updated_at = datetime.utcnow()
        path = self._turn_path(turn.conversation_id, turn.turn_id)
        path.write_text(turn.model_dump_json(indent=2), encoding="utf-8")
        return turn

    def get(self, conversation_id: str, turn_id: str) -> Optional[TurnRecord]:
        path = self._turn_path(conversation_id, turn_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return TurnRecord.model_validate(data)

    def list_for_conversation(self, conversation_id: str) -> List[TurnRecord]:
        conv_dir = self.base_dir / conversation_id
        if not conv_dir.is_dir():
            return []
        turns: List[TurnRecord] = []
        for path in sorted(conv_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                turns.append(TurnRecord.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return turns

    def active_turn(self, conversation_id: str) -> Optional[TurnRecord]:
        for turn in self.list_for_conversation(conversation_id):
            if turn.status not in {
                TurnStatus.COMPLETE,
                TurnStatus.CANCELLED,
                TurnStatus.FAILED,
            }:
                return turn
        return None

    def delete(self, conversation_id: str, turn_id: str) -> bool:
        path = self._turn_path(conversation_id, turn_id)
        if not path.exists():
            return False
        path.unlink()
        return True