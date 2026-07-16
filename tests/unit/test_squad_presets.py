"""Tests for arena squad preset loading."""

import pytest

from backend.squad_presets import (
    DEFAULT_SQUAD,
    list_squad_names,
    load_squad_preset,
    resolve_startup_squad,
)


class TestSquadPresets:
    def test_list_squad_names(self):
        names = list_squad_names()
        assert "normal" in names
        assert "freebee9" in names
        assert "cheap_pros" in names

    def test_normal_squad_has_five_models(self):
        squad = load_squad_preset("normal")
        assert squad["name"] == "normal"
        assert len(squad["arena_models"]) == 5
        assert squad["chairman_model"]

    def test_freebee9_squad_has_nine_models(self):
        squad = load_squad_preset("freebee9")
        assert squad["name"] == "freebee9"
        assert len(squad["arena_models"]) == 9

    def test_cheap_pros_squad_has_four_paid_models_and_chair(self):
        squad = load_squad_preset("cheap_pros")
        assert squad["name"] == "cheap_pros"
        assert squad["label"] == "Cheap Pro's"
        assert len(squad["arena_models"]) == 4
        assert all(not model.endswith(":free") for model in squad["arena_models"])
        assert not squad["chairman_model"].endswith(":free")

    def test_unknown_squad_raises(self):
        with pytest.raises(ValueError, match="Unknown arena squad"):
            load_squad_preset("nonexistent")

    def test_resolve_startup_squad_defaults_to_normal(self):
        squad = resolve_startup_squad(None)
        assert squad["name"] == DEFAULT_SQUAD

    def test_resolve_startup_squad_bad_env_falls_back(self):
        squad = resolve_startup_squad("not-a-real-squad")
        assert squad["name"] == DEFAULT_SQUAD
