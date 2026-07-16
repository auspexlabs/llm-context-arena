"""Canonical conversation storage with a queryable session projection."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from .config import DATA_DIR
from .session_catalog import SessionCatalog, SessionCatalogEntry, SessionQuery
from .session_projection import SessionProjector

try:  # POSIX inter-process locking.
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows.
    fcntl = None  # type: ignore[assignment]

try:  # Windows inter-process locking.
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX.
    msvcrt = None  # type: ignore[assignment]


def utc_now() -> str:
    """Return a stable, sortable UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def caller_label(caller: Optional[str], origin: Optional[str]) -> str:
    """Use a supplied agent identity, otherwise retain the channel identity."""
    return str(caller or origin or "unknown").strip() or "unknown"


class StorageService:
    """Own conversation JSON mutation and its rebuildable session catalog."""

    def __init__(
        self,
        data_dir: str = DATA_DIR,
        catalog_path: Optional[str] = None,
        *,
        reconcile: bool = True,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._locks_dir = self.data_dir / ".locks"
        self._locks_dir.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self.projector = SessionProjector(self.data_dir)
        default_catalog = self.data_dir.parent / "session_catalog.db"
        self.catalog = SessionCatalog(Path(catalog_path) if catalog_path else default_catalog)
        if reconcile:
            self.reconcile_catalog()

    def _get_conversation_path(self, conversation_id: str) -> Path:
        return self.data_dir / f"{conversation_id}.json"

    @contextmanager
    def _conversation_lock(self, conversation_id: str) -> Iterator[None]:
        """Serialize read-modify-write cycles across threads and worker processes."""
        # A fixed stripe set bounds lock-file growth while preserving stable
        # cross-process lock identities. Hash collisions only serialize writes.
        stripe = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()[:2]
        lock_path = self._locks_dir / f"{stripe}.lock"
        with self._thread_lock, lock_path.open("a+b") as handle:
            self._lock_handle(handle)
            try:
                yield
            finally:
                self._unlock_handle(handle)

    @staticmethod
    def _lock_handle(handle: Any) -> None:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            return
        if msvcrt is None:  # pragma: no cover - unsupported Python platform.
            raise RuntimeError("Curia requires OS-backed file locking")
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

    @staticmethod
    def _unlock_handle(handle: Any) -> None:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return
        if msvcrt is not None:  # pragma: no branch - Windows counterpart above.
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    @staticmethod
    def _serialize(conversation: Dict[str, Any]) -> bytes:
        return (json.dumps(conversation, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    def _atomic_replace(self, path: Path, payload: bytes) -> None:
        """Durably replace one canonical JSON file without exposing partial data."""
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
            if os.name != "nt":
                dir_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _read_path(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _project_path(self, path: Path) -> Optional[SessionCatalogEntry]:
        try:
            payload = path.read_bytes()
            conversation = json.loads(payload)
            return self.projector.project(
                conversation,
                checksum=self.projector.checksum(payload, str(conversation["id"])),
                file_mtime=path.stat().st_mtime,
            )
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def _persist_locked(self, conversation: Dict[str, Any]) -> None:
        path = self._get_conversation_path(str(conversation["id"]))
        payload = self._serialize(conversation)
        entry = self.projector.project(
            conversation,
            checksum=self.projector.checksum(payload, str(conversation["id"])),
        )
        self.catalog.prepare_upsert(entry)
        self._atomic_replace(path, payload)
        self.catalog.commit_upsert(entry)

    def _mutate(
        self,
        conversation_id: str,
        change: Callable[[Dict[str, Any]], None],
        *,
        caller: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._conversation_lock(conversation_id):
            conversation = self._read_path(self._get_conversation_path(conversation_id))
            if conversation is None:
                raise ValueError(f"Conversation {conversation_id} not found")
            change(conversation)
            conversation["updated_at"] = utc_now()
            conversation["storage_revision"] = int(conversation.get("storage_revision") or 0) + 1
            if origin:
                conversation.setdefault("origin", origin)
            if caller or origin:
                conversation["last_caller"] = caller_label(caller, origin)
                conversation["last_caller_at"] = conversation["updated_at"]
            self._persist_locked(conversation)
            return conversation

    def create_conversation(
        self,
        conversation_id: str,
        mode: str = "council",
        *,
        caller: Optional[str] = None,
        origin: str = "api",
    ) -> Dict[str, Any]:
        now = utc_now()
        identity = caller_label(caller, origin)
        conversation = {
            "id": conversation_id,
            "created_at": now,
            "updated_at": now,
            "storage_revision": 1,
            "title": "New Conversation",
            "messages": [],
            "mode": mode,
            "origin": origin,
            "originator": identity,
            "last_caller": identity,
            "last_caller_at": now,
        }
        with self._conversation_lock(conversation_id):
            if self._get_conversation_path(conversation_id).exists():
                raise ValueError(f"Conversation {conversation_id} already exists")
            self._persist_locked(conversation)
        return conversation

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        return self._read_path(self._get_conversation_path(conversation_id))

    def save_conversation(
        self,
        conversation: Dict[str, Any],
        *,
        caller: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> None:
        conversation_id = str(conversation["id"])
        with self._conversation_lock(conversation_id):
            conversation["updated_at"] = utc_now()
            conversation["storage_revision"] = int(conversation.get("storage_revision") or 0) + 1
            if origin:
                conversation.setdefault("origin", origin)
            if caller or origin:
                conversation["last_caller"] = caller_label(caller, origin)
                conversation["last_caller_at"] = conversation["updated_at"]
            self._persist_locked(conversation)

    def list_conversations(self) -> List[Dict[str, Any]]:
        return self.catalog.all_legacy()

    def list_sessions(self, query: SessionQuery) -> Dict[str, Any]:
        return self.catalog.query(query)

    def reconcile_catalog(self) -> Dict[str, int]:
        paths = sorted(self.data_dir.glob("*.json"))
        return self.catalog.reconcile(paths, self._project_path)

    def refresh_catalog(self, conversation_id: str) -> None:
        """Refresh sidecar-derived state without mutating canonical conversation JSON."""
        with self._conversation_lock(conversation_id):
            path = self._get_conversation_path(conversation_id)
            entry = self._project_path(path)
            if entry is not None:
                self.catalog.prepare_upsert(entry)
                self.catalog.commit_upsert(entry)

    def add_user_message(
        self,
        conversation_id: str,
        content: str,
        *,
        caller: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> None:
        def append(conversation: Dict[str, Any]) -> None:
            conversation.setdefault("messages", []).append({"role": "user", "content": content})

        self._mutate(conversation_id, append, caller=caller, origin=origin)

    def add_assistant_message(
        self,
        conversation_id: str,
        stage1: List[Dict[str, Any]],
        stage2: List[Dict[str, Any]],
        stage3: Dict[str, Any],
        context_sources: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        caller: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> None:
        def append(conversation: Dict[str, Any]) -> None:
            conversation.setdefault("messages", []).append(
                {
                    "role": "assistant",
                    "stage1": stage1,
                    "stage2": stage2,
                    "stage3": stage3,
                    "context_sources": context_sources or [],
                    "metadata": metadata or {},
                }
            )

        self._mutate(conversation_id, append, caller=caller, origin=origin)

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        self._mutate(conversation_id, lambda conversation: conversation.update(title=title))

    def set_repository(self, conversation_id: str, repository: str) -> None:
        self._mutate(
            conversation_id,
            lambda conversation: conversation.update(repository=repository),
        )

    def reset_conversation(self, conversation_id: str) -> None:
        self._mutate(
            conversation_id,
            lambda conversation: conversation.update(messages=[]),
        )

    def delete_conversation(self, conversation_id: str) -> bool:
        path = self._get_conversation_path(conversation_id)
        with self._conversation_lock(conversation_id):
            if not path.exists():
                return False
            conversation = self._read_path(path) or {}
            revision = int(conversation.get("storage_revision") or 0) + 1
            self.catalog.prepare_delete(conversation_id, revision)
            path.unlink()
            self.catalog.commit_delete(conversation_id)
        return True
