"""Tests for structured OpenRouter failure payloads."""

from backend.openrouter import (
    failure_record,
    is_query_failure,
    is_usable_response,
    _failure_response,
    _parse_error_body,
)


class TestOpenRouterFailures:
    def test_failure_response_marked(self):
        resp = _failure_response("m1", {"code": 429, "message": "rate limited"})
        assert is_query_failure(resp)
        assert not is_usable_response(resp)

    def test_failure_record_from_structured(self):
        resp = _failure_response(
            "meta-llama/llama-3.3-70b-instruct:free",
            {
                "code": 429,
                "message": "Provider returned error",
                "provider": "Venice",
                "raw": "rate-limited upstream",
            },
        )
        rec = failure_record("meta-llama/llama-3.3-70b-instruct:free", resp, stage="stage1", role="answer")
        assert rec["status"] == 429
        assert "Provider" in rec["message"]
        assert rec["provider"] == "Venice"

    def test_usable_response_requires_content(self):
        assert is_usable_response({"content": "hello"})
        assert not is_usable_response({"content": ""})
        assert not is_usable_response(None)

    def test_parse_error_body_openrouter_shape(self):
        class FakeResp:
            status_code = 404
            text = '{"error":{"message":"No endpoints","code":404,"metadata":{"provider_name":"x","raw":"policy"}}}'

            def json(self):
                import json
                return json.loads(self.text)

        parsed = _parse_error_body(FakeResp())
        assert parsed["code"] == 404
        assert parsed["provider"] == "x"