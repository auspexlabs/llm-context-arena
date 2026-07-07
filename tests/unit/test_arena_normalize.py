"""Tests for arena result normalization (DIS-002)."""

from backend.arena import is_council_mode, normalize_arena_results


class TestNormalizeArenaResults:
    def test_council_mode_unchanged(self):
        s1 = [{"model": "a", "response": "x", "role": "answer"}]
        s2 = [{"model": "b", "ranking": "FINAL RANKING:\n1. Response A"}]
        s3 = {"model": "chair", "response": "final", "role": "chair_final"}
        meta = {"mode": "council", "steps": s1 + [{"role": "rankings"}] + [s3]}
        out = normalize_arena_results("council", s1, s2, s3, meta)
        assert out[0] == s1
        assert out[1] == s2
        assert out[3]["steps"]

    def test_fight_clears_stage1(self):
        steps = [
            {"model": "a", "response": "ans", "role": "answer"},
            {"model": "a", "response": "crit", "role": "critique"},
        ]
        s3 = {"model": "chair", "response": "done", "role": "chair_final"}
        meta = {"mode": "fight", "steps": steps + [s3]}
        s1, s2, s3_out, meta_out = normalize_arena_results("fight", steps, [], s3, meta)
        assert s1 == []
        assert s2 == []
        assert s3_out == s3
        assert len(meta_out["steps"]) == 3

    def test_is_council_mode(self):
        assert is_council_mode("council") is True
        assert is_council_mode("baseline") is True
        assert is_council_mode("fight") is False