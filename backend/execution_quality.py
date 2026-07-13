"""Assess whether an arena turn is agent-acceptable or materially degraded."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .model_failures import collect_failure_recommendations, failure_status_class


CHAIRMAN_SYNTHESIS_ERROR = "Error: Unable to generate final synthesis."


def _has_content(text: Any) -> bool:
    return bool(str(text or "").strip())


def is_usable_final_synthesis(stage3: Optional[Dict[str, Any]]) -> bool:
    """True when stage-3 is a real chairman answer, not a placeholder or empty."""
    if not stage3:
        return False
    if stage3.get("synthesis_failed"):
        return False
    resp = str(stage3.get("response") or "").strip()
    if not resp:
        return False
    if resp == CHAIRMAN_SYNTHESIS_ERROR or resp.startswith(CHAIRMAN_SYNTHESIS_ERROR):
        return False
    return True


def _chairman_failure_in_metadata(failures: List[Dict[str, Any]]) -> bool:
    for failure in failures:
        stage = str(failure.get("stage") or failure.get("role") or "")
        if stage in {"stage3", "chair_final", "chair"}:
            return True
    return False


def _draft_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in steps if str(s.get("role") or "").startswith("draft_")]


def _steps_with_role_prefix(steps: List[Dict[str, Any]], prefix: str) -> List[Dict[str, Any]]:
    return [s for s in steps if str(s.get("role") or "").startswith(prefix)]


def assess_execution_quality(
    *,
    mode: str,
    metadata: Optional[Dict[str, Any]] = None,
    stage1: Optional[List[Dict[str, Any]]] = None,
    stage2: Optional[List[Dict[str, Any]]] = None,
    stage3: Optional[Dict[str, Any]] = None,
    arena_models: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Return structured quality for agents and MCP consumers.

    acceptable=False means the agent should not present the result as a successful
    multi-model deliberation without user disclosure and/or retry.
    """
    meta = metadata or {}
    mode_key = (mode or meta.get("mode") or "council").lower()
    models = arena_models or meta.get("arena_models") or []
    failures = list(meta.get("model_failures") or [])
    steps = list(meta.get("steps") or [])
    issues: List[Dict[str, Any]] = []
    recommendations: List[str] = []
    failure_kinds: List[str] = []

    for failure in failures:
        kind = failure.get("failure_kind") or failure_status_class(failure)
        if kind not in failure_kinds:
            failure_kinds.append(kind)
        issues.append(
            {
                "code": "model_failure",
                "model": failure.get("model"),
                "status": failure.get("status"),
                "message": failure.get("message"),
                "provider": failure.get("provider"),
                "stage": failure.get("stage") or failure.get("role"),
                "failure_kind": kind,
            }
        )

    chairman_failed = not is_usable_final_synthesis(stage3) or _chairman_failure_in_metadata(
        failures
    )
    if chairman_failed:
        code = "chairman_failed" if _chairman_failure_in_metadata(failures) else "empty_final"
        issues.append(
            {
                "code": code,
                "message": (
                    "Chairman synthesis failed — no usable final verdict."
                    if code == "chairman_failed"
                    else "Chairman produced no usable final answer."
                ),
            }
        )
        recommendations.append(
            "Chairman failed — retry with a different chairman model, wait out rate limits, "
            "or use @tokenbudget / fewer arena models. Do not present partial council output as final."
        )

    summarize_targets = meta.get("summarize_targets") or {}
    summarize_jobs = list(meta.get("summarize_jobs") or [])
    summarize_failures = [
        job for job in summarize_jobs if str(job.get("outcome") or "") not in {"ok", ""}
    ]
    summarizer_used_chairman = any(
        job.get("chairman_fallback")
        and not job.get("cache_hit")
        and str(job.get("outcome") or "") == "ok"
        for job in summarize_jobs
    )

    budget_raw = meta.get("budget_decisions") or {}
    if isinstance(budget_raw, dict):
        budget_decisions = list(budget_raw.values())
    else:
        budget_decisions = list(budget_raw)

    observation_pending = list(meta.get("observation_pending") or [])

    if summarize_targets:
        issues.append(
            {
                "code": "context_compressed",
                "message": "RAG context was chairman-summarized to fit token budget.",
                "targets": summarize_targets,
            }
        )
    if summarizer_used_chairman:
        issues.append(
            {
                "code": "chairman_summarizer",
                "message": "Chairman model used as summarizer fallback (summarizer_model unset).",
            }
        )
    for job in summarize_failures:
        issues.append(
            {
                "code": "summarize_failure",
                "message": f"Summarize job failed for {job.get('target_model_id', '?')}.",
                "outcome": job.get("outcome"),
                "prompt_id": job.get("prompt_id"),
                "target_model_id": job.get("target_model_id"),
            }
        )

    structure_degraded = [
        job
        for job in summarize_jobs
        if job.get("structure_preserved") is False and str(job.get("outcome") or "") == "ok"
    ]
    for job in structure_degraded:
        issues.append(
            {
                "code": "structure_not_preserved",
                "message": (
                    f"Summarize output for {job.get('target_model_id', '?')} "
                    "lost structure placeholders; citations were footered."
                ),
                "prompt_id": job.get("prompt_id"),
                "target_model_id": job.get("target_model_id"),
            }
        )
    if structure_degraded:
        recommendations.append(
            "Structure-aware compression partially failed. Review summarized context "
            "for missing citations or symbol headers."
        )

    successful_stage1 = 0
    successful_drafts = 0
    expected_drafts = 0

    if mode_key == "round_robin":
        drafts = _draft_steps(steps)
        expected_drafts = len(drafts) or len(models)
        successful_drafts = sum(1 for s in drafts if _has_content(s.get("response")))
        failed_drafts = max(0, len(drafts) - successful_drafts)
        if failed_drafts:
            issues.append(
                {
                    "code": "empty_draft_responses",
                    "failed": failed_drafts,
                    "expected": len(drafts),
                    "succeeded": successful_drafts,
                }
            )
        if successful_drafts == 0 and expected_drafts > 0:
            recommendations.append(
                "All round-robin draft models failed. Retry with @tokenbudget 8000, "
                "paid models, or a smaller squad."
            )
        elif successful_drafts == 1 and len(drafts) > 1:
            issues.append(
                {
                    "code": "rr_chain_degraded",
                    "message": (
                        "Only one model produced a draft; the round-robin refinement "
                        "chain did not run."
                    ),
                    "succeeded": 1,
                    "expected": len(drafts),
                }
            )
            recommendations.append(
                "Do not present as multi-model deliberation. Inform the user and "
                "retry with reliable models or @tokenbudget."
            )
        elif failed_drafts:
            recommendations.append(
                f"{failed_drafts} draft model(s) failed. Check model_failures; "
                "consider paid models or OpenRouter privacy settings."
            )

    elif mode_key == "council":
        s1 = stage1 or []
        successful_stage1 = sum(1 for r in s1 if _has_content(r.get("response")))
        expected = len(models) or len(s1)
        if successful_stage1 < 2 and expected >= 2:
            issues.append(
                {
                    "code": "council_degraded",
                    "succeeded": successful_stage1,
                    "expected": expected,
                    "message": "Too few council answers for meaningful peer review.",
                }
            )
            recommendations.append(
                "Council had insufficient successful answers. Retry or shrink the squad."
            )
        failed_s2 = sum(1 for r in (stage2 or []) if not _has_content(r.get("ranking")))
        if failed_s2:
            issues.append(
                {
                    "code": "empty_rankings",
                    "failed": failed_s2,
                    "expected": len(stage2 or []),
                }
            )

    elif mode_key == "fight":
        for role_prefix, label in (
            ("answer_", "answers"),
            ("critique_", "critiques"),
            ("defense_", "defenses"),
        ):
            role_steps = _steps_with_role_prefix(steps, role_prefix)
            if not role_steps:
                continue
            empty = sum(1 for s in role_steps if not _has_content(s.get("response")))
            if empty:
                issues.append(
                    {
                        "code": f"empty_{label}",
                        "failed": empty,
                        "expected": len(role_steps),
                    }
                )
        if failures:
            recommendations.append(
                "Fight mode had model failures. Surface errors to the user before "
                "trusting adversarial synthesis."
            )

    elif steps:
        empty_steps = sum(1 for s in steps if not _has_content(s.get("response")))
        if empty_steps:
            issues.append(
                {
                    "code": "empty_step_responses",
                    "failed": empty_steps,
                    "expected": len(steps),
                }
            )

    if failures:
        for rec in collect_failure_recommendations(failures):
            if rec not in recommendations:
                recommendations.append(rec)
    if failures and not recommendations:
        recommendations.append(
            "Model failures occurred. Read metadata.model_failures and retry or "
            "inform the user — do not silently accept partial deliberation."
        )

    blocking_codes = {
        "empty_final",
        "chairman_failed",
        "empty_draft_responses",
        "rr_chain_degraded",
        "council_degraded",
        "empty_rankings",
        "empty_answers",
        "empty_critiques",
        "empty_defenses",
        "empty_step_responses",
    }
    has_blocking = any(i.get("code") in blocking_codes for i in issues)
    has_failures = bool(failures)

    if chairman_failed:
        severity = "failed"
        acceptable = False
    elif mode_key == "round_robin" and successful_drafts == 0 and expected_drafts > 0:
        severity = "failed"
        acceptable = False
    elif has_failures or has_blocking:
        severity = "degraded"
        acceptable = False
    else:
        severity = "ok"
        acceptable = True

    return {
        "acceptable": acceptable,
        "severity": severity,
        "mode": mode_key,
        "issues": issues,
        "recommendations": recommendations,
        "summarize_failures": summarize_failures,
        "budget_decisions": budget_decisions,
        "observation_pending": observation_pending,
        "summarizer_used_chairman": summarizer_used_chairman,
        "failure_kinds": failure_kinds,
        "stats": {
            "model_failures": len(failures),
            "arena_models": len(models),
            "successful_stage1": successful_stage1,
            "successful_drafts": successful_drafts,
            "expected_drafts": expected_drafts,
            "has_final_answer": is_usable_final_synthesis(stage3),
            "summarize_jobs": len(summarize_jobs),
            "summarize_failures": len(summarize_failures),
        },
    }


