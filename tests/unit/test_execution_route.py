"""Execution detail route follows canonical trace topology."""

from backend.routes.execution import _steps_from_trace


def test_steps_from_trace_resolves_each_council_ranking_payload():
    stage1 = [
        {"model": f"m{i}", "role": "answer", "response": f"a{i}"}
        for i in range(2)
    ]
    stage2 = [
        {"model": f"m{i}", "role": "rankings", "ranking": f"r{i}"}
        for i in range(2)
    ]
    stage3 = {"model": "chair", "role": "chair_final", "response": "final"}
    nodes = [
        {
            "step_id": "answer-1",
            "ordinal": 1,
            "kind": "answer",
            "role": "answer",
            "model": "m0",
            "status": "succeeded",
            "terminal": False,
            "predecessor_step_ids": [],
            "source": {"collection": "stage1", "index": 0},
        },
        {
            "step_id": "answer-2",
            "ordinal": 2,
            "kind": "answer",
            "role": "answer",
            "model": "m1",
            "status": "succeeded",
            "terminal": False,
            "predecessor_step_ids": [],
            "source": {"collection": "stage1", "index": 1},
        },
        {
            "step_id": "ranking-1",
            "ordinal": 3,
            "kind": "ranking",
            "role": "rankings",
            "model": "m0",
            "status": "succeeded",
            "terminal": False,
            "predecessor_step_ids": ["answer-1", "answer-2"],
            "source": {"collection": "stage2", "index": 0},
        },
        {
            "step_id": "ranking-2",
            "ordinal": 4,
            "kind": "ranking",
            "role": "rankings",
            "model": "m1",
            "status": "succeeded",
            "terminal": False,
            "predecessor_step_ids": ["answer-1", "answer-2"],
            "source": {"collection": "stage2", "index": 1},
        },
        {
            "step_id": "chair-1",
            "ordinal": 5,
            "kind": "verdict",
            "role": "chair_final",
            "model": "chair",
            "status": "succeeded",
            "terminal": True,
            "predecessor_step_ids": ["answer-1", "answer-2", "ranking-1", "ranking-2"],
            "source": {"collection": "stage3", "index": 0},
        },
    ]
    msg = {"stage1": stage1, "stage2": stage2, "stage3": stage3}
    meta = {"steps": stage1 + [{"role": "rankings"}] + [stage3], "execution_trace": {"version": 1, "steps": nodes}}

    rows = _steps_from_trace(msg, meta)

    assert len(rows) == 5
    assert [row["kind"] for row in rows] == ["answer", "answer", "ranking", "ranking", "verdict"]
    assert [row.get("ranking") for row in rows[2:4]] == ["r0", "r1"]
    assert rows[-1]["terminal"] is True
