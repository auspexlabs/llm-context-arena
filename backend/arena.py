"""LLM Context Arena - Multi-mode orchestration for model deliberation."""

import asyncio
import time
from typing import List, Dict, Any, Tuple, Optional, Callable
from .openrouter import (
    query_models_parallel,
    query_model,
    is_usable_response,
    failure_record,
)
from .budget import maybe_compress_mid_turn
from .budget_metadata import SummarizeJob
from .config import ARENA_MODELS, CHAIRMAN_MODEL
from .cost_tracking import apply_usage_fields, sum_usage_fields, summarize_turn_cost
from .execution_quality import CHAIRMAN_SYNTHESIS_ERROR
from .prompts import render_prompt
from .prompt_provenance import (
    artifact_ref,
    context_ref,
    provenance,
    render_projected_prompt,
    text_part,
)

COUNCIL_MODES = frozenset({"council", "baseline"})


def is_council_mode(mode: Optional[str]) -> bool:
    return (mode or "council").lower() in COUNCIL_MODES


def normalize_arena_results(
    mode: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Tuple[List, List, Dict, Dict]:
    """Council keeps stage1/2/3 split; advanced modes expose steps only via metadata."""
    mode_key = (mode or "council").lower()
    meta = dict(metadata or {})
    meta["mode"] = meta.get("mode") or mode_key
    if is_council_mode(mode_key):
        return stage1_results, stage2_results, stage3_result, meta
    steps = meta.get("steps")
    if not steps and stage1_results:
        steps = list(stage1_results)
        meta["steps"] = steps
    return [], stage2_results, stage3_result, meta


async def emit_execution_start(
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]],
    mode: str,
    step_total: int,
    labels: Optional[List[str]] = None,
) -> None:
    if not progress_cb:
        return
    await progress_cb(
        {
            "type": "execution_start",
            "data": {
                "mode": mode,
                "step_total": step_total,
                "labels": labels or [],
            },
        }
    )
    await progress_cb({"type": "mode_steps", "data": {"total": step_total, "labels": labels or []}})


async def emit_step_complete(
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]],
    step: Dict[str, Any],
    step_index: int,
    step_total: int,
    *,
    state: str = "finish",
) -> None:
    if not progress_cb:
        return
    payload = {
        "step_index": step_index,
        "step_total": step_total,
        "step": step,
        "role": step.get("role"),
        "label": step.get("role"),
        "model": step.get("model"),
        "active_model": step.get("model"),
        "state": state,
        "completed": step_index,
        "current": step_index,
    }
    await progress_cb({"type": "step_complete", "data": payload})
    await progress_cb({"type": "mode_progress", "data": payload})


