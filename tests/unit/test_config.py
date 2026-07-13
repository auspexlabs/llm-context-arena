"""Tests for backend configuration helpers."""

from backend import config


def _reset_colbert_device_cache() -> None:
    config._COLBERT_DEVICE_RESOLVED = None


class TestGetColbertDevice:
    def test_auto_falls_back_to_cpu_without_cuda(self, monkeypatch):
        _reset_colbert_device_cache()
        monkeypatch.delenv("COLBERT_DEVICE", raising=False)
        monkeypatch.setattr(config, "_cuda_usable_for_colbert", lambda: False)
        assert config.get_colbert_device() == "cpu"

    def test_auto_uses_cuda_when_usable(self, monkeypatch):
        _reset_colbert_device_cache()
        monkeypatch.delenv("COLBERT_DEVICE", raising=False)
        monkeypatch.setattr(config, "_cuda_usable_for_colbert", lambda: True)
        assert config.get_colbert_device() == "cuda"

    def test_explicit_cpu_override(self, monkeypatch):
        _reset_colbert_device_cache()
        monkeypatch.setenv("COLBERT_DEVICE", "cpu")
        assert config.get_colbert_device() == "cpu"

    def test_explicit_cuda_falls_back_when_unusable(self, monkeypatch):
        _reset_colbert_device_cache()
        monkeypatch.setenv("COLBERT_DEVICE", "cuda")
        monkeypatch.setattr(config, "_cuda_usable_for_colbert", lambda: False)
        assert config.get_colbert_device() == "cpu"

    def test_explicit_cuda_when_usable(self, monkeypatch):
        _reset_colbert_device_cache()
        monkeypatch.setenv("COLBERT_DEVICE", "cuda")
        monkeypatch.setattr(config, "_cuda_usable_for_colbert", lambda: True)
        assert config.get_colbert_device() == "cuda"