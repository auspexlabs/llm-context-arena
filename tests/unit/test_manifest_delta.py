"""Tests for manifest delta detection and incremental chunk merge."""

import pickle
from pathlib import Path

import pytest

from backend.rag.chunker import chunk_file
from backend.rag.indexer import index_directory, merge_chunks_for_delta
from backend.rag.manifest import diff_manifest, scan_repo_files
from backend.rag.store import ConversationStore


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class _FakeEmbedder:
    def embed_query(self, text: str):
        return [1.0, 0.0]

    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]


class TestManifestDiff:
    def test_detects_added_changed_removed(self, tmp_path):
        (tmp_path / "a.py").write_text("alpha = 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("beta = 2\n", encoding="utf-8")
        current = scan_repo_files(tmp_path)

        indexed = [
            {"path": "a.py", "bytes": 10, "mtime": 1.0},
            {"path": "b.py", "bytes": 10, "mtime": 2.0},
            {"path": "gone.py", "bytes": 5, "mtime": 3.0},
        ]
        delta = diff_manifest(indexed, current)
        assert "gone.py" in delta.removed
        assert "a.py" in delta.changed or "b.py" in delta.changed
        assert delta.has_changes

    def test_no_changes_when_metadata_matches(self, tmp_path):
        path = tmp_path / "a.py"
        path.write_text("x = 1\n", encoding="utf-8")
        stat = path.stat()
        current = scan_repo_files(tmp_path)
        indexed = [{"path": "a.py", "bytes": stat.st_size, "mtime": stat.st_mtime}]
        delta = diff_manifest(indexed, current)
        assert not delta.has_changes
        assert delta.unchanged == ["a.py"]


class TestMergeChunksForDelta:
    def test_drops_removed_and_rechunks_changed(self, tmp_path):
        old_path = tmp_path / "old.py"
        old_path.write_text("def old_fn():\n    pass\n", encoding="utf-8")
        new_path = tmp_path / "new.py"
        new_path.write_text("def new_fn():\n    return 1\n", encoding="utf-8")

        old_chunks = chunk_file(old_path, tmp_path)
        keep_path = tmp_path / "keep.py"
        keep_path.write_text("def keep_fn():\n    pass\n", encoding="utf-8")
        keep_chunks = chunk_file(keep_path, tmp_path)

        existing = {c.chunk_id: c for c in old_chunks + keep_chunks}
        order = [c.chunk_id for c in old_chunks + keep_chunks]

        old_path.write_text("def old_fn():\n    return 99\n", encoding="utf-8")
        delta = diff_manifest(
            [{"path": "old.py", "bytes": 1, "mtime": 1.0}, {"path": "keep.py", "bytes": 1, "mtime": 1.0}],
            scan_repo_files(tmp_path),
        )
        delta.added = ["new.py"]
        delta.removed = []
        delta.changed = ["old.py"]

        merged = merge_chunks_for_delta(existing, order, tmp_path, delta)
        sources = {c.source for c in merged}
        assert "keep.py" in sources
        assert "new.py" in sources
        assert "old.py" in sources
        old_merged = [c for c in merged if c.source == "old.py"]
        assert any("return 99" in c.content for c in old_merged)


class TestIndexDirectoryDelta:
    @staticmethod
    def _patch_index_build(monkeypatch):
        class _FakeVS:
            def save_local(self, _path):
                return None

        monkeypatch.setattr(
            "backend.rag.store.build_semantic_index",
            lambda chunks, path, rebuild=True: None,
        )
        monkeypatch.setattr(
            "backend.rag.store.FAISS.from_texts",
            lambda texts, embedder, metadatas=None: _FakeVS(),
        )

    def test_skips_rebuild_when_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "conversations").mkdir(parents=True)
        repo = tmp_path / "repo"
        repo.mkdir()
        sample = FIXTURES / "sample_module.py"
        (repo / "sample_module.py").write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
        manifest_path = tmp_path / "manifest.json"
        store = ConversationStore("delta-convo", tmp_path / "data", _FakeEmbedder())
        self._patch_index_build(monkeypatch)

        msg1 = index_directory(repo, "delta-convo", store, manifest_path)
        assert "Indexed" in msg1

        store2 = ConversationStore("delta-convo", tmp_path / "data", _FakeEmbedder())
        msg2 = index_directory(repo, "delta-convo", store2, manifest_path)
        assert "No changes" in msg2

    def test_delta_reindex_updates_chunks(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "conversations").mkdir(parents=True)
        repo = tmp_path / "repo"
        repo.mkdir()
        sample = FIXTURES / "sample_module.py"
        target = repo / "sample_module.py"
        target.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
        manifest_path = tmp_path / "manifest.json"
        data_dir = tmp_path / "data"
        store = ConversationStore("delta-convo", data_dir, _FakeEmbedder())
        self._patch_index_build(monkeypatch)

        index_directory(repo, "delta-convo", store, manifest_path)

        target.write_text(
            target.read_text(encoding="utf-8") + "\n\ndef delta_marker():\n    return 'delta'\n",
            encoding="utf-8",
        )
        store2 = ConversationStore("delta-convo", data_dir, _FakeEmbedder())
        msg = index_directory(repo, "delta-convo", store2, manifest_path)
        assert "Delta reindexed" in msg

        chunks_path = tmp_path / "data" / "conversations" / "delta-convo_chunks.pkl"
        assert chunks_path.exists()
        with open(chunks_path, "rb") as f:
            payload = pickle.load(f)
        symbols = {c.symbol for c in payload["chunks"].values() if c.symbol}
        assert "delta_marker" in symbols


class TestProviderIndexDelta:
    def test_compute_index_delta_reports_changes(self, tmp_path, monkeypatch):
        from backend.rag_lmstudio_provider import LMStudioRAGProvider

        repo = tmp_path / "repo"
        repo.mkdir()
        sample = repo / "sample_module.py"
        sample.write_text((FIXTURES / "sample_module.py").read_text(encoding="utf-8"), encoding="utf-8")

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            '{"conv-1": {"root": "%s", "files": [{"path": "sample_module.py", "bytes": 1, "mtime": 1.0}]}}'
            % str(repo),
            encoding="utf-8",
        )
        monkeypatch.setattr("backend.rag_lmstudio_provider.INDEX_MANIFEST_PATH", str(manifest_path))

        provider = LMStudioRAGProvider(embedder=_FakeEmbedder())
        delta = provider.compute_index_delta("conv-1")
        assert delta["has_index"] is True
        assert delta["has_changes"] is True
        assert "sample_module.py" in delta["changed"]