async def stage1_collect_responses(
    user_query: str,
    per_model_prompts: Optional[Dict[str, str]] = None,
    arena_models: Optional[List[str]] = None,
    context_tokens_map: Optional[Dict[str, int]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]] = None,
    emit_steps: bool = True,
    progress_total: Optional[int] = None,
    progress_offset: int = 0,
    model_failures: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all arena models.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    models = arena_models or ARENA_MODELS
    context_map = context_tokens_map or {}
    total_steps = progress_total if progress_total is not None else len(models)
    step_counter = [progress_offset]
    counter_lock = asyncio.Lock()

    async def _run_model(idx: int, model: str) -> Optional[Dict[str, Any]]:
        prompt = per_model_prompts.get(model, user_query) if per_model_prompts else user_query
        context_tokens = context_map.get(model, context_map.get("__base__", 0))
        async with counter_lock:
            start_idx = step_counter[0]
        if progress_cb:
            await progress_cb(
                {
                    "type": "mode_progress",
                    "data": {
                        "step_index": start_idx,
                        "step_total": total_steps,
                        "completed": start_idx,
                        "current": start_idx,
                        "total": total_steps,
                        "label": "answer",
                        "active_model": model,
                        "model": model,
                        "state": "start",
                    },
                }
            )
        individual_prompt = render_prompt("council.stage1", prompt=prompt)
        orchestration_text = render_prompt(
            "council.stage1",
            prompt="[Grounded question and repository context attached separately; inspect RAG retrieval]",
        )
        resp = await query_model(
            model,
            [{"role": "user", "content": individual_prompt}],
        )
        if not is_usable_response(resp):
            if model_failures is not None:
                model_failures.append(
                    failure_record(model, resp, stage="stage1", role="answer")
                )
            return None
        result = apply_usage_fields(
            {
                "model": model,
                "response": resp.get("content", ""),
                "role": "answer",
                "prompt_preview": individual_prompt[:500],
                "prompt_full": individual_prompt,
                "orchestration_text": orchestration_text,
                "est_tokens": max(len(individual_prompt) // 4, 1),
                "context_tokens": context_tokens,
            },
            resp,
        )
        async with counter_lock:
            step_counter[0] += 1
            finish_idx = step_counter[0]
        await emit_step_complete(progress_cb, result, finish_idx, total_steps)
        return result

    tasks = [asyncio.create_task(_run_model(idx, model)) for idx, model in enumerate(models)]
    responses_list = await asyncio.gather(*tasks)
    # Filter out failures
    return [res for res in responses_list if res is not None]


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    arena_models: Optional[List[str]] = None,
    model_failures: Optional[List[Dict[str, Any]]] = None,
    query_model_fn: Optional[Callable] = None,
    chairman_model: str = CHAIRMAN_MODEL,
    budget_override: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str], List[SummarizeJob]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
    ])

    mid_turn_jobs: List[SummarizeJob] = []
    if query_model_fn is not None:
        responses_text, mid_turn_jobs = await maybe_compress_mid_turn(
            user_query=user_query,
            responses_text=responses_text,
            arena_models=arena_models or ARENA_MODELS,
            query_model_fn=query_model_fn,
            chairman_model=chairman_model,
            budget_override=budget_override,
        )

    ranking_prompt = render_prompt(
        "council.rank",
        user_query=user_query,
        responses_text=responses_text,
    )
    ranking_orchestration = render_prompt(
        "council.rank",
        user_query="[Grounded question and repository context attached separately; inspect RAG retrieval]",
        responses_text=responses_text,
    )

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all arena models in parallel
    models = arena_models or ARENA_MODELS
    responses = await query_models_parallel(models, messages)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if is_usable_response(response):
            full_text = response.get("content", "")
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append(
                apply_usage_fields(
                    {
                        "model": model,
                        "ranking": full_text,
                        "parsed_ranking": parsed,
                        "role": "rankings",
                        "prompt_preview": ranking_prompt[:500],
                        "prompt_full": ranking_prompt,
                        "orchestration_text": ranking_orchestration,
                        "est_tokens": max(len(ranking_prompt) // 4, 1),
                    },
                    response,
                )
            )
        elif model_failures is not None:
            model_failures.append(
                failure_record(model, response, stage="stage2", role="rankings")
            )

    return stage2_results, label_to_model, mid_turn_jobs


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    chairman_model: str = CHAIRMAN_MODEL,
    model_failures: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build comprehensive context for chairman
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in stage2_results
    ])

    chairman_prompt = render_prompt(
        "council.chair",
        user_query=user_query,
        stage1_text=stage1_text,
        stage2_text=stage2_text,
    )
    chairman_orchestration = render_prompt(
        "council.chair",
        user_query="[Grounded question and repository context attached separately; inspect RAG retrieval]",
        stage1_text=stage1_text,
        stage2_text=stage2_text,
    )

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    response = await query_model(chairman_model, messages)

    if not is_usable_response(response):
        if model_failures is not None:
            model_failures.append(
                failure_record(
                    chairman_model, response, stage="stage3", role="chair_final"
                )
            )
        return {
            "model": chairman_model,
            "response": CHAIRMAN_SYNTHESIS_ERROR,
            "role": "chair_final",
            "synthesis_failed": True,
        }

    return apply_usage_fields(
        {
            "model": chairman_model,
            "response": response.get("content", ""),
            "role": "chair_final",
            "prompt_preview": chairman_prompt[:500],
            "prompt_full": chairman_prompt,
            "orchestration_text": chairman_orchestration,
            "est_tokens": max(len(chairman_prompt) // 4, 1),
            "context_tokens": 0,
        },
        response,
    )


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "avg_rank": round(avg_rank, 2),
                "votes": len(positions),
                "rank_positions": list(positions),
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x["avg_rank"])

    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Use gemini-2.5-flash for title generation (fast and cheap)
    response = await query_model("google/gemini-2.5-flash", messages, timeout=30.0)

    if response is None:
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


async def run_full_arena(
    user_query: str,
    per_model_prompts: Optional[Dict[str, str]] = None,
    mode: str = "council",
    arena_models: Optional[List[str]] = None,
    chairman_model: str = CHAIRMAN_MODEL,
    iterations: Optional[int] = None,
    context_tokens: int = 0,
    context_tokens_map: Optional[Dict[str, int]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete arena deliberation process.

    Args:
        user_query: The user's question
        mode: Arena mode (council, round_robin, fight, stacks, complex_iterative, complex_questioning)

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    mode = (mode or "council").lower()
    runner = MODE_RUNNERS.get(mode, run_mode_council)
    results = await runner(
        user_query=user_query,
        per_model_prompts=per_model_prompts,
        arena_models=arena_models,
        chairman_model=chairman_model,
        iterations=iterations,
        context_tokens=context_tokens,
        context_tokens_map=context_tokens_map,
        progress_cb=progress_cb,
    )
    stage1_results, stage2_results, stage3_result, metadata = results
    normalized = normalize_arena_results(
        mode, stage1_results, stage2_results, stage3_result, metadata
    )
    meta_out = normalized[3]
    steps = meta_out.get("steps") or []
    if steps and "cost" not in meta_out:
        meta_out["cost"] = summarize_turn_cost(steps)
    if progress_cb:
        await progress_cb(
            {
                "type": "execution_complete",
                "data": {
                    "mode": mode,
                    "step_total": len(steps),
                    "steps": steps,
                    "council_mode": is_council_mode(mode),
                    "cost": meta_out.get("cost"),
                    "model_failures": meta_out.get("model_failures") or [],
                },
            }
        )
    return normalized


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------


async def run_mode_council(
    user_query: str,
    per_model_prompts: Optional[Dict[str, str]],
    arena_models: Optional[List[str]],
    chairman_model: str,
    iterations: Optional[int] = None,
    context_tokens: int = 0,
    context_tokens_map: Optional[Dict[str, int]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]] = None,
):
    """Council mode: All models answer, peer review, chairman synthesizes."""
    models = arena_models or ARENA_MODELS
    model_failures: List[Dict[str, Any]] = []
    total_steps = len(models) + 2  # stage1 per model + rankings + chair
    await emit_execution_start(
        progress_cb,
        "council",
        total_steps,
        ["answer"] * len(models) + ["rankings", "chair_final"],
    )

    stage1_results = await stage1_collect_responses(
        user_query,
        per_model_prompts,
        models,
        context_tokens_map=context_tokens_map,
        progress_cb=progress_cb,
        progress_total=total_steps,
        model_failures=model_failures,
    )
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {"mode": "council", "model_failures": model_failures}

    stage2_results, label_to_model, mid_turn_jobs = await stage2_collect_rankings(
        user_query,
        stage1_results,
        models,
        model_failures=model_failures,
        query_model_fn=query_model,
        chairman_model=chairman_model,
    )
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    rankings_step = {
        "model": "arena",
        "response": "\n\n".join(
            f"{r['model']}:\n{(r.get('ranking') or '')[:1200]}"
            for r in stage2_results
        ),
        "role": "rankings",
        "prompt_preview": "Peer rankings aggregation",
        "context_tokens": 0,
        "est_tokens": 0,
        **sum_usage_fields(stage2_results),
    }
    await emit_step_complete(
        progress_cb, rankings_step, len(stage1_results) + 1, total_steps
    )

    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        chairman_model=chairman_model,
        model_failures=model_failures,
    )
    chair_step = dict(stage3_result, role="chair_final")
    await emit_step_complete(progress_cb, chair_step, total_steps, total_steps)

    steps = [
        dict(s, context_tokens=s.get("context_tokens", context_tokens))
        for s in stage1_results
    ] + [rankings_step, chair_step]
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "mode": "council",
        "steps": steps,
        "cost": summarize_turn_cost(steps),
        "model_failures": model_failures,
    }
    if mid_turn_jobs:
        metadata["summarize_jobs"] = [j.to_dict() for j in mid_turn_jobs]
    return stage1_results, stage2_results, stage3_result, metadata


