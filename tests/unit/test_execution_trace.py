"""Canonical execution trace contract tests."""

from backend.execution_trace import build_execution_trace


def test_round_robin_trace_preserves_last_successful_lineage_through_failures():
    steps = [
        {"model": "a", "role": "draft_p1_t1", "response": "A", "iteration": 1, "turn": 1},
        {"model": "b", "role": "draft_p1_t2", "response": "B", "iteration": 1, "turn": 2},
        {"model": "c", "role": "draft_p1_t3", "response": "", "iteration": 1, "turn": 3},
        {"model": "d", "role": "draft_p1_t4", "response": "", "iteration": 1, "turn": 4},
        {"model": "chair", "role": "chair_final", "response": "final"},
    ]
    failures = [
        {"model": "c", "role": "draft_p1_t3", "status": 429, "failure_kind": "rate_limit"},
        {"model": "d", "role": "draft_p1_t4", "status": 429, "failure_kind": "rate_limit"},
    ]

    trace = build_execution_trace(
        mode="round_robin",
        metadata_steps=steps,
        failures=failures,
        arena_models=["a", "b", "c", "d"],
        chairman_model="chair",
        has_context=True,
        context_source_count=12,
    )

    nodes = trace["steps"]
    assert [node["status"] for node in nodes] == [
        "succeeded",
        "succeeded",
        "failed",
        "failed",
        "succeeded",
    ]
    assert nodes[1]["predecessor_step_ids"] == [nodes[0]["step_id"]]
    assert nodes[2]["predecessor_step_ids"] == [nodes[1]["step_id"]]
    assert nodes[3]["predecessor_step_ids"] == [nodes[1]["step_id"]]
    assert nodes[4]["predecessor_step_ids"] == [nodes[1]["step_id"]]
    assert "rag-context" in nodes[1]["input_artifact_ids"]
    assert nodes[2]["output_artifact_id"] is None
    assert trace["summary"] == {
        "planned_steps": 5,
        "attempted_steps": 5,
        "succeeded_steps": 3,
        "failed_steps": 2,
        "arena_steps": 4,
        "arena_succeeded_steps": 2,
        "arena_failed_steps": 2,
        "participant_expected": 4,
        "participant_succeeded": 2,
        "participant_failed": 2,
        "drafts_expected": 4,
        "drafts_succeeded": 2,
        "successful_refinements": 1,
        "handoff_deliveries": 3,
        "final_status": "succeeded",
    }


def test_council_trace_uses_individual_rankings_not_aggregate_step():
    trace = build_execution_trace(
        mode="council",
        metadata_steps=[{"model": "arena", "role": "rankings", "response": "combined"}],
        stage1=[
            {"model": "a", "response": "A"},
            {"model": "b", "response": "B"},
        ],
        stage2=[
            {"model": "a", "ranking": "B, A"},
            {"model": "b", "ranking": "A, B"},
        ],
        stage3={"model": "chair", "response": "final"},
        arena_models=["a", "b"],
        chairman_model="chair",
    )

    assert [node["kind"] for node in trace["steps"]] == [
        "answer",
        "answer",
        "ranking",
        "ranking",
        "verdict",
    ]
    assert trace["summary"]["participant_succeeded"] == 2


def test_fight_trace_matches_peer_only_critique_and_defense_packets():
    steps = []
    for role in ("answer", "critique", "defense"):
        steps.extend(
            {"model": model, "role": role, "response": f"{role}-{model}"}
            for model in ("a", "b", "c")
        )
    steps.append({"model": "chair", "role": "chair_final", "response": "final"})

    trace = build_execution_trace(
        mode="fight",
        metadata_steps=steps,
        arena_models=["a", "b", "c"],
        chairman_model="chair",
    )
    nodes = trace["steps"]
    answers = {node["model"]: node for node in nodes if node["kind"] == "answer"}
    critiques = {node["model"]: node for node in nodes if node["kind"] == "critique"}
    defenses = {node["model"]: node for node in nodes if node["kind"] == "defense"}
    chair = nodes[-1]

    assert set(critiques["a"]["predecessor_step_ids"]) == {
        answers["b"]["step_id"],
        answers["c"]["step_id"],
    }
    assert set(defenses["a"]["predecessor_step_ids"]) == {
        answers["a"]["step_id"],
        critiques["b"]["step_id"],
        critiques["c"]["step_id"],
    }
    assert set(chair["predecessor_step_ids"]) == {
        defense["step_id"] for defense in defenses.values()
    }
