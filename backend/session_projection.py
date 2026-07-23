"""Derive session-catalog rows from canonical conversations and turn sidecars."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cost_tracking import summarize_conversation_cost
from .session_catalog import SessionCatalogEntry


_QUALITY_RANK = {"unknown": 0, "ok": 1, "degraded": 2, "failed": 3}
_ACTIVE_TURN_STATUSES = {"pending", "stage1_complete", "stage2_complete", "await_user"}


class SessionProjector:
    """Pure summary semantics plus sidecar discovery for one storage root."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def turn_sidecars(self, conversation_id: str) -> List[Dict[str, Any]]:
        turn_dir = self.data_dir / "turns" / conversation_id
        if not turn_dir.is_dir():
            return []
        turns: List[Dict[str, Any]] = []
        for path in turn_dir.glob("*.json"):
            try:
                turns.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                continue
        turns.sort(key=lambda turn: str(turn.get("updated_at") or turn.get("created_at") or ""))
        return turns

    def checksum(self, canonical_payload: bytes, conversation_id: str) -> str:
        """Fingerprint every canonical input that can change the projected row."""
        digest = hashlib.sha256(canonical_payload)
        turn_dir = self.data_dir / "turns" / conversation_id
        if turn_dir.is_dir():
            for path in sorted(turn_dir.glob("*.json")):
                try:
                    digest.update(path.name.encode("utf-8"))
                    digest.update(path.read_bytes())
                except OSError:
                    continue
        return digest.hexdigest()

    @staticmethod
    def _step_duration(message: Dict[str, Any]) -> int:
        metadata = message.get("metadata") or {}
        explicit = metadata.get("total_execution_time_ms")
        if explicit is not None:
            return int(explicit or 0)
        steps = metadata.get("steps") or []
        if steps:
            return sum(int(step.get("duration_ms") or 0) for step in steps)
        payloads = [*(message.get("stage1") or []), *(message.get("stage2") or [])]
        if message.get("stage3"):
            payloads.append(message["stage3"])
        return sum(int(step.get("duration_ms") or 0) for step in payloads)

    def project(
        self,
        conversation: Dict[str, Any],
        *,
        checksum: str,
        file_mtime: Optional[float] = None,
    ) -> SessionCatalogEntry:
        messages = list(conversation.get("messages") or [])
        assistants = [message for message in messages if message.get("role") == "assistant"]
        users = [message for message in messages if message.get("role") == "user"]
        sidecars = self.turn_sidecars(str(conversation["id"]))
        costs = summarize_conversation_cost(messages)

        qualities = [
            str(((message.get("metadata") or {}).get("execution_quality") or {}).get("severity") or "unknown")
            for message in assistants
        ]
        latest_quality = qualities[-1] if qualities else "unknown"
        worst_quality = max(qualities or ["unknown"], key=lambda value: _QUALITY_RANK.get(value, 0))
        failure_count = sum(
            len((message.get("metadata") or {}).get("model_failures") or [])
            for message in assistants
        )

        latest_metadata = (assistants[-1].get("metadata") or {}) if assistants else {}
        arena_models = list(latest_metadata.get("arena_models") or [])
        chairman_model = str(latest_metadata.get("chairman_model") or "")
        fingerprint = str(latest_metadata.get("squad_fingerprint") or "")
        if not fingerprint and (arena_models or chairman_model):
            fingerprint = f"{chairman_model}::{'|'.join(sorted(arena_models))}"

        active_sidecar = next(
            (
                turn
                for turn in reversed(sidecars)
                if str(turn.get("status") or "") in _ACTIVE_TURN_STATUSES
            ),
            None,
        )
        if active_sidecar:
            status = "running"
        elif sidecars and str(sidecars[-1].get("status") or "") == "failed":
            status = "failed"
        elif len(users) > len(assistants):
            status = "pending"
        elif latest_quality == "failed":
            status = "failed"
        elif latest_quality == "degraded":
            status = "degraded"
        elif assistants:
            status = "complete"
        else:
            status = "idle"

        created_at = str(conversation.get("created_at") or "")
        fallback_updated = created_at
        if file_mtime is not None:
            fallback_updated = datetime.fromtimestamp(file_mtime, timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        updated_candidates = [str(conversation.get("updated_at") or fallback_updated)]
        updated_candidates.extend(
            str(turn.get("updated_at") or turn.get("created_at") or "") for turn in sidecars
        )
        updated_at = max(value for value in updated_candidates if value)

        last_sidecar = next((turn for turn in reversed(sidecars) if turn.get("agent_id")), None)
        origin = str(conversation.get("origin") or "unknown")
        originator = str(conversation.get("originator") or origin or "unknown")
        conversation_caller_at = str(
            conversation.get("last_caller_at") or conversation.get("updated_at") or created_at
        )
        sidecar_caller_at = str(
            (last_sidecar or {}).get("updated_at")
            or (last_sidecar or {}).get("created_at")
            or ""
        )
        if last_sidecar and sidecar_caller_at >= conversation_caller_at:
            last_caller = str(last_sidecar["agent_id"])
        else:
            last_caller = str(conversation.get("last_caller") or originator)

        return SessionCatalogEntry(
            id=str(conversation["id"]),
            created_at=created_at,
            updated_at=updated_at,
            title=str(conversation.get("title") or "New Conversation"),
            mode=str(conversation.get("mode") or "council"),
            origin=origin,
            originator=originator,
            last_caller=last_caller,
            turn_count=max(len(users), len(assistants), len(sidecars)),
            message_count=len(messages),
            status=status,
            latest_quality=latest_quality,
            worst_quality=worst_quality,
            total_cost_usd=float(costs.get("conversation_cost_usd") or 0.0),
            total_tokens=int(costs.get("total_tokens") or 0),
            total_calls=int(costs.get("calls") or 0),
            failure_count=failure_count,
            duration_ms=sum(self._step_duration(message) for message in assistants),
            squad_name=str(latest_metadata.get("arena_squad") or ""),
            squad_fingerprint=fingerprint,
            arena_models=arena_models,
            chairman_model=chairman_model,
            rag_used=any(bool(message.get("context_sources")) for message in assistants),
            repository=str(conversation.get("repository") or ""),
            source_revision=int(conversation.get("storage_revision") or 0),
            source_checksum=checksum,
        )