async def run_mode_round_robin(
    user_query: str,
    per_model_prompts: Optional[Dict[str, str]],
    arena_models: Optional[List[str]],
    chairman_model: str,
    iterations: Optional[int] = None,
    context_tokens: int = 0,
    context_tokens_map: Optional[Dict[str, int]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Tuple[List, List, Dict, Dict]:
    """Round Robin mode: Sequential refinement by each model."""
    models = arena_models or ARENA_MODELS
    context_map = context_tokens_map or {}
    model_failures: List[Dict[str, Any]] = []
    drafts: List[Dict[str, Any]] = []
    prior_text = ""
    passes = iterations or 1
    total_steps = passes * len(models) + 1
    await emit_execution_start(
        progress_cb,
        "round_robin",
        total_steps,
        [f"draft_p{p}_t{t}" for p in range(1, passes + 1) for t in range(1, len(models) + 1)]
        + ["chair_final"],
    )
    step_idx = 0
    for iteration in range(1, passes + 1):
        for turn, model in enumerate(models, start=1):
            base_prompt = per_model_prompts.get(model, user_query) if per_model_prompts else user_query
            had_prior = bool(prior_text and prior_text.strip())
            prior_for_prompt = prior_text if had_prior else "(none yet)"
            turn_prompt = render_prompt(
                "round_robin.turn",
                iteration=iteration,
                passes=passes,
                turn=turn,
                model_count=len(models),
                user_query=user_query,
                prior_for_prompt=prior_for_prompt,
            )
            full_prompt = f"{base_prompt}\n\n{turn_prompt}"
            start = time.time()
            resp = await query_model(model, [{"role": "user", "content": full_prompt}])
            elapsed_ms = int((time.time() - start) * 1000)
            ctx_tokens = context_map.get(model, context_map.get("__base__", context_tokens))
            if not is_usable_response(resp):
                model_failures.append(
                    failure_record(
                        model,
                        resp,
                        stage=f"draft_p{iteration}_t{turn}",
                        role=f"draft_p{iteration}_t{turn}",
                    )
                )
            text = resp.get("content", "") if is_usable_response(resp) else ""
            prior_snip = (
                (prior_text[:240] + "…")
                if prior_text and len(prior_text) > 240
                else (prior_text or "(none yet)")
            )
            draft_step = apply_usage_fields(
                {
                    "model": model,
                    "response": text,
                    "role": f"draft_p{iteration}_t{turn}",
                    "iteration": iteration,
                    "turn": turn,
                    "had_prior_draft": had_prior,
                    "prior_draft": prior_text if had_prior else None,
                    "turn_instruction": turn_prompt,
                    "orchestration_text": turn_prompt,
                    "prompt_preview": (
                        f"Pass {iteration}/{passes} turn {turn}/{len(models)} · "
                        f"Prior draft: {prior_snip}"
                    ),
                    "prompt_full": full_prompt,
                    "est_tokens": max(len(full_prompt) // 4, 1),
                    "context_tokens": ctx_tokens,
                    "duration_ms": elapsed_ms,
                },
                resp,
            )
            drafts.append(draft_step)
            if text.strip():
                prior_text = text
            step_idx += 1
            await emit_step_complete(progress_cb, draft_step, step_idx, total_steps)

    if not drafts:
        return [], [], {"model": "error", "response": "Round Robin failed: no drafts produced."}, {"mode": "round_robin"}

    chair_prompt = render_prompt(
        "round_robin.chair",
        prior_text=prior_text,
        user_query=user_query,
    )
    chair_orchestration = render_prompt(
        "round_robin.chair",
        prior_text=prior_text,
        user_query="[Grounded question and repository context attached separately; inspect RAG retrieval]",
    )
    start = time.time()
    chair_resp = await query_model(chairman_model, [{"role": "user", "content": chair_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    if not is_usable_response(chair_resp):
        model_failures.append(
            failure_record(
                chairman_model, chair_resp, stage="chair", role="chair_final"
            )
        )
    stage3_result = apply_usage_fields(
        {
            "model": chairman_model,
            "response": chair_resp.get("content", "")
            if is_usable_response(chair_resp)
            else "No response from chairman.",
            "role": "chair_final",
            "prior_draft": prior_text or None,
            "had_prior_draft": bool(prior_text),
            "orchestration_text": chair_orchestration,
            "prompt_preview": f"Chair final · draft {len(prior_text or '')} chars",
            "prompt_full": chair_prompt,
            "est_tokens": max(len(chair_prompt) // 4, 1),
            "context_tokens": context_map.get("__base__", context_tokens),
            "duration_ms": elapsed_ms,
        },
        chair_resp,
    )
    await emit_step_complete(progress_cb, stage3_result, total_steps, total_steps)

    steps = drafts + [stage3_result]
    metadata = {
        "mode": "round_robin",
        "steps": steps,
        "iterations": passes,
        "cost": summarize_turn_cost(steps),
        "model_failures": model_failures,
    }
    return drafts, [], stage3_result, metadata


async def run_mode_fight(
    user_query: str,
    per_model_prompts: Optional[Dict[str, str]],
    arena_models: Optional[List[str]],
    chairman_model: str,
    iterations: Optional[int] = None,
    context_tokens: int = 0,
    context_tokens_map: Optional[Dict[str, int]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]] = None,
):
    """Fight mode: Adversarial debate with critique and defense rounds."""
    models = arena_models or ARENA_MODELS
    prompt_map = per_model_prompts or {}
    context_map = context_tokens_map or {}
    model_failures: List[Dict[str, Any]] = []
    total_steps = len(models) * 3 + 1
    await emit_execution_start(
        progress_cb,
        "fight",
        total_steps,
        (["answer"] * len(models))
        + (["critique"] * len(models))
        + (["defense"] * len(models))
        + ["chair_final"],
    )

    answers = await stage1_collect_responses(
        user_query,
        prompt_map,
        models,
        context_tokens_map=context_map,
        progress_cb=progress_cb,
        emit_steps=False,
        progress_total=total_steps,
        progress_offset=0,
        model_failures=model_failures,
    )
    answers = [
        {
            **a,
            "role": "answer",
            "prompt_preview": a.get("prompt_preview"),
            "prompt_full": a.get("prompt_full", user_query),
            "est_tokens": a.get("est_tokens", max(len(user_query) // 4, 1)),
            "context_tokens": a.get("context_tokens", context_tokens),
            "orchestration_text": (
                f"{a.get('orchestration_text') or ''}\n\n{render_prompt('mode.fight')}"
            ).strip(),
        }
        for a in answers
    ]

    critiques: List[Dict[str, Any]] = []
    step_idx = len(models)
    for ans in answers:
        others = [a for a in answers if a["model"] != ans["model"]]
        peer_positions = "\n\n".join([f"{o['model']}:\n{o['response']}" for o in others])
        critique_prompt = render_prompt(
            "fight.critique",
            user_query=user_query,
            peer_positions=peer_positions,
        )
        peer_position_parts: List[Dict[str, Any]] = []
        for index, other in enumerate(others):
            if index:
                peer_position_parts.append(text_part("\n\n"))
            peer_position_parts.extend(
                [
                    text_part(f"{other['model']}:\n"),
                    artifact_ref(
                        "opening position",
                        producer_role="answer",
                        producer_model=other["model"],
                    ),
                ]
            )
        critique_orchestration, critique_provenance = render_projected_prompt(
            "fight.critique",
            user_query=provenance([context_ref("Grounded topic")]),
            peer_positions=provenance(peer_position_parts),
        )
        start = time.time()
        resp = await query_model(ans["model"], [{"role": "user", "content": critique_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        if not is_usable_response(resp):
            model_failures.append(
                failure_record(
                    ans["model"], resp, stage="critique", role="critique"
                )
            )
        critique_step = apply_usage_fields(
            {
                "model": ans["model"],
                "response": resp.get("content", "") if is_usable_response(resp) else "",
                "role": "critique",
                "prompt_preview": critique_prompt[:500],
                "prompt_full": critique_prompt,
                "orchestration_text": critique_orchestration,
                "prompt_provenance": critique_provenance,
                "est_tokens": max(len(critique_prompt) // 4, 1),
                "context_tokens": context_map.get(ans["model"], context_map.get("__base__", context_tokens)),
                "duration_ms": elapsed_ms,
            },
            resp,
        )
        critiques.append(critique_step)
        step_idx += 1
        await emit_step_complete(progress_cb, critique_step, step_idx, total_steps)

    defenses: List[Dict[str, Any]] = []
    for ans in answers:
        peer_crits = [c for c in critiques if c["model"] != ans["model"]]
        peer_critiques = "\n\n".join([f"{c['model']}:\n{c['response']}" for c in peer_crits])
        defense_prompt = render_prompt(
            "fight.defense",
            user_query=user_query,
            prior_answer=ans["response"],
            peer_critiques=peer_critiques,
        )
        peer_critique_parts: List[Dict[str, Any]] = []
        for index, critique in enumerate(peer_crits):
            if index:
                peer_critique_parts.append(text_part("\n\n"))
            peer_critique_parts.extend(
                [
                    text_part(f"{critique['model']}:\n"),
                    artifact_ref(
                        "peer critique",
                        producer_role="critique",
                        producer_model=critique["model"],
                    ),
                ]
            )
        defense_orchestration, defense_provenance = render_projected_prompt(
            "fight.defense",
            user_query=provenance([context_ref("Grounded topic")]),
            prior_answer=provenance(
                [
                    artifact_ref(
                        "this model's opening position",
                        producer_role="answer",
                        producer_model=ans["model"],
                    )
                ]
            ),
            peer_critiques=provenance(peer_critique_parts),
        )
        start = time.time()
        resp = await query_model(ans["model"], [{"role": "user", "content": defense_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        if not is_usable_response(resp):
            model_failures.append(
                failure_record(
                    ans["model"], resp, stage="defense", role="defense"
                )
            )
        defense_step = apply_usage_fields(
            {
                "model": ans["model"],
                "response": resp.get("content", "") if is_usable_response(resp) else "",
                "role": "defense",
                "prompt_full": defense_prompt,
                "prompt_preview": defense_prompt[:500],
                "orchestration_text": defense_orchestration,
                "prompt_provenance": defense_provenance,
                "est_tokens": max(len(defense_prompt) // 4, 1),
                "context_tokens": context_map.get(ans["model"], context_map.get("__base__", context_tokens)),
                "duration_ms": elapsed_ms,
            },
            resp,
        )
        defenses.append(defense_step)
        step_idx += 1
        await emit_step_complete(progress_cb, defense_step, step_idx, total_steps)

    chair_prompt = render_prompt(
        "fight.chair",
        user_query=user_query,
        answers="\n\n".join([f"{a['model']}:\n{a['response']}" for a in answers]),
        critiques="\n\n".join([f"{c['model']}:\n{c['response']}" for c in critiques]),
        defenses="\n\n".join([f"{d['model']}:\n{d['response']}" for d in defenses]),
    )
    def artifact_block(
        rows: List[Dict[str, Any]], role: str, label: str
    ) -> Dict[str, Any]:
        parts: List[Dict[str, Any]] = []
        for index, row in enumerate(rows):
            if index:
                parts.append(text_part("\n"))
            parts.extend(
                [
                    text_part(f"{row['model']}: "),
                    artifact_ref(
                        label,
                        producer_role=role,
                        producer_model=row["model"],
                    ),
                ]
            )
        return provenance(parts)

    chair_orchestration, chair_provenance = render_projected_prompt(
        "fight.chair",
        user_query=provenance([context_ref("Grounded topic")]),
        answers=artifact_block(answers, "answer", "opening position"),
        critiques=artifact_block(critiques, "critique", "peer critique"),
        defenses=artifact_block(defenses, "defense", "defense"),
    )
    start = time.time()
    chair_resp = await query_model(chairman_model, [{"role": "user", "content": chair_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    if not is_usable_response(chair_resp):
        model_failures.append(
            failure_record(
                chairman_model, chair_resp, stage="chair", role="chair_final"
            )
        )
    stage3_result = apply_usage_fields(
        {
            "model": chairman_model,
            "response": chair_resp.get("content", "")
            if is_usable_response(chair_resp)
            else "No response from chairman.",
            "role": "chair_final",
            "prompt_full": chair_prompt,
            "orchestration_text": chair_orchestration,
            "prompt_provenance": chair_provenance,
            "prompt_preview": chair_prompt[:500],
            "est_tokens": max(len(chair_prompt) // 4, 1),
            "context_tokens": context_map.get("__base__", context_tokens),
            "duration_ms": elapsed_ms,
        },
        chair_resp,
    )
    await emit_step_complete(progress_cb, stage3_result, total_steps, total_steps)

    steps = answers + critiques + defenses + [stage3_result]
    metadata = {
        "mode": "fight",
        "steps": steps,
        "cost": summarize_turn_cost(steps),
        "model_failures": model_failures,
    }
    return steps, [], stage3_result, metadata


async def run_mode_stacks(
    user_query: str,
    per_model_prompts: Optional[Dict[str, str]],
    arena_models: Optional[List[str]],
    chairman_model: str,
    iterations: Optional[int] = None,
    context_tokens: int = 0,
    context_tokens_map: Optional[Dict[str, int]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]] = None,
):
    """Stacks mode: Hierarchical merge with attack and defense phases."""
    models = arena_models or ARENA_MODELS
    context_map = context_tokens_map or {}
    if len(models) < 2:
        return [], [], {"model": "error", "response": "Stacks requires at least two models."}, {"mode": "stacks"}

    total_steps = 2 + 1 + (len(models[2:]) if len(models) > 2 else len(models[:2])) + 1 + len(models[:2]) + 1
    labels: List[str] = (
        ["stacks_answer"] * len(models[:2])
        + ["stacks_merge"]
        + ["stacks_critique"] * (len(models[2:]) if len(models) > 2 else len(models[:2]))
        + ["stacks_judge"]
        + ["stacks_defense"] * len(models[:2])
        + ["chair_final"]
    )
    await emit_execution_start(progress_cb, "stacks", total_steps, labels)

    answers = await stage1_collect_responses(
        user_query,
        per_model_prompts,
        models[:2],
        context_tokens_map=context_map,
        progress_cb=progress_cb,
        emit_steps=False,
        progress_total=total_steps,
        progress_offset=0,
    )
    answers = [
        {
            **a,
            "role": "stacks_answer",
            "prompt_preview": a.get("prompt_preview"),
            "prompt_full": a.get("prompt_full", user_query),
            "est_tokens": a.get("est_tokens", max(len(user_query) // 4, 1)),
            "context_tokens": a.get("context_tokens", context_tokens),
        }
        for a in answers
    ]

    merge_prompt = (
        f"Merge two answers while preserving optionality. Cite context if needed.\n\nA:\n{answers[0]['response']}\n\nB:\n{answers[1]['response']}"
    )
    start = time.time()
    cursor = len(answers)
    merged = await query_model(chairman_model, [{"role": "user", "content": merge_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    merged_text = merged.get("content", "") if merged else ""
    merged_step = apply_usage_fields(
        {
            "model": chairman_model,
            "response": merged_text,
            "role": "stacks_merge",
            "prompt_preview": merge_prompt[:500],
            "prompt_full": merge_prompt,
            "est_tokens": max(len(merge_prompt) // 4, 1),
            "context_tokens": context_map.get("__base__", context_tokens),
            "duration_ms": elapsed_ms,
        },
        merged,
    )
    cursor += 1
    await emit_step_complete(progress_cb, merged_step, cursor, total_steps)

    critics_models = models[2:] if len(models) > 2 else models[:2]
    critiques: List[Dict[str, Any]] = []
    for cm in critics_models:
        critique_prompt = (
            f"Critique the merged answer. Attack weak spots and missing context. Be concise.\n\nMerged:\n{merged_text}"
        )
        start = time.time()
        resp = await query_model(cm, [{"role": "user", "content": critique_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        critique_step = apply_usage_fields(
            {
                "model": cm,
                "response": resp.get("content", "") if resp else "",
                "role": "stacks_critique",
                "prompt_preview": critique_prompt[:500],
                "prompt_full": critique_prompt,
                "est_tokens": max(len(critique_prompt) // 4, 1),
                "context_tokens": context_map.get(cm, context_map.get("__base__", context_tokens)),
                "duration_ms": elapsed_ms,
            },
            resp,
        )
        critiques.append(critique_step)
        cursor += 1
        await emit_step_complete(progress_cb, critique_step, cursor, total_steps)

    judge_prompt = (
        f"Judge the merged answer vs critiques. Note what holds and fails.\nMerged:\n{merged_text}\n\nCritiques:\n" +
        "\n\n".join([f"{c['model']}:\n{c['response']}" for c in critiques])
    )
    start = time.time()
    judge = await query_model(chairman_model, [{"role": "user", "content": judge_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    judge_text = judge.get("content", "") if judge else ""
    judge_step = apply_usage_fields(
        {
            "model": chairman_model,
            "response": judge_text,
            "role": "stacks_judge",
            "prompt_preview": judge_prompt[:500],
            "prompt_full": judge_prompt,
            "est_tokens": max(len(judge_prompt) // 4, 1),
            "context_tokens": context_map.get("__base__", context_tokens),
            "duration_ms": elapsed_ms,
        },
        judge,
    )
    cursor += 1
    await emit_step_complete(progress_cb, judge_step, cursor, total_steps)

    defenses: List[Dict[str, Any]] = []
    for ans in answers:
        defense_prompt = (
            f"Defend the merged answer vs critiques; fix valid issues briefly.\nMerged:\n{merged_text}\n\nCritiques:\n" +
            "\n\n".join([f"{c['model']}:\n{c['response']}" for c in critiques])
        )
        start = time.time()
        resp = await query_model(ans["model"], [{"role": "user", "content": defense_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        defense_step = apply_usage_fields(
            {
                "model": ans["model"],
                "response": resp.get("content", "") if resp else "",
                "role": "stacks_defense",
                "prompt_preview": defense_prompt[:500],
                "prompt_full": defense_prompt,
                "est_tokens": max(len(defense_prompt) // 4, 1),
                "context_tokens": context_map.get(ans["model"], context_map.get("__base__", context_tokens)),
                "duration_ms": elapsed_ms,
            },
            resp,
        )
        defenses.append(defense_step)
        cursor += 1
        await emit_step_complete(progress_cb, defense_step, cursor, total_steps)

    final_prompt = (
        f"Produce final report; present both sides; note judgment rationale.\nJudge:\n{judge_text}\n\nMerged:\n{merged_text}\n\nDefenses:\n" +
        "\n\n".join([f"{d['model']}:\n{d['response']}" for d in defenses])
    )
    start = time.time()
    final_resp = await query_model(chairman_model, [{"role": "user", "content": final_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    final_text = final_resp.get("content", "") if final_resp else ""
    chair_step = apply_usage_fields(
        {
            "model": chairman_model,
            "response": final_text,
            "role": "chair_final",
            "prompt_preview": final_prompt[:500],
            "prompt_full": final_prompt,
            "est_tokens": max(len(final_prompt) // 4, 1),
            "context_tokens": context_map.get("__base__", context_tokens),
            "duration_ms": elapsed_ms,
        },
        final_resp,
    )
    await emit_step_complete(progress_cb, chair_step, total_steps, total_steps)

    steps = answers + [merged_step] + critiques + [judge_step] + defenses + [chair_step]
    metadata = {"mode": "stacks", "steps": steps, "cost": summarize_turn_cost(steps)}
    return steps, [], chair_step, metadata


async def run_mode_complex_iterative(
    user_query: str,
    per_model_prompts: Optional[Dict[str, str]],
    arena_models: Optional[List[str]],
    chairman_model: str,
    iterations: Optional[int] = None,
    context_tokens: int = 0,
    context_tokens_map: Optional[Dict[str, int]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]] = None,
):
    """Complex Iterative mode: Alternating extract/expand cycles."""
    models = arena_models or ARENA_MODELS
    context_map = context_tokens_map or {}
    if len(models) < 2:
        return [], [], {"model": "error", "response": "Complex Iterative needs at least two models."}, {"mode": "complex_iterative"}

    extract_model = models[0]
    expand_model = models[1]
    steps: List[Dict[str, Any]] = []
    summary = ""
    suggested = ""
    total_steps = 5
    await emit_execution_start(
        progress_cb,
        "complex_iterative",
        total_steps,
        ["extract", "expand", "extract", "expand", "chair_final"],
    )
    step_idx = 0
    for hop in range(4):  # extract/expand twice
        if hop % 2 == 0:
            prompt = f"Extract: summarize intent and constraints; list key facts; propose the next prompt. Context:\n{user_query}\n\nPrior summary:\n{summary}\nPrior suggested:\n{suggested}"
            start = time.time()
            resp = await query_model(extract_model, [{"role": "user", "content": prompt}])
            elapsed_ms = int((time.time() - start) * 1000)
            text = resp.get("content", "") if resp else ""
            extract_step = apply_usage_fields(
                {
                    "model": extract_model,
                    "response": text,
                    "role": "extract",
                    "prompt_preview": prompt[:500],
                    "prompt_full": prompt,
                    "est_tokens": max(len(prompt) // 4, 1),
                    "context_tokens": context_map.get(extract_model, context_map.get("__base__", context_tokens)),
                    "duration_ms": elapsed_ms,
                },
                resp,
            )
            steps.append(extract_step)
            summary = text or summary
            step_idx += 1
            await emit_step_complete(progress_cb, extract_step, step_idx, total_steps)
        else:
            prompt = f"Expand the prior extract; elaborate actionable detail and improve the suggested prompt.\nPrior summary:\n{summary}\nPrior suggested:\n{suggested}"
            start = time.time()
            resp = await query_model(expand_model, [{"role": "user", "content": prompt}])
            elapsed_ms = int((time.time() - start) * 1000)
            text = resp.get("content", "") if resp else ""
            expand_step = apply_usage_fields(
                {
                    "model": expand_model,
                    "response": text,
                    "role": "expand",
                    "prompt_preview": prompt[:500],
                    "prompt_full": prompt,
                    "est_tokens": max(len(prompt) // 4, 1),
                    "context_tokens": context_map.get(expand_model, context_map.get("__base__", context_tokens)),
                    "duration_ms": elapsed_ms,
                },
                resp,
            )
            steps.append(expand_step)
            suggested = text or suggested
            step_idx += 1
            await emit_step_complete(progress_cb, expand_step, step_idx, total_steps)

    final_prompt = f"Use the latest extract/expand chain to answer the original question.\nOriginal question:\n{user_query}\n\nLatest summary:\n{summary}\nLatest expansion:\n{suggested}\n\nFirst, briefly summarize what you saw in each extract/expand step (2 sentences or a short paragraph per item), labeled 'What I saw'. Then provide the final answer."
    start = time.time()
    final_resp = await query_model(chairman_model, [{"role": "user", "content": final_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    final_text = final_resp.get("content", "") if final_resp else ""
    chair_step = apply_usage_fields(
        {
            "model": chairman_model,
            "response": final_text,
            "role": "chair_final",
            "prompt_preview": final_prompt[:500],
            "prompt_full": final_prompt,
            "est_tokens": max(len(final_prompt) // 4, 1),
            "context_tokens": context_map.get("__base__", context_tokens),
            "duration_ms": elapsed_ms,
        },
        final_resp,
    )
    await emit_step_complete(progress_cb, chair_step, total_steps, total_steps)
    all_steps = steps + [chair_step]
    metadata = {
        "mode": "complex_iterative",
        "steps": all_steps,
        "cost": summarize_turn_cost(all_steps),
    }
    return steps, [], chair_step, metadata


async def run_mode_complex_questioning(
    user_query: str,
    per_model_prompts: Optional[Dict[str, str]],
    arena_models: Optional[List[str]],
    chairman_model: str,
    iterations: Optional[int] = None,
    context_tokens: int = 0,
    context_tokens_map: Optional[Dict[str, int]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]] = None,
):
    """Complex Questioning mode: Socratic method with self-questioning and muse rounds."""
    models = arena_models or ARENA_MODELS
    context_map = context_tokens_map or {}
    total_steps = len(models) * 3 + 2
    labels = (["answer"] * len(models)) + (["question_self"] * len(models)) + ["brief"] + (["muse"] * len(models)) + ["chair_final"]
    await emit_execution_start(progress_cb, "complex_questioning", total_steps, labels)
    answers = await stage1_collect_responses(
        user_query,
        per_model_prompts,
        models,
        context_tokens_map=context_map,
        progress_cb=progress_cb,
        emit_steps=False,
        progress_total=total_steps,
        progress_offset=0,
    )
    answers = [
        {
            **a,
            "role": "answer",
            "prompt_preview": a.get("prompt_preview"),
            "prompt_full": a.get("prompt_full", user_query),
            "est_tokens": a.get("est_tokens", max(len(user_query) // 4, 1)),
            "context_tokens": a.get("context_tokens", context_tokens),
        }
        for a in answers
    ]
    if not answers:
        return [], [], {"model": "error", "response": "Complex Questioning failed: no answers."}, {"mode": "complex_questioning"}

    questions: List[Dict[str, Any]] = []
    cursor = len(models)
    for ans in answers:
        peers = [a for a in answers if a["model"] != ans["model"]]
        question_prompt = (
            f"Re-read your answer through peers' lenses. Identify where you may be wrong or overconfident. Update briefly.\nYour answer:\n{ans['response']}\nPeers:\n" +
            "\n\n".join([f"{p['model']}:\n{p['response']}" for p in peers])
        )
        start = time.time()
        resp = await query_model(ans["model"], [{"role": "user", "content": question_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        question_step = apply_usage_fields(
            {
                "model": ans["model"],
                "response": resp.get("content", "") if resp else "",
                "role": "question_self",
                "prompt_preview": question_prompt[:500],
                "prompt_full": question_prompt,
                "est_tokens": max(len(question_prompt) // 4, 1),
                "context_tokens": context_map.get(ans["model"], context_map.get("__base__", context_tokens)),
                "duration_ms": elapsed_ms,
            },
            resp,
        )
        questions.append(question_step)
        cursor += 1
        await emit_step_complete(progress_cb, question_step, cursor, total_steps)

    brief_prompt = (
        f"Summarize convergences/divergences and produce a concise brief.\nQuestion:\n{user_query}\n\nAnswers:\n" +
        "\n\n".join([f"{a['model']}:\n{a['response']}" for a in answers]) +
        "\n\nReflections:\n" +
        "\n\n".join([f"{q['model']}:\n{q['response']}" for q in questions])
    )
    start = time.time()
    brief_resp = await query_model(chairman_model, [{"role": "user", "content": brief_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    brief_text = brief_resp.get("content", "") if brief_resp else ""
    brief_step = apply_usage_fields(
        {
            "model": chairman_model,
            "response": brief_text,
            "role": "brief",
            "prompt_preview": brief_prompt[:500],
            "prompt_full": brief_prompt,
            "est_tokens": max(len(brief_prompt) // 4, 1),
            "context_tokens": context_map.get("__base__", context_tokens),
            "duration_ms": elapsed_ms,
        },
        brief_resp,
    )
    cursor += 1
    await emit_step_complete(progress_cb, brief_step, cursor, total_steps)

    muses: List[Dict[str, Any]] = []
    for ans in answers:
        muse_prompt = (
            f"Consider the brief alone (no original context). Add reflections or corrections; avoid inventing new facts.\nBrief:\n{brief_text}"
        )
        start = time.time()
        resp = await query_model(ans["model"], [{"role": "user", "content": muse_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        muse_step = apply_usage_fields(
            {
                "model": ans["model"],
                "response": resp.get("content", "") if resp else "",
                "role": "muse",
                "prompt_preview": muse_prompt[:500],
                "prompt_full": muse_prompt,
                "est_tokens": max(len(muse_prompt) // 4, 1),
                "context_tokens": context_map.get(ans["model"], context_map.get("__base__", context_tokens)),
                "duration_ms": elapsed_ms,
            },
            resp,
        )
        muses.append(muse_step)
        cursor += 1
        await emit_step_complete(progress_cb, muse_step, cursor, total_steps)

    final_prompt = (
        f"Produce final answer based on debate and muse round; cite from earlier context if needed.\nBrief:\n{brief_text}\n\nMuse:\n" +
        "\n\n".join([f"{m['model']}:\n{m['response']}" for m in muses]) +
        "\n\nFirst, briefly summarize what you saw in each round (answers, self-questions, brief, muse) in 2 sentences or a short paragraph per item, labeled 'What I saw'. Then provide the final answer."
    )
    start = time.time()
    final_resp = await query_model(chairman_model, [{"role": "user", "content": final_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    final_text = final_resp.get("content", "") if final_resp else ""

    chair_step = apply_usage_fields(
        {
            "model": chairman_model,
            "response": final_text,
            "role": "chair_final",
            "prompt_preview": final_prompt[:500],
            "prompt_full": final_prompt,
            "est_tokens": max(len(final_prompt) // 4, 1),
            "context_tokens": context_map.get("__base__", context_tokens),
            "duration_ms": elapsed_ms,
        },
        final_resp,
    )
    await emit_step_complete(progress_cb, chair_step, total_steps, total_steps)
    steps = answers + questions + [brief_step] + muses + [chair_step]
    metadata = {"mode": "complex_questioning", "steps": steps, "cost": summarize_turn_cost(steps)}
    return steps, [], chair_step, metadata


# Mode runner registry
MODE_RUNNERS: Dict[str, Callable[..., Any]] = {
    "council": run_mode_council,
    "baseline": run_mode_council,
    "round_robin": run_mode_round_robin,
    "fight": run_mode_fight,
    "stacks": run_mode_stacks,
    "complex_iterative": run_mode_complex_iterative,
    "complex_questioning": run_mode_complex_questioning,
}

# Backwards compatibility aliases
run_full_council = run_full_arena  # Deprecated: use run_full_arena
