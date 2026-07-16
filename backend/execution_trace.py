"""Canonical execution trace shared by all arena modes and UI consumers."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence


TRACE_VERSION = 1
TERMINAL_ROLES = {"chair", "chair_final", "verdict"}


def _has_output(payload: Dict[str, Any]) -> bool:
    return bool(str(payload.get("response") or payload.get("ranking") or "").strip())


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "step"


def _kind(role: str) -> str:
    if role.startswith("draft_"):
        return "draft"
    if role in TERMINAL_ROLES:
        return "verdict"
    if role in {"rankings", "ranking"}:
        return "ranking"
    if role.startswith("stacks_"):
        return role.removeprefix("stacks_")
    return role or "step"


def _failure_matches(
    failure: Dict[str, Any],
    *,
    model: str,
    role: str,
) -> bool:
    if str(failure.get("model") or "") != model:
        return False
    failure_role = str(failure.get("role") or "")
    failure_stage = str(failure.get("stage") or "")
    if failure_role == role or failure_stage == role:
        return True
    aliases = {
        "answer": {"stage1", "answer"},
        "rankings": {"stage2", "rankings", "ranking"},
        "chair_final": {"stage3", "chair", "chair_final"},
    }
    return bool({failure_role, failure_stage} & aliases.get(role, {role}))


def _source_payloads(
    mode: str,
    *,
    metadata_steps: Sequence[Dict[str, Any]],
    stage1: Sequence[Dict[str, Any]],
    stage2: Sequence[Dict[str, Any]],
    stage3: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if mode in {"council", "baseline"}:
        rows: List[Dict[str, Any]] = []
        rows.extend(
            {"payload": payload, "collection": "stage1", "index": index, "role": "answer"}
            for index, payload in enumerate(stage1)
        )
        rows.extend(
            {"payload": payload, "collection": "stage2", "index": index, "role": "rankings"}
            for index, payload in enumerate(stage2)
        )
        if stage3:
            rows.append(
                {"payload": stage3, "collection": "stage3", "index": 0, "role": "chair_final"}
            )
        return rows
    return [
        {
            "payload": payload,
            "collection": "metadata.steps",
            "index": index,
            "role": str(payload.get("role") or payload.get("label") or f"step_{index + 1}"),
        }
        for index, payload in enumerate(metadata_steps)
    ]


def _parent_ids(mode: str, nodes: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    parents: Dict[str, List[str]] = {node["step_id"]: [] for node in nodes}
    successful = [node for node in nodes if node["status"] == "succeeded"]

    if mode in {"round_robin", "complex_iterative"}:
        last_success: Optional[str] = None
        for node in nodes:
            if last_success:
                parents[node["step_id"]] = [last_success]
            if node["status"] == "succeeded" and not node["terminal"]:
                last_success = node["step_id"]
        return parents

    if mode in {"council", "baseline"}:
        answers = [node["step_id"] for node in successful if node["kind"] == "answer"]
        rankings = [node["step_id"] for node in successful if node["kind"] == "ranking"]
        for node in nodes:
            if node["kind"] == "ranking":
                parents[node["step_id"]] = answers
            elif node["terminal"]:
                parents[node["step_id"]] = answers + rankings
        return parents

    if mode == "fight":
        answers = [node for node in successful if node["kind"] == "answer"]
        critiques = [node for node in successful if node["kind"] == "critique"]
        defenses = [node for node in successful if node["kind"] == "defense"]
        for node in nodes:
            if node["kind"] == "critique":
                parents[node["step_id"]] = [
                    answer["step_id"] for answer in answers if answer["model"] != node["model"]
                ]
            elif node["kind"] == "defense":
                own = [answer["step_id"] for answer in answers if answer["model"] == node["model"]]
                parents[node["step_id"]] = own + [
                    critique["step_id"]
                    for critique in critiques
                    if critique["model"] != node["model"]
                ]
            elif node["terminal"]:
                leaves = defenses or critiques or answers
                parents[node["step_id"]] = [leaf["step_id"] for leaf in leaves]
        return parents

    if mode == "stacks":
        answers = [node for node in successful if node["kind"] == "answer"]
        merge = [node for node in successful if node["kind"] == "merge"]
        critiques = [node for node in successful if node["kind"] == "critique"]
        judge = [node for node in successful if node["kind"] == "judge"]
        defenses = [node for node in successful if node["kind"] == "defense"]
        for node in nodes:
            if node["kind"] == "merge":
                parents[node["step_id"]] = [answer["step_id"] for answer in answers]
            elif node["kind"] == "critique":
                parents[node["step_id"]] = [item["step_id"] for item in merge]
            elif node["kind"] in {"judge", "defense"}:
                parents[node["step_id"]] = [item["step_id"] for item in merge + critiques]
            elif node["terminal"]:
                parents[node["step_id"]] = [
                    item["step_id"] for item in (judge + defenses or merge + critiques)
                ]
        return parents

    if mode == "complex_questioning":
        answers = [node for node in successful if node["kind"] == "answer"]
        questions = [node for node in successful if node["kind"] == "question_self"]
        briefs = [node for node in successful if node["kind"] == "brief"]
        muses = [node for node in successful if node["kind"] == "muse"]
        for node in nodes:
            if node["kind"] == "question_self":
                parents[node["step_id"]] = [
                    answer["step_id"] for answer in answers if answer["model"] == node["model"]
                ]
            elif node["kind"] == "brief":
                parents[node["step_id"]] = [item["step_id"] for item in answers + questions]
            elif node["kind"] == "muse":
                own = [item["step_id"] for item in questions if item["model"] == node["model"]]
                parents[node["step_id"]] = [item["step_id"] for item in briefs] + own
            elif node["terminal"]:
                parents[node["step_id"]] = [item["step_id"] for item in muses + briefs]
        return parents

    last_success = None
    for node in nodes:
        if last_success:
            parents[node["step_id"]] = [last_success]
        if node["status"] == "succeeded" and not node["terminal"]:
            last_success = node["step_id"]
    return parents


def _unique(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


def build_execution_trace(
    *,
    mode: str,
    metadata_steps: Optional[Sequence[Dict[str, Any]]] = None,
    stage1: Optional[Sequence[Dict[str, Any]]] = None,
    stage2: Optional[Sequence[Dict[str, Any]]] = None,
    stage3: Optional[Dict[str, Any]] = None,
    failures: Optional[Sequence[Dict[str, Any]]] = None,
    arena_models: Optional[Sequence[str]] = None,
    chairman_model: str = "",
    has_context: bool = False,
    context_source_count: int = 0,
) -> Dict[str, Any]:
    """Build a compact, authoritative graph over existing response payloads."""
    mode_key = (mode or "council").lower()
    failures_list = list(failures or [])
    rows = _source_payloads(
        mode_key,
        metadata_steps=list(metadata_steps or []),
        stage1=list(stage1 or []),
        stage2=list(stage2 or []),
        stage3=stage3,
    )
    nodes: List[Dict[str, Any]] = []
    matched_failure_ids: set[int] = set()

    for ordinal, row in enumerate(rows, start=1):
        payload = row["payload"]
        role = str(row["role"])
        model = str(payload.get("model") or (chairman_model if role in TERMINAL_ROLES else ""))
        matching = [
            (index, failure)
            for index, failure in enumerate(failures_list)
            if _failure_matches(failure, model=model, role=role)
        ]
        matched_failure_ids.update(index for index, _ in matching)
        status = "succeeded" if _has_output(payload) and not matching else "failed"
        step_id = f"step-{ordinal:02d}-{_slug(role)}"
        node: Dict[str, Any] = {
            "step_id": step_id,
            "ordinal": ordinal,
            "kind": _kind(role),
            "role": role,
            "model": model,
            "status": status,
            "terminal": role in TERMINAL_ROLES,
            "source": {"collection": row["collection"], "index": row["index"]},
            "iteration": payload.get("iteration"),
            "position": payload.get("turn"),
        }
        if matching:
            failure = matching[0][1]
            node["failure"] = {
                key: failure.get(key)
                for key in ("status", "message", "provider", "failure_kind")
                if failure.get(key) is not None
            }
        nodes.append(node)

    for failure_index, failure in enumerate(failures_list):
        if failure_index in matched_failure_ids:
            continue
        ordinal = len(nodes) + 1
        role = str(failure.get("role") or failure.get("stage") or "failed_step")
        role = {"stage1": "answer", "stage2": "rankings", "stage3": "chair_final"}.get(role, role)
        model = str(failure.get("model") or "")
        nodes.append(
            {
                "step_id": f"step-{ordinal:02d}-{_slug(role)}",
                "ordinal": ordinal,
                "kind": _kind(role),
                "role": role,
                "model": model,
                "status": "failed",
                "terminal": role in TERMINAL_ROLES or model == chairman_model,
                "source": None,
                "iteration": None,
                "position": None,
                "failure": {
                    key: failure.get(key)
                    for key in ("status", "message", "provider", "failure_kind")
                    if failure.get(key) is not None
                },
            }
        )

    parent_map = _parent_ids(mode_key, nodes)
    artifacts: List[Dict[str, Any]] = [{"artifact_id": "user-query", "kind": "user_query"}]
    if has_context:
        artifacts.append(
            {
                "artifact_id": "rag-context",
                "kind": "context_bundle",
                "source_count": context_source_count,
            }
        )
    edges: List[Dict[str, str]] = []
    for node in nodes:
        parents = parent_map[node["step_id"]]
        node["predecessor_step_ids"] = parents
        inputs = ["user-query"]
        if has_context:
            inputs.append("rag-context")
        for parent_id in parents:
            artifact_id = f"{parent_id}:output"
            inputs.append(artifact_id)
            edges.append({"from_step_id": parent_id, "to_step_id": node["step_id"], "artifact_id": artifact_id})
        node["input_artifact_ids"] = inputs
        if node["status"] == "succeeded":
            output_id = f"{node['step_id']}:output"
            node["output_artifact_id"] = output_id
            artifacts.append(
                {
                    "artifact_id": output_id,
                    "kind": "verdict" if node["terminal"] else "model_output",
                    "producer_step_id": node["step_id"],
                }
            )
        else:
            node["output_artifact_id"] = None

    arena_set = set(arena_models or [])
    arena_nodes = [node for node in nodes if not node["terminal"]]
    participant_models = list(arena_models or _unique(node["model"] for node in arena_nodes))
    participant_succeeded = {
        node["model"] for node in arena_nodes if node["status"] == "succeeded" and node["model"]
    }
    participant_failed_only = {
        model
        for model in participant_models
        if model not in participant_succeeded
        and any(node["model"] == model and node["status"] == "failed" for node in arena_nodes)
    }
    draft_nodes = [node for node in arena_nodes if node["kind"] == "draft"]
    successful_refinements = [
        node for node in draft_nodes if node["status"] == "succeeded" and node["predecessor_step_ids"]
    ]
    final_nodes = [node for node in nodes if node["terminal"]]
    summary = {
        "planned_steps": len(nodes),
        "attempted_steps": sum(node["status"] in {"succeeded", "failed"} for node in nodes),
        "succeeded_steps": sum(node["status"] == "succeeded" for node in nodes),
        "failed_steps": sum(node["status"] == "failed" for node in nodes),
        "arena_steps": len(arena_nodes),
        "arena_succeeded_steps": sum(node["status"] == "succeeded" for node in arena_nodes),
        "arena_failed_steps": sum(node["status"] == "failed" for node in arena_nodes),
        "participant_expected": len(participant_models),
        "participant_succeeded": len(participant_succeeded & arena_set) if arena_set else len(participant_succeeded),
        "participant_failed": len(participant_failed_only),
        "drafts_expected": len(draft_nodes),
        "drafts_succeeded": sum(node["status"] == "succeeded" for node in draft_nodes),
        "successful_refinements": len(successful_refinements),
        "handoff_deliveries": sum(bool(node["predecessor_step_ids"]) for node in draft_nodes),
        "final_status": final_nodes[-1]["status"] if final_nodes else "missing",
    }
    return {
        "version": TRACE_VERSION,
        "mode": mode_key,
        "steps": nodes,
        "artifacts": artifacts,
        "edges": edges,
        "summary": summary,
    }
