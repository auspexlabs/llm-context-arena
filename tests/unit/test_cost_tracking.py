"""Tests for OpenRouter cost aggregation."""

from backend.cost_tracking import (
    apply_usage_fields,
    summarize_conversation_cost,
    summarize_turn_cost,
    usage_fields_from_response,
)


class TestCostTracking:
    def test_usage_fields_from_response(self):
        resp = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "cost": 0.00125,
            }
        }
        fields = usage_fields_from_response(resp)
        assert fields["prompt_tokens"] == 100
        assert fields["completion_tokens"] == 50
        assert fields["cost_usd"] == 0.00125

    def test_apply_usage_fields(self):
        step = {"model": "test", "role": "answer"}
        apply_usage_fields(step, {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0}})
        assert step["prompt_tokens"] == 10
        assert step["completion_tokens"] == 5

    def test_summarize_turn_cost(self):
        steps = [
            {"cost_usd": 0.0, "prompt_tokens": 100, "completion_tokens": 20},
            {"cost_usd": 0.002, "prompt_tokens": 200, "completion_tokens": 40},
        ]
        summary = summarize_turn_cost(steps)
        assert summary["turn_cost_usd"] == 0.002
        assert summary["prompt_tokens"] == 300
        assert summary["calls"] == 2

    def test_summarize_conversation_cost(self):
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "metadata": {
                    "cost": {
                        "turn_cost_usd": 0.01,
                        "prompt_tokens": 1000,
                        "completion_tokens": 200,
                        "calls": 3,
                    }
                },
            },
            {"role": "user", "content": "again"},
            {
                "role": "assistant",
                "metadata": {
                    "steps": [
                        {"cost_usd": 0.005, "prompt_tokens": 500, "completion_tokens": 100}
                    ]
                },
            },
        ]
        summary = summarize_conversation_cost(messages)
        assert summary["conversation_cost_usd"] == 0.015
        assert summary["turns"] == 2