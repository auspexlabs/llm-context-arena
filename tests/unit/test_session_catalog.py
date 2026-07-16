import json
import sqlite3
from dataclasses import replace

import pytest

from backend.session_catalog import (
    InvalidSessionCursor,
    SessionCatalogEntry,
    SessionQuery,
)
from backend.storage_service import StorageService


def _storage(tmp_path):
    return StorageService(data_dir=str(tmp_path / "conversations"))


def test_catalog_projects_useful_session_metadata(tmp_path):
    storage = _storage(tmp_path)
    conversation = storage.create_conversation(
        "conv-1", mode="fight", caller="codex-dogfood", origin="mcp"
    )
    conversation["repository"] = "/srv/curia"
    conversation["messages"] = [
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "stage1": [],
            "stage2": [],
            "stage3": {"model": "chair/model", "response": "answer"},
            "context_sources": [{"source": "backend/main.py"}],
            "metadata": {
                "arena_models": ["vendor/z", "vendor/a"],
                "chairman_model": "chair/model",
                "arena_squad": "cheap-pros",
                "cost": {
                    "turn_cost_usd": 0.125,
                    "total_tokens": 321,
                    "calls": 3,
                },
                "steps": [{"duration_ms": 800}, {"duration_ms": 200}],
                "model_failures": [{"model": "vendor/z"}],
                "execution_quality": {"severity": "degraded"},
            },
        },
    ]
    storage.save_conversation(conversation, caller="codex-dogfood", origin="mcp")

    page = storage.list_sessions(SessionQuery())

    [session] = page["items"]
    assert session["id"] == "conv-1"
    assert session["turn_count"] == 1
    assert session["last_caller"] == "codex-dogfood"
    assert session["origin"] == "mcp"
    assert session["status"] == "degraded"
    assert session["latest_quality"] == "degraded"
    assert session["total_cost_usd"] == 0.125
    assert session["total_tokens"] == 321
    assert session["total_calls"] == 3
    assert session["failure_count"] == 1
    assert session["duration_ms"] == 1000
    assert session["squad_name"] == "cheap-pros"
    assert session["squad_fingerprint"] == "chair/model::vendor/a|vendor/z"
    assert session["rag_used"] is True
    assert session["repository"] == "/srv/curia"


