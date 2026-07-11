"""Tests for catalog refresh (DEC-018 Phase B)."""

import pytest

from backend.catalog_refresh import refresh_catalog_from_remote, validate_frozen_config


def test_refresh_catalog_updates_registered_limits(tmp_path, monkeypatch):
    catalog_path = tmp_path / "model_catalog.yaml"
    catalog_path.write_text(
        "version: 1\nmodels:\n  test/model:\n    tags: []\n    registered_limit: 1000\n",
        encoding="utf-8",
    )
    meta_path = tmp_path / "catalog_meta.yaml"
    monkeypatch.setattr("backend.catalog_refresh.MODEL_CATALOG_PATH", catalog_path)
    monkeypatch.setattr("backend.catalog_refresh.CATALOG_META_PATH", meta_path)

    remote = {
        "test/model": {"id": "test/model", "context_length": 200000, "pricing": {"prompt": "0"}},
    }
    cleared: list[bool] = []
    monkeypatch.setattr(
        "backend.frozen_config.clear_frozen_cache",
        lambda: cleared.append(True),
    )
    summary = refresh_catalog_from_remote(remote, dry_run=False)
    assert "test/model" in summary["updated"]
    assert "registered_limit: 200000" in catalog_path.read_text(encoding="utf-8")
    assert cleared == [True]


def test_validate_frozen_config_ok():
    ok, issues = validate_frozen_config()
    assert ok is True
    assert issues == []