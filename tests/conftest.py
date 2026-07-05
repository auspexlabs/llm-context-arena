"""Shared pytest fixtures for LLM Context Arena tests."""

import pytest
from pathlib import Path

from backend.directives import ParsedDirectives
from backend.models import ArenaMode, ModelResponse, Stage1Result


@pytest.fixture
def sample_directives():
    """Return a default ParsedDirectives instance."""
    return ParsedDirectives()


@pytest.fixture
def sample_model_response_dict():
    """Return a sample model response as dict."""
    return {
        "model": "openai/gpt-4",
        "response": "Test response content",
        "role": "answer",
        "est_tokens": 100,
        "context_tokens": 50,
    }


@pytest.fixture
def sample_model_response(sample_model_response_dict):
    """Return a sample ModelResponse instance."""
    return ModelResponse(**sample_model_response_dict)


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Return a temporary data directory for storage tests."""
    data_dir = tmp_path / "conversations"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
