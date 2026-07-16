"""Queryable projection of conversation history for the Sessions surface."""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


CATALOG_VERSION = 1
SORT_COLUMNS = {
    "updated_desc": "updated_at",
    "created_desc": "created_at",
    "cost_desc": "total_cost_usd",
}
FACET_COLUMNS = {
    "mode",
    "last_caller",
    "origin",
    "status",
    "latest_quality",
    "squad_name",
}
LEGACY_SESSION_LIMIT = 500
SQLITE_BIND_BATCH = 500


@dataclass(frozen=True)
class SessionCatalogEntry:
    """One denormalized session row derived from canonical conversation JSON."""

    id: str
    created_at: str
    updated_at: str
    title: str
    mode: str
    origin: str = "unknown"
    originator: str = "unknown"
    last_caller: str = "unknown"
    turn_count: int = 0
    message_count: int = 0
    status: str = "idle"
    latest_quality: str = "unknown"
    worst_quality: str = "unknown"
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_calls: int = 0
    failure_count: int = 0
    duration_ms: int = 0
    squad_name: str = ""
    squad_fingerprint: str = ""
    arena_models: List[str] = field(default_factory=list)
    chairman_model: str = ""
    rag_used: bool = False
    repository: str = ""
    source_revision: int = 0
    source_checksum: str = ""

    def to_public_dict(self) -> Dict[str, Any]:
        row = asdict(self)
        row.pop("source_revision", None)
        row.pop("source_checksum", None)
        return row


@dataclass(frozen=True)
class SessionQuery:
    """Server-side filters and cursor controls for a session page."""

    limit: int = 50
    cursor: Optional[str] = None
    mode: Optional[str] = None
    caller: Optional[str] = None
    origin: Optional[str] = None
    status: Optional[str] = None
    quality: Optional[str] = None
    squad: Optional[str] = None
    from_at: Optional[str] = None
    to_at: Optional[str] = None
    sort: str = "updated_desc"


class InvalidSessionCursor(ValueError):
    """Raised when a session cursor cannot safely be applied."""


