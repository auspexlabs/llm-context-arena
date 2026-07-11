"""SQLite observation store — pending, accepted, history, archive (DEC-018 B3)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "observations.db"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PendingObservation:
    id: int
    model_id: str
    registered_limit: int
    observed_limit: int
    delta_ratio: float
    prompt_tokens: Optional[int]
    failure_reason: Optional[str]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "model_id": self.model_id,
            "registered_limit": self.registered_limit,
            "observed_limit": self.observed_limit,
            "delta_ratio": self.delta_ratio,
            "prompt_tokens": self.prompt_tokens,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AcceptedObservation:
    model_id: str
    observed_limit: int
    registered_limit: int
    accepted_at: str
    expires_at: str
    source_pending_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "observed_limit": self.observed_limit,
            "registered_limit": self.registered_limit,
            "accepted_at": self.accepted_at,
            "expires_at": self.expires_at,
            "source_pending_id": self.source_pending_id,
        }


class ObservationStore:
    """Append-only observation ledger with pending + accepted tables."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS observation_pending (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    registered_limit INTEGER NOT NULL,
                    observed_limit INTEGER NOT NULL,
                    delta_ratio REAL NOT NULL,
                    prompt_tokens INTEGER,
                    failure_reason TEXT,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS observation_accepted (
                    model_id TEXT PRIMARY KEY,
                    observed_limit INTEGER NOT NULL,
                    registered_limit INTEGER NOT NULL,
                    accepted_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    source_pending_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS observation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    registered_limit INTEGER,
                    observed_limit INTEGER,
                    delta_ratio REAL,
                    created_at TEXT NOT NULL,
                    details TEXT
                );
                CREATE TABLE IF NOT EXISTS observation_archive (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    observed_limit INTEGER NOT NULL,
                    registered_limit INTEGER NOT NULL,
                    accepted_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    source_pending_id INTEGER
                );
                """
            )

    def list_pending(self) -> List[PendingObservation]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, model_id, registered_limit, observed_limit, delta_ratio,
                       prompt_tokens, failure_reason, created_at
                FROM observation_pending
                WHERE status = 'pending'
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._row_pending(r) for r in rows]

    def get_pending(self, obs_id: int) -> Optional[PendingObservation]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, model_id, registered_limit, observed_limit, delta_ratio,
                       prompt_tokens, failure_reason, created_at
                FROM observation_pending
                WHERE id = ? AND status = 'pending'
                """,
                (obs_id,),
            ).fetchone()
        return self._row_pending(row) if row else None

    def get_accepted(self, model_id: str) -> Optional[AcceptedObservation]:
        now = _utcnow()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT model_id, observed_limit, registered_limit, accepted_at,
                       expires_at, source_pending_id
                FROM observation_accepted
                WHERE model_id = ? AND expires_at > ?
                """,
                (model_id, now),
            ).fetchone()
        return self._row_accepted(row) if row else None

    def list_accepted(self) -> List[AcceptedObservation]:
        now = _utcnow()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT model_id, observed_limit, registered_limit, accepted_at,
                       expires_at, source_pending_id
                FROM observation_accepted
                WHERE expires_at > ?
                ORDER BY model_id
                """,
                (now,),
            ).fetchall()
        return [self._row_accepted(r) for r in rows]

    def accepted_limits_map(self) -> Dict[str, int]:
        """Non-expired accepted limits in one query."""
        now = _utcnow()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT model_id, observed_limit
                FROM observation_accepted
                WHERE expires_at > ?
                """,
                (now,),
            ).fetchall()
        return {str(row["model_id"]): int(row["observed_limit"]) for row in rows}

    def propose(
        self,
        *,
        model_id: str,
        registered_limit: int,
        observed_limit: int,
        prompt_tokens: Optional[int] = None,
        failure_reason: Optional[str] = None,
    ) -> Optional[PendingObservation]:
        if registered_limit <= 0:
            return None
        delta_ratio = abs(observed_limit - registered_limit) / registered_limit
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM observation_pending
                WHERE model_id = ? AND status = 'pending'
                  AND observed_limit = ? AND registered_limit = ?
                """,
                (model_id, observed_limit, registered_limit),
            ).fetchone()
            if existing:
                return self.get_pending(int(existing["id"]))

            now = _utcnow()
            cur = conn.execute(
                """
                INSERT INTO observation_pending
                (model_id, registered_limit, observed_limit, delta_ratio,
                 prompt_tokens, failure_reason, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    model_id,
                    registered_limit,
                    observed_limit,
                    delta_ratio,
                    prompt_tokens,
                    failure_reason,
                    now,
                ),
            )
            obs_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO observation_history
                (model_id, action, registered_limit, observed_limit, delta_ratio, created_at, details)
                VALUES (?, 'proposed', ?, ?, ?, ?, ?)
                """,
                (model_id, registered_limit, observed_limit, delta_ratio, now, None),
            )
        return self.get_pending(obs_id)

    def accept(self, obs_id: int, ttl_days: int) -> Optional[AcceptedObservation]:
        pending = self.get_pending(obs_id)
        if pending is None:
            return None
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=ttl_days)
        accepted_at = now.isoformat()
        expires_at = expires.isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE observation_pending SET status = 'accepted' WHERE id = ?",
                (obs_id,),
            )
            conn.execute(
                """
                INSERT INTO observation_accepted
                (model_id, observed_limit, registered_limit, accepted_at, expires_at, source_pending_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                    observed_limit = excluded.observed_limit,
                    registered_limit = excluded.registered_limit,
                    accepted_at = excluded.accepted_at,
                    expires_at = excluded.expires_at,
                    source_pending_id = excluded.source_pending_id
                """,
                (
                    pending.model_id,
                    pending.observed_limit,
                    pending.registered_limit,
                    accepted_at,
                    expires_at,
                    obs_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO observation_history
                (model_id, action, registered_limit, observed_limit, delta_ratio, created_at, details)
                VALUES (?, 'accepted', ?, ?, ?, ?, ?)
                """,
                (
                    pending.model_id,
                    pending.registered_limit,
                    pending.observed_limit,
                    pending.delta_ratio,
                    accepted_at,
                    f"pending_id={obs_id}",
                ),
            )
        return self.get_accepted(pending.model_id)

    def decline(self, obs_id: int) -> bool:
        pending = self.get_pending(obs_id)
        if pending is None:
            return False
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                "UPDATE observation_pending SET status = 'declined' WHERE id = ?",
                (obs_id,),
            )
            conn.execute(
                """
                INSERT INTO observation_history
                (model_id, action, registered_limit, observed_limit, delta_ratio, created_at, details)
                VALUES (?, 'declined', ?, ?, ?, ?, ?)
                """,
                (
                    pending.model_id,
                    pending.registered_limit,
                    pending.observed_limit,
                    pending.delta_ratio,
                    now,
                    f"pending_id={obs_id}",
                ),
            )
        return True

    @staticmethod
    def _row_pending(row: sqlite3.Row) -> PendingObservation:
        return PendingObservation(
            id=int(row["id"]),
            model_id=str(row["model_id"]),
            registered_limit=int(row["registered_limit"]),
            observed_limit=int(row["observed_limit"]),
            delta_ratio=float(row["delta_ratio"]),
            prompt_tokens=row["prompt_tokens"],
            failure_reason=row["failure_reason"],
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_accepted(row: sqlite3.Row) -> AcceptedObservation:
        return AcceptedObservation(
            model_id=str(row["model_id"]),
            observed_limit=int(row["observed_limit"]),
            registered_limit=int(row["registered_limit"]),
            accepted_at=str(row["accepted_at"]),
            expires_at=str(row["expires_at"]),
            source_pending_id=row["source_pending_id"],
        )


@lru_cache(maxsize=1)
def get_observation_store(db_path: str = str(DEFAULT_DB_PATH)) -> ObservationStore:
    return ObservationStore(Path(db_path))