def assess_from_response_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Assess quality from a send_message / run_turn API payload."""
    meta = payload.get("metadata") or {}
    return assess_execution_quality(
        mode=meta.get("mode") or payload.get("mode") or "council",
        metadata=meta,
        stage1=payload.get("stage1"),
        stage2=payload.get("stage2"),
        stage3=payload.get("stage3"),
        arena_models=meta.get("arena_models"),
    )


def _format_issue_line(issue: Dict[str, Any]) -> str:
    """Render one issue as a readable agent-notice line."""
    code = issue.get("code", "issue")
    if code == "model_failure":
        model = (issue.get("model") or "?").split("/")[-1]
        status = issue.get("status")
        kind = issue.get("failure_kind") or "unknown"
        msg = (issue.get("message") or "")[:120]
        return f"- model_failure ({kind}): {model} (HTTP {status}) — {msg}"
    if code in {"empty_final", "chairman_failed"}:
        return f"- {code}: {issue.get('message') or 'Chairman synthesis failed'}"
    if code == "context_compressed":
        return "- context was chairman-summarized for token budget"
    if code == "chairman_summarizer":
        return "- chairman model used as summarizer fallback"
    if code == "summarize_failure":
        target = (issue.get("target_model_id") or "?").split("/")[-1]
        outcome = issue.get("outcome") or "failed"
        return f"- summarize_failure: {target} ({outcome})"
    if code == "structure_not_preserved":
        target = (issue.get("target_model_id") or "?").split("/")[-1]
        return f"- structure_not_preserved: {target} (citations footered)"
    if message := issue.get("message"):
        return f"- {code}: {message}"

    failed = issue.get("failed")
    expected = issue.get("expected")
    succeeded = issue.get("succeeded")
    if failed is not None and expected is not None:
        if succeeded is not None:
            return f"- {code}: {failed} of {expected} failed ({succeeded} succeeded)"
        return f"- {code}: {failed} of {expected} failed"
    if succeeded is not None and expected is not None:
        return f"- {code}: {succeeded} of {expected} succeeded"

    return f"- {code}: execution degraded"


def format_agent_notice(quality: Dict[str, Any]) -> str:
    """Human/agent-readable banner when execution is not acceptable."""
    if quality.get("acceptable"):
        return ""

    severity = (quality.get("severity") or "degraded").upper()
    lines = [
        f"EXECUTION {severity} — do not treat this turn as a successful full deliberation.",
        "",
        "Issues:",
    ]
    for issue in quality.get("issues") or []:
        lines.append(_format_issue_line(issue))

    recs = quality.get("recommendations") or []
    if recs:
        lines.extend(["", "Recommendations:"])
        for rec in recs:
            lines.append(f"- {rec}")

    lines.extend(
        [
            "",
            "execution_quality.acceptable is false — inform the user and consider retry "
            "(@tokenbudget, different models, or OpenRouter privacy settings).",
        ]
    )
    return "\n".join(lines)