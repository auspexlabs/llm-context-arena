"""Tests for model failure classification (DEC-018 Phase C c2)."""

from backend.model_failures import (
    ModelFailureKind,
    classify_model_failure,
    collect_failure_recommendations,
    enrich_failure_record,
    failure_status_class,
    recommendation_for_failure_kind,
)
from backend.openrouter import _failure_response, failure_record


class TestModelFailureClassification:
    def test_rate_limit_from_status(self):
        assert classify_model_failure(status=429, message="rate limited") == ModelFailureKind.RATE_LIMIT

    def test_context_exceeded_from_message(self):
        kind = classify_model_failure(status=400, message="context length exceeded for model")
        assert kind == ModelFailureKind.CONTEXT_EXCEEDED

    def test_privacy_blocked_from_message(self):
        kind = classify_model_failure(status=403, message="data policy requires privacy settings")
        assert kind == ModelFailureKind.PRIVACY_BLOCKED

    def test_timeout_from_message(self):
        kind = classify_model_failure(status=None, message="Request timed out")
        assert kind == ModelFailureKind.TIMEOUT

    def test_failure_record_includes_kind(self):
        resp = _failure_response("m1", {"code": 429, "message": "rate limited"})
        rec = failure_record("m1", resp, stage="stage1", role="answer")
        assert rec["failure_kind"] == "rate_limit"

    def test_failure_status_class_uses_kind(self):
        rec = enrich_failure_record({"status": 500, "message": "upstream"})
        assert failure_status_class(rec) == "server_error"

    def test_no_response_classified_unknown_not_timeout(self):
        rec = failure_record("m1", None, stage="stage1", role="answer")
        assert rec["failure_kind"] == "unknown"

    def test_generic_logging_message_not_privacy_blocked(self):
        kind = classify_model_failure(status=500, message="error occurred during request logging")
        assert kind == ModelFailureKind.SERVER_ERROR

    def test_collect_failure_recommendations_dedupes(self):
        failures = [
            {"failure_kind": "rate_limit"},
            {"failure_kind": "rate_limit"},
            {"failure_kind": "context_exceeded"},
        ]
        recs = collect_failure_recommendations(failures)
        assert len(recs) == 2
        assert recommendation_for_failure_kind(ModelFailureKind.CONTEXT_EXCEEDED) in recs[0]
        assert "Rate limited" in recs[1]

    def test_collect_failure_recommendations_dedupes_invalid_kinds_to_unknown(self):
        failures = [
            {"failure_kind": "bad_v1"},
            {"failure_kind": "bad_v2"},
        ]
        recs = collect_failure_recommendations(failures)
        assert len(recs) == 1
        assert recs[0] == recommendation_for_failure_kind(ModelFailureKind.UNKNOWN)