class SessionCatalog:
    """SQLite projection with recoverable write intents and keyset queries."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    originator TEXT NOT NULL,
                    last_caller TEXT NOT NULL,
                    turn_count INTEGER NOT NULL,
                    message_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    latest_quality TEXT NOT NULL,
                    worst_quality TEXT NOT NULL,
                    total_cost_usd REAL NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    total_calls INTEGER NOT NULL,
                    failure_count INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    squad_name TEXT NOT NULL,
                    squad_fingerprint TEXT NOT NULL,
                    arena_models_json TEXT NOT NULL,
                    chairman_model TEXT NOT NULL,
                    rag_used INTEGER NOT NULL,
                    repository TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,
                    source_checksum TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_updated
                    ON sessions(updated_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_sessions_created
                    ON sessions(created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_sessions_cost
                    ON sessions(total_cost_usd DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_sessions_mode ON sessions(mode);
                CREATE INDEX IF NOT EXISTS idx_sessions_caller ON sessions(last_caller);
                CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
                CREATE INDEX IF NOT EXISTS idx_sessions_quality ON sessions(latest_quality);
                CREATE INDEX IF NOT EXISTS idx_sessions_squad ON sessions(squad_name);
                CREATE TABLE IF NOT EXISTS session_write_intents (
                    conversation_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,
                    source_checksum TEXT NOT NULL,
                    entry_json TEXT NOT NULL
                );
                """
            )
            connection.execute(f"PRAGMA user_version = {CATALOG_VERSION}")

    @staticmethod
    def _db_values(entry: SessionCatalogEntry) -> Tuple[Any, ...]:
        return (
            entry.id,
            entry.created_at,
            entry.updated_at,
            entry.title,
            entry.mode,
            entry.origin,
            entry.originator,
            entry.last_caller,
            entry.turn_count,
            entry.message_count,
            entry.status,
            entry.latest_quality,
            entry.worst_quality,
            entry.total_cost_usd,
            entry.total_tokens,
            entry.total_calls,
            entry.failure_count,
            entry.duration_ms,
            entry.squad_name,
            entry.squad_fingerprint,
            json.dumps(entry.arena_models, separators=(",", ":")),
            entry.chairman_model,
            int(entry.rag_used),
            entry.repository,
            entry.source_revision,
            entry.source_checksum,
        )

    @staticmethod
    def _upsert(connection: sqlite3.Connection, entry: SessionCatalogEntry) -> None:
        connection.execute(
            """
            INSERT INTO sessions (
                id, created_at, updated_at, title, mode, origin, originator,
                last_caller, turn_count, message_count, status, latest_quality,
                worst_quality, total_cost_usd, total_tokens, total_calls,
                failure_count, duration_ms, squad_name, squad_fingerprint,
                arena_models_json, chairman_model, rag_used, repository,
                source_revision, source_checksum
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                title=excluded.title,
                mode=excluded.mode,
                origin=excluded.origin,
                originator=excluded.originator,
                last_caller=excluded.last_caller,
                turn_count=excluded.turn_count,
                message_count=excluded.message_count,
                status=excluded.status,
                latest_quality=excluded.latest_quality,
                worst_quality=excluded.worst_quality,
                total_cost_usd=excluded.total_cost_usd,
                total_tokens=excluded.total_tokens,
                total_calls=excluded.total_calls,
                failure_count=excluded.failure_count,
                duration_ms=excluded.duration_ms,
                squad_name=excluded.squad_name,
                squad_fingerprint=excluded.squad_fingerprint,
                arena_models_json=excluded.arena_models_json,
                chairman_model=excluded.chairman_model,
                rag_used=excluded.rag_used,
                repository=excluded.repository,
                source_revision=excluded.source_revision,
                source_checksum=excluded.source_checksum
            WHERE excluded.source_revision > sessions.source_revision
               OR (
                    excluded.source_revision = sessions.source_revision
                    AND excluded.updated_at >= sessions.updated_at
               )
            """,
            SessionCatalog._db_values(entry),
        )

    def prepare_upsert(self, entry: SessionCatalogEntry) -> None:
        """Persist intent before the canonical JSON replacement begins."""
        payload = json.dumps(asdict(entry), separators=(",", ":"), sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO session_write_intents (
                    conversation_id, operation, source_revision,
                    source_checksum, entry_json
                ) VALUES (?, 'upsert', ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    operation=excluded.operation,
                    source_revision=excluded.source_revision,
                    source_checksum=excluded.source_checksum,
                    entry_json=excluded.entry_json
                """,
                (entry.id, entry.source_revision, entry.source_checksum, payload),
            )

    def commit_upsert(self, entry: SessionCatalogEntry) -> None:
        """Publish the projection and clear its completed write intent."""
        with self._connect() as connection:
            self._upsert(connection, entry)
            connection.execute(
                "DELETE FROM session_write_intents WHERE conversation_id = ?",
                (entry.id,),
            )

    def prepare_delete(self, conversation_id: str, source_revision: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO session_write_intents (
                    conversation_id, operation, source_revision,
                    source_checksum, entry_json
                ) VALUES (?, 'delete', ?, '', '')
                ON CONFLICT(conversation_id) DO UPDATE SET
                    operation='delete', source_revision=excluded.source_revision,
                    source_checksum='', entry_json=''
                """,
                (conversation_id, source_revision),
            )

    def commit_delete(self, conversation_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (conversation_id,))
            connection.execute(
                "DELETE FROM session_write_intents WHERE conversation_id = ?",
                (conversation_id,),
            )

    def reconcile(
        self,
        conversation_paths: Iterable[Path],
        projector: Callable[[Path], Optional[SessionCatalogEntry]],
    ) -> Dict[str, int]:
        """Repair stale/missing rows and remove catalog rows without canonical JSON."""
        paths = list(conversation_paths)
        canonical_ids = {path.stem for path in paths}
        repaired = skipped = removed = 0
        reconciled_ids: set[str] = set()
        with self._connect() as connection:
            known = {
                str(row["id"]): str(row["source_checksum"])
                for row in connection.execute("SELECT id, source_checksum FROM sessions")
            }
            for path in paths:
                entry = projector(path)
                if entry is None:
                    continue
                reconciled_ids.add(entry.id)
                if known.get(entry.id) == entry.source_checksum:
                    skipped += 1
                    continue
                self._upsert(connection, entry)
                repaired += 1
            stale = set(known) - canonical_ids
            for conversation_id in stale:
                connection.execute("DELETE FROM sessions WHERE id = ?", (conversation_id,))
                connection.execute(
                    "DELETE FROM session_write_intents WHERE conversation_id = ?",
                    (conversation_id,),
                )
                removed += 1
            if reconciled_ids:
                reconciled_list = list(reconciled_ids)
                for offset in range(0, len(reconciled_list), SQLITE_BIND_BATCH):
                    batch = reconciled_list[offset : offset + SQLITE_BIND_BATCH]
                    placeholders = ",".join("?" for _ in batch)
                    connection.execute(
                        "DELETE FROM session_write_intents "
                        f"WHERE conversation_id IN ({placeholders})",
                        batch,
                    )
        return {"repaired": repaired, "skipped": skipped, "removed": removed}

    @staticmethod
    def _encode_cursor(sort: str, value: Any, conversation_id: str) -> str:
        raw = json.dumps([sort, value, conversation_id], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str, expected_sort: str) -> Tuple[Any, str]:
        try:
            padding = "=" * (-len(cursor) % 4)
            decoded = json.loads(
                base64.urlsafe_b64decode(cursor + padding).decode()
            )
            if not isinstance(decoded, list) or len(decoded) != 3:
                raise ValueError("unexpected cursor shape")
            sort, value, conversation_id = decoded
        except Exception as exc:
            raise InvalidSessionCursor("Malformed session cursor") from exc
        value_is_valid = (
            isinstance(value, (int, float)) and not isinstance(value, bool)
            if expected_sort == "cost_desc"
            else isinstance(value, str)
        )
        if (
            sort != expected_sort
            or not value_is_valid
            or not isinstance(conversation_id, str)
            or not conversation_id
        ):
            raise InvalidSessionCursor("Session cursor does not match the requested sort")
        return value, conversation_id

    @staticmethod
    def _public_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "title": row["title"],
            "mode": row["mode"],
            "origin": row["origin"],
            "originator": row["originator"],
            "last_caller": row["last_caller"],
            "turn_count": row["turn_count"],
            "message_count": row["message_count"],
            "status": row["status"],
            "latest_quality": row["latest_quality"],
            "worst_quality": row["worst_quality"],
            "total_cost_usd": row["total_cost_usd"],
            "total_tokens": row["total_tokens"],
            "total_calls": row["total_calls"],
            "failure_count": row["failure_count"],
            "duration_ms": row["duration_ms"],
            "squad_name": row["squad_name"],
            "squad_fingerprint": row["squad_fingerprint"],
            "arena_models": json.loads(row["arena_models_json"] or "[]"),
            "chairman_model": row["chairman_model"],
            "rag_used": bool(row["rag_used"]),
            "repository": row["repository"],
        }

    def query(self, query: SessionQuery) -> Dict[str, Any]:
        sort = query.sort if query.sort in SORT_COLUMNS else "updated_desc"
        sort_column = SORT_COLUMNS[sort]
        limit = min(100, max(1, int(query.limit)))
        clauses: List[str] = []
        values: List[Any] = []
        filters: Sequence[Tuple[str, Optional[str]]] = (
            ("mode", query.mode),
            ("last_caller", query.caller),
            ("origin", query.origin),
            ("status", query.status),
            ("latest_quality", query.quality),
            ("squad_name", query.squad),
        )
        for column, value in filters:
            if value:
                clauses.append(f"{column} = ?")
                values.append(value)
        if query.from_at:
            clauses.append("updated_at >= ?")
            values.append(query.from_at)
        if query.to_at:
            clauses.append("updated_at <= ?")
            values.append(query.to_at)
        filter_where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

        page_clauses = list(clauses)
        page_values = list(values)
        if query.cursor:
            cursor_value, cursor_id = self._decode_cursor(query.cursor, sort)
            page_clauses.append(
                f"({sort_column} < ? OR ({sort_column} = ? AND id < ?))"
            )
            page_values.extend([cursor_value, cursor_value, cursor_id])
        page_where = f" WHERE {' AND '.join(page_clauses)}" if page_clauses else ""

        with self._connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM sessions{filter_where}", values
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"SELECT * FROM sessions{page_where} "
                f"ORDER BY {sort_column} DESC, id DESC LIMIT ?",
                [*page_values, limit + 1],
            ).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
            items = [self._public_row(row) for row in rows]
            next_cursor = None
            if has_more and rows:
                tail = rows[-1]
                next_cursor = self._encode_cursor(sort, tail[sort_column], tail["id"])
            facets = {
                "modes": self._distinct(connection, "mode"),
                "callers": self._distinct(connection, "last_caller"),
                "origins": self._distinct(connection, "origin"),
                "statuses": self._distinct(connection, "status"),
                "qualities": self._distinct(connection, "latest_quality"),
                "squads": self._distinct(connection, "squad_name", omit_empty=True),
            }
        return {
            "items": items,
            "next_cursor": next_cursor,
            "total": total,
            "facets": facets,
            "sort": sort,
        }

    @staticmethod
    def _distinct(
        connection: sqlite3.Connection,
        column: str,
        *,
        omit_empty: bool = False,
    ) -> List[str]:
        if column not in FACET_COLUMNS:
            raise ValueError(f"Unsupported session facet: {column}")
        where = f" WHERE {column} <> ''" if omit_empty else ""
        return [
            str(row[0])
            for row in connection.execute(
                f"SELECT DISTINCT {column} FROM sessions{where} ORDER BY {column}"
            )
            if row[0] is not None
        ]

    def all_legacy(self, limit: int = LEGACY_SESSION_LIMIT) -> List[Dict[str, Any]]:
        """Bounded compatibility view for the superseded conversation-list API."""
        bounded_limit = min(LEGACY_SESSION_LIMIT, max(1, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC, id DESC LIMIT ?",
                (bounded_limit,),
            ).fetchall()
        return [self._public_row(row) for row in rows]