def test_interrupted_projection_commit_is_repaired_on_restart(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    storage.create_conversation("conv-1")

    def fail_commit(_entry):
        raise RuntimeError("simulated catalog interruption")

    monkeypatch.setattr(storage.catalog, "commit_upsert", fail_commit)
    with pytest.raises(RuntimeError, match="simulated"):
        storage.add_user_message("conv-1", "persisted canonical message")

    canonical = json.loads((tmp_path / "conversations" / "conv-1.json").read_text())
    assert canonical["messages"][0]["content"] == "persisted canonical message"

    repaired = _storage(tmp_path)
    [session] = repaired.list_sessions(SessionQuery())["items"]
    assert session["message_count"] == 1
    with sqlite3.connect(tmp_path / "session_catalog.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM session_write_intents").fetchone()[0] == 0


def test_filtered_cursor_pages_are_stable_and_url_safe(tmp_path):
    storage = _storage(tmp_path)
    for index in range(5):
        storage.create_conversation(
            f"conv-{index}",
            mode="fight" if index < 4 else "council",
            caller="codex" if index % 2 == 0 else "grok",
            origin="mcp",
        )

    first = storage.list_sessions(SessionQuery(limit=2, mode="fight", sort="created_desc"))
    assert len(first["items"]) == 2
    assert first["total"] == 4
    assert first["next_cursor"]
    assert " " not in first["next_cursor"]

    second = storage.list_sessions(
        SessionQuery(
            limit=2,
            mode="fight",
            sort="created_desc",
            cursor=first["next_cursor"],
        )
    )
    ids = [row["id"] for row in [*first["items"], *second["items"]]]
    assert len(ids) == len(set(ids)) == 4

    codex = storage.list_sessions(SessionQuery(caller="codex"))
    assert {row["last_caller"] for row in codex["items"]} == {"codex"}

    with pytest.raises(InvalidSessionCursor):
        storage.list_sessions(SessionQuery(cursor="not-a-cursor"))


def test_turn_sidecar_refresh_updates_session_state_and_caller(tmp_path):
    storage = _storage(tmp_path)
    storage.create_conversation("conv-1")
    turn_dir = tmp_path / "conversations" / "turns" / "conv-1"
    turn_dir.mkdir(parents=True)
    (turn_dir / "turn-1.json").write_text(
        json.dumps(
            {
                "turn_id": "turn-1",
                "conversation_id": "conv-1",
                "agent_id": "grok-test",
                "status": "stage1_complete",
                "created_at": "2099-07-15T10:00:00Z",
                "updated_at": "2099-07-15T10:01:00Z",
            }
        )
    )

    storage.refresh_catalog("conv-1")
    [session] = storage.list_sessions(SessionQuery())["items"]
    assert session["status"] == "running"
    assert session["last_caller"] == "grok-test"


def test_startup_reconciliation_detects_sidecar_only_changes(tmp_path):
    storage = _storage(tmp_path)
    storage.create_conversation("conv-1")
    turn_dir = tmp_path / "conversations" / "turns" / "conv-1"
    turn_dir.mkdir(parents=True)
    (turn_dir / "turn-1.json").write_text(
        json.dumps(
            {
                "turn_id": "turn-1",
                "conversation_id": "conv-1",
                "agent_id": "codex",
                "status": "pending",
                "updated_at": "2099-07-15T10:01:00Z",
            }
        )
    )

    restarted = _storage(tmp_path)
    [session] = restarted.list_sessions(SessionQuery())["items"]
    assert session["status"] == "running"
    assert session["last_caller"] == "codex"


def test_older_projection_cannot_overwrite_newer_revision(tmp_path):
    storage = _storage(tmp_path)
    storage.create_conversation("conv-1")
    storage.update_conversation_title("conv-1", "new title")
    current = storage._project_path(storage._get_conversation_path("conv-1"))
    assert current is not None

    stale = replace(
        current,
        title="stale title",
        source_revision=current.source_revision - 1,
        updated_at="2000-01-01T00:00:00Z",
    )
    storage.catalog.commit_upsert(stale)

    [session] = storage.list_sessions(SessionQuery())["items"]
    assert session["title"] == "new title"


def test_legacy_list_reads_catalog_without_projection_fields_leaking(tmp_path):
    storage = _storage(tmp_path)
    storage.create_conversation("conv-1", mode="council")

    [summary] = storage.list_conversations()
    assert summary["id"] == "conv-1"
    assert summary["message_count"] == 0
    assert "source_checksum" not in summary
    assert "source_revision" not in summary


def test_legacy_list_is_bounded_and_facet_columns_are_allowlisted(tmp_path):
    storage = _storage(tmp_path)
    storage.create_conversation("one")
    storage.create_conversation("two")

    assert len(storage.catalog.all_legacy(limit=1)) == 1
    with storage.catalog._connect() as connection:
        with pytest.raises(ValueError, match="Unsupported session facet"):
            storage.catalog._distinct(connection, "mode; DROP TABLE sessions")


def test_conversation_locks_use_a_bounded_stripe_set(tmp_path):
    storage = _storage(tmp_path)
    for index in range(300):
        with storage._conversation_lock(f"conversation-{index}"):
            pass

    lock_files = list(storage._locks_dir.glob("*.lock"))
    assert len(lock_files) <= 256
    assert all(len(path.stem) == 2 for path in lock_files)


def test_reconciliation_batches_write_intent_cleanup_past_sqlite_bind_limit(tmp_path):
    storage = _storage(tmp_path)
    paths = [tmp_path / f"session-{index}.json" for index in range(1001)]
    with storage.catalog._connect() as connection:
        connection.executemany(
            "INSERT INTO session_write_intents "
            "(conversation_id, operation, source_revision, source_checksum, entry_json) "
            "VALUES (?, 'upsert', 1, '', '')",
            [(path.stem,) for path in paths],
        )

    def project(path):
        return SessionCatalogEntry(
            id=path.stem,
            created_at="2026-07-15T00:00:00Z",
            updated_at="2026-07-15T00:00:00Z",
            title=path.stem,
            mode="council",
            source_revision=1,
            source_checksum=path.stem,
        )

    result = storage.catalog.reconcile(paths, project)
    assert result == {"repaired": 1001, "skipped": 0, "removed": 0}
    assert storage.list_sessions(SessionQuery(limit=1))["total"] == 1001
    with storage.catalog._connect() as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM session_write_intents"
        ).fetchone()[0]
        assert remaining == 0
