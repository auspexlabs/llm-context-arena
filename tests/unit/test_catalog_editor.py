"""Tests for catalog editor read/write (DEC-018 Phase C / DEF-008)."""

import pytest

from backend.catalog_editor import list_catalog_models, update_catalog_model_fields


def test_list_catalog_models_reads_yaml(tmp_path, monkeypatch):
    catalog_path = tmp_path / "model_catalog.yaml"
    catalog_path.write_text(
        "version: 1\nmodels:\n  test/model:\n    tags: [free]\n    registered_limit: 1000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.catalog_editor.MODEL_CATALOG_PATH", catalog_path)

    data = list_catalog_models()
    assert data["count"] == 1
    assert data["models"]["test/model"]["registered_limit"] == 1000


def test_update_catalog_model_fields(tmp_path, monkeypatch):
    catalog_path = tmp_path / "model_catalog.yaml"
    catalog_path.write_text(
        "version: 1\nmodels:\n  test/model:\n    tags: []\n    registered_limit: 1000\n    model_modifier: 1.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.catalog_editor.MODEL_CATALOG_PATH", catalog_path)
    monkeypatch.setattr("backend.frozen_config.clear_frozen_cache", lambda: None)

    result = update_catalog_model_fields(
        "test/model",
        {"tags": ["free"], "model_modifier": 0.5, "manual_override_limit": 800},
    )
    assert result["entry"]["tags"] == ["free"]
    assert result["entry"]["model_modifier"] == 0.5
    assert result["entry"]["manual_override_limit"] == 800
    assert "manual_override_limit: 800" in catalog_path.read_text(encoding="utf-8")


def test_update_catalog_model_clears_manual_override(tmp_path, monkeypatch):
    catalog_path = tmp_path / "model_catalog.yaml"
    catalog_path.write_text(
        "version: 1\nmodels:\n  test/model:\n    registered_limit: 1000\n    manual_override_limit: 500\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.catalog_editor.MODEL_CATALOG_PATH", catalog_path)
    monkeypatch.setattr("backend.frozen_config.clear_frozen_cache", lambda: None)

    update_catalog_model_fields("test/model", {"manual_override_limit": None})
    text = catalog_path.read_text(encoding="utf-8")
    assert "manual_override_limit" not in text