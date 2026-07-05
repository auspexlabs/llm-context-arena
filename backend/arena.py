"""LLM Context Arena - Multi-mode orchestration for model deliberation."""

import asyncio
import time
from typing import List, Dict, Any, Tuple, Optional, Callable
from .openrouter import query_models_parallel, query_model
from .config import ARENA_MODELS, CHAIRMAN_MODEL


async def stage1_collect_responses(
    user_query: str,
    per_model_prompts: Optional[Dict[str, str]] = None,
    arena_models: Optional[List[str]] = None,
    context_tokens_map: Optional[Dict[str, int]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]] = None,
    emit_steps: bool = True,
    progress_total: Optional[int] = None,
    progress_offset: int = 0,
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
    completed = progress_offset

    async def _run_model(idx: int, model: str) -> Optional[Dict[str, Any]]:
        prompt = per_model_prompts.get(model, user_query) if per_model_prompts else user_query
        context_tokens = context_map.get(model, context_map.get("__base__", 0))
        if progress_cb:
            await progress_cb(
                {
                    "type": "mode_progress",
                    "data": {
                        "completed": completed,
                        "total": total_steps,
                        "label": "answer",
                        "active_model": model,
                        "state": "start",
                    },
                }
            )
        individual_prompt = (
            f"Answer the user question directly. You are a single model providing your own answer.\n"
            f"Do not speak for other models or imply a panel.\n\nUser question:\n{prompt}"
        )
        resp = await query_model(
            model,
            [{"role": "user", "content": individual_prompt}],
        )
        if progress_cb:
            await progress_cb(
                {
                    "type": "mode_progress",
                    "data": {
                        "completed": min(completed + 1, total_steps),
                        "total": total_steps,
                        "label": "answer",
                        "active_model": model,
                        "state": "finish",
                        "context_tokens": context_tokens,
                        "est_tokens": max(len(individual_prompt) // 4, 1),
                        "step": {
                            "model": model,
                            "response": resp.get("content", ""),
                            "role": "answer",
                            "prompt_preview": individual_prompt[:200],
                            "est_tokens": max(len(individual_prompt) // 4, 1),
                            "context_tokens": context_tokens,
                        },
                    },
                }
            )
        if resp is None:
            return None
        return {
            "model": model,
            "response": resp.get("content", ""),
            "role": "answer",
            "prompt_preview": individual_prompt[:500],
            "prompt_full": individual_prompt,
            "est_tokens": max(len(individual_prompt) // 4, 1),
            "context_tokens": context_tokens,
        }

    tasks = [asyncio.create_task(_run_model(idx, model)) for idx, model in enumerate(models)]
    responses_list = await asyncio.gather(*tasks)
    # Filter out failures
    return [res for res in responses_list if res is not None]


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    arena_models: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
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

    ranking_prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Then, at the very end of your response, provide a final ranking.
3. IMPORTANT CRITERION: Penalize any response that ignores instructions or invents extra roles. Favor responses that followed instructions exactly.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all arena models in parallel
    models = arena_models or ARENA_MODELS
    responses = await query_models_parallel(models, messages)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed
            })

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    chairman_model: str = CHAIRMAN_MODEL,
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

    chairman_prompt = f"""You are the Chairman of an LLM Arena. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}

First, briefly summarize what you saw in each stage (2 sentences or a short paragraph per item), covering the key points of each response and ranking. Label this section "What I saw".

Then, provide the final answer to the original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the arena's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    response = await query_model(chairman_model, messages)

    if response is None:
        # Fallback if chairman fails
        return {
            "model": chairman_model,
            "response": "Error: Unable to generate final synthesis."
        }

    return {
        "model": chairman_model,
        "response": response.get('content', ''),
        "role": "chair_final",
        "prompt_preview": chairman_prompt[:500],
        "est_tokens": max(len(chairman_prompt) // 4, 1),
        "context_tokens": 0,
    }


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
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

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
    if progress_cb and metadata.get("steps"):
        await progress_cb(
            {
                "type": "mode_progress",
                "data": {
                    "current": len(metadata.get("steps", [])),
                    "total": len(metadata.get("steps", [])),
                    "label": "Complete",
                    "state": "finish",
                },
            }
        )
    return results


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
    total_steps = len(models) + 2  # stage1 per model + rankings + chair
    if progress_cb:
        await progress_cb({"type": "mode_steps", "data": {"total": total_steps, "labels": ["answer"] * len(models) + ["rankings", "chair_final"]}})

    stage1_results = await stage1_collect_responses(
        user_query,
        per_model_prompts,
        models,
        context_tokens_map=context_tokens_map,
        progress_cb=progress_cb,
        progress_total=total_steps,
    )
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {"mode": "council"}

    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": len(stage1_results), "total": total_steps, "label": "rankings", "active_model": "arena", "state": "start"}})
    stage2_results, label_to_model = await stage2_collect_rankings(user_query, stage1_results, models)
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": len(stage1_results) + 1, "total": total_steps, "label": "rankings", "active_model": "arena", "state": "finish"}})
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": len(stage1_results) + 1, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "start"}})
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        chairman_model=chairman_model,
    )
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": total_steps, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "finish"}})

    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "mode": "council",
        "steps": [
            dict(s, context_tokens=s.get("context_tokens", context_tokens))
            for s in stage1_results
        ]
        + [
            {
                "model": "arena",
                "response": "",
                "role": "rankings",
                "prompt_preview": "Peer rankings aggregation",
                "context_tokens": 0,
                "est_tokens": 0,
            },
            dict(stage3_result, role="chair_final"),
        ],
    }
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
    drafts: List[Dict[str, Any]] = []
    prior_text = ""
    passes = iterations or 1
    total_steps = passes * len(models) + 1
    if progress_cb:
        await progress_cb(
            {
                "type": "mode_steps",
                "data": {
                    "total": total_steps,
                    "labels": [f"draft_p{p}_t{t}" for p in range(1, passes + 1) for t in range(1, len(models) + 1)] + ["chair_final"],
                },
            }
        )
    step_idx = 0
    for iteration in range(1, passes + 1):
        for turn, model in enumerate(models, start=1):
            base_prompt = per_model_prompts.get(model, user_query) if per_model_prompts else user_query
            turn_prompt = (
                f"Round Robin pass {iteration}/{passes}, turn {turn}/{len(models)}. "
                f"You see the latest draft below. Improve accuracy and clarity; keep useful detail. "
                f"Original question: {user_query}\n\nLatest draft:\n{prior_text or '(none yet)'}"
            )
            full_prompt = f"{base_prompt}\n\n{turn_prompt}"
            start = time.time()
            if progress_cb:
                await progress_cb(
                    {
                        "type": "mode_progress",
                        "data": {
                            "current": step_idx,
                            "total": total_steps,
                            "label": f"draft_{iteration}/{passes}",
                            "model": model,
                            "state": "start",
                        },
                    }
                )
            resp = await query_model(model, [{"role": "user", "content": full_prompt}])
            elapsed_ms = int((time.time() - start) * 1000)
            text = resp.get("content", "") if resp else ""
            ctx_tokens = context_map.get(model, context_map.get("__base__", context_tokens))
            drafts.append({
                "model": model,
                "response": text,
                "role": f"draft_p{iteration}_t{turn}",
                "prompt_preview": full_prompt[:500],
                "prompt_full": full_prompt,
                "est_tokens": max(len(full_prompt) // 4, 1),
                "context_tokens": ctx_tokens,
                "duration_ms": elapsed_ms,
            })
            prior_text = text or prior_text
            step_idx += 1
            if progress_cb:
                await progress_cb(
                    {
                        "type": "mode_progress",
                        "data": {
                            "current": step_idx,
                            "total": total_steps,
                            "label": f"draft_{iteration}/{passes}",
                            "model": model,
                            "state": "finish",
                        },
                    }
                )

    if not drafts:
        return [], [], {"model": "error", "response": "Round Robin failed: no drafts produced."}, {"mode": "round_robin"}

    chair_prompt = (
        f"Final draft from round robin:\n{prior_text}\n\nOriginal question:\n{user_query}\n\n"
        "Produce the final answer building on the latest draft; fix any errors and cite context if present."
    )
    start = time.time()
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": step_idx, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "start"}})
    chair_resp = await query_model(chairman_model, [{"role": "user", "content": chair_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    stage3_result = {
        "model": chairman_model,
        "response": chair_resp.get("content", "") if chair_resp else "No response from chairman.",
        "role": "chair_final",
        "prompt_preview": chair_prompt[:500],
        "prompt_full": chair_prompt,
        "est_tokens": max(len(chair_prompt) // 4, 1),
        "context_tokens": context_map.get("__base__", context_tokens),
        "duration_ms": elapsed_ms,
    }
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": total_steps, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "finish", "est_tokens": max(len(chair_prompt) // 4, 1)}})

    metadata = {"mode": "round_robin", "steps": drafts + [dict(stage3_result, role="chair_final")], "iterations": passes}
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
    total_steps = len(models) * 3 + 1
    if progress_cb:
        await progress_cb(
            {
                "type": "mode_steps",
                "data": {
                    "total": total_steps,
                    "labels": (["answer"] * len(models)) + (["critique"] * len(models)) + (["defense"] * len(models)) + ["chair_final"],
                },
            }
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
    )
    answers = [
        {
            "model": a["model"],
            "response": a["response"],
            "role": "answer",
            "prompt_preview": a.get("prompt_preview"),
            "prompt_full": a.get("prompt_full", user_query),
            "est_tokens": a.get("est_tokens", max(len(user_query) // 4, 1)),
            "context_tokens": a.get("context_tokens", context_tokens),
        }
        for a in answers
    ]

    critiques: List[Dict[str, Any]] = []
    step_idx = len(models)
    for ans in answers:
        others = [a for a in answers if a["model"] != ans["model"]]
        critique_prompt = (
            "Provided is a position on a specific topic (context is included). "
            "Argue against it directly and critique the reasoning—call out gaps, weak claims, and missing evidence.\n\n"
            f"Topic:\n{user_query}\n\n"
            "Peer positions:\n" +
            "\n\n".join([f"{o['model']}:\n{o['response']}" for o in others])
        )
        start = time.time()
        if progress_cb:
            await progress_cb(
                {
                    "type": "mode_progress",
                    "data": {
                        "current": step_idx,
                        "total": total_steps,
                        "label": "critique",
                        "model": ans["model"],
                        "state": "start",
                    },
                }
            )
        resp = await query_model(ans["model"], [{"role": "user", "content": critique_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        critiques.append({
            "model": ans["model"],
            "response": resp.get("content", "") if resp else "",
            "role": "critique",
            "prompt_preview": critique_prompt[:500],
            "prompt_full": critique_prompt,
            "est_tokens": max(len(critique_prompt) // 4, 1),
            "context_tokens": context_map.get(ans["model"], context_map.get("__base__", context_tokens)),
            "duration_ms": elapsed_ms,
        })
        step_idx += 1
        if progress_cb:
            await progress_cb(
                {
                    "type": "mode_progress",
                    "data": {
                        "current": step_idx,
                        "total": total_steps,
                        "label": "critique",
                        "model": ans["model"],
                        "state": "finish",
                    },
                }
            )

    defenses: List[Dict[str, Any]] = []
    for ans in answers:
        peer_crits = [c for c in critiques if c["model"] != ans["model"]]
        defense_prompt = (
            "Here is a critique to your previous message; please defend your position. "
            "Address the critiques directly and update your stance if needed.\n\n"
            f"Original topic:\n{user_query}\n\n"
            f"Your prior answer:\n{ans['response']}\n\n"
            "Peer critiques:\n" +
            "\n\n".join([f"{c['model']}:\n{c['response']}" for c in peer_crits])
        )
        start = time.time()
        if progress_cb:
            await progress_cb(
                {
                    "type": "mode_progress",
                    "data": {
                        "current": step_idx,
                        "total": total_steps,
                        "label": "defense",
                        "model": ans["model"],
                        "state": "start",
                    },
                }
            )
        resp = await query_model(ans["model"], [{"role": "user", "content": defense_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        defenses.append({
            "model": ans["model"],
            "response": resp.get("content", "") if resp else "",
            "role": "defense",
            "prompt_full": defense_prompt,
            "prompt_preview": defense_prompt[:500],
            "est_tokens": max(len(defense_prompt) // 4, 1),
            "context_tokens": context_map.get(ans["model"], context_map.get("__base__", context_tokens)),
            "duration_ms": elapsed_ms,
        })
        step_idx += 1
        if progress_cb:
            await progress_cb(
                {
                    "type": "mode_progress",
                    "data": {
                        "current": step_idx,
                        "total": total_steps,
                        "label": "defense",
                        "model": ans["model"],
                        "state": "finish",
                    },
                }
            )

    chair_prompt = (
        f"Debate on: {user_query}\n\nAnswers:\n" +
        "\n\n".join([f"{a['model']}:\n{a['response']}" for a in answers]) +
        "\n\nCritiques:\n" +
        "\n\n".join([f"{c['model']}:\n{c['response']}" for c in critiques]) +
        "\n\nDefenses:\n" +
        "\n\n".join([f"{d['model']}:\n{d['response']}" for d in defenses]) +
        "\n\nSummarize consensus, disagreements, and provide the best combined answer."
    )
    start = time.time()
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": step_idx, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "start"}})
    chair_resp = await query_model(chairman_model, [{"role": "user", "content": chair_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    stage3_result = {
        "model": chairman_model,
        "response": chair_resp.get("content", "") if chair_resp else "No response from chairman.",
        "role": "chair_final",
        "prompt_full": chair_prompt,
        "prompt_preview": chair_prompt[:500],
        "est_tokens": max(len(chair_prompt) // 4, 1),
        "context_tokens": context_map.get("__base__", context_tokens),
        "duration_ms": elapsed_ms,
    }
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": total_steps, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "finish", "est_tokens": max(len(chair_prompt)//4,1)}})

    steps = answers + critiques + defenses + [dict(stage3_result, role="chair_final")]
    metadata = {"mode": "fight", "steps": steps}
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
    if progress_cb:
        labels: List[str] = (
            ["stacks_answer"] * len(models[:2])
            + ["stacks_merge"]
            + ["stacks_critique"] * (len(models[2:]) if len(models) > 2 else len(models[:2]))
            + ["stacks_judge"]
            + ["stacks_defense"] * len(models[:2])
            + ["chair_final"]
        )
        await progress_cb({"type": "mode_steps", "data": {"total": total_steps, "labels": labels}})

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
    answers = [{"model": a["model"], "response": a["response"], "role": "stacks_answer", "prompt_preview": a.get("prompt_preview"), "prompt_full": a.get("prompt_full", user_query), "est_tokens": a.get("est_tokens", max(len(user_query) // 4, 1)), "context_tokens": a.get("context_tokens", context_tokens)} for a in answers]

    merge_prompt = (
        f"Merge two answers while preserving optionality. Cite context if needed.\n\nA:\n{answers[0]['response']}\n\nB:\n{answers[1]['response']}"
    )
    start = time.time()
    cursor = len(answers)
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "stacks_merge", "active_model": chairman_model, "state": "start"}})
    merged = await query_model(chairman_model, [{"role": "user", "content": merge_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    merged_text = merged.get("content", "") if merged else ""
    merged_step = {"model": chairman_model, "response": merged_text, "role": "stacks_merge", "prompt_preview": merge_prompt[:500], "prompt_full": merge_prompt, "est_tokens": max(len(merge_prompt) // 4, 1), "context_tokens": context_map.get("__base__", context_tokens), "duration_ms": elapsed_ms}
    if progress_cb:
        cursor += 1
        await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "stacks_merge", "active_model": chairman_model, "state": "finish"}})

    critics_models = models[2:] if len(models) > 2 else models[:2]
    critiques: List[Dict[str, Any]] = []
    for cm in critics_models:
        critique_prompt = (
            f"Critique the merged answer. Attack weak spots and missing context. Be concise.\n\nMerged:\n{merged_text}"
        )
        if progress_cb:
            await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "stacks_critique", "active_model": cm, "state": "start"}})
        start = time.time()
        resp = await query_model(cm, [{"role": "user", "content": critique_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        critiques.append({"model": cm, "response": resp.get("content", "") if resp else "", "role": "stacks_critique", "prompt_preview": critique_prompt[:500], "prompt_full": critique_prompt, "est_tokens": max(len(critique_prompt) // 4, 1), "context_tokens": context_map.get(cm, context_map.get("__base__", context_tokens)), "duration_ms": elapsed_ms})
        if progress_cb:
            cursor += 1
            await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "stacks_critique", "active_model": cm, "state": "finish"}})

    judge_prompt = (
        f"Judge the merged answer vs critiques. Note what holds and fails.\nMerged:\n{merged_text}\n\nCritiques:\n" +
        "\n\n".join([f"{c['model']}:\n{c['response']}" for c in critiques])
    )
    start = time.time()
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "stacks_judge", "active_model": chairman_model, "state": "start"}})
    judge = await query_model(chairman_model, [{"role": "user", "content": judge_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    judge_text = judge.get("content", "") if judge else ""
    judge_step = {"model": chairman_model, "response": judge_text, "role": "stacks_judge", "prompt_preview": judge_prompt[:500], "prompt_full": judge_prompt, "est_tokens": max(len(judge_prompt) // 4, 1), "context_tokens": context_map.get("__base__", context_tokens), "duration_ms": elapsed_ms}
    if progress_cb:
        cursor += 1
        await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "stacks_judge", "active_model": chairman_model, "state": "finish"}})

    defenses: List[Dict[str, Any]] = []
    for ans in answers:
        defense_prompt = (
            f"Defend the merged answer vs critiques; fix valid issues briefly.\nMerged:\n{merged_text}\n\nCritiques:\n" +
            "\n\n".join([f"{c['model']}:\n{c['response']}" for c in critiques])
        )
        if progress_cb:
            await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "stacks_defense", "active_model": ans["model"], "state": "start"}})
        start = time.time()
        resp = await query_model(ans["model"], [{"role": "user", "content": defense_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        defenses.append({"model": ans["model"], "response": resp.get("content", "") if resp else "", "role": "stacks_defense", "prompt_preview": defense_prompt[:500], "prompt_full": defense_prompt, "est_tokens": max(len(defense_prompt) // 4, 1), "context_tokens": context_map.get(ans["model"], context_map.get("__base__", context_tokens)), "duration_ms": elapsed_ms})
        if progress_cb:
            cursor += 1
            await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "stacks_defense", "active_model": ans["model"], "state": "finish"}})

    final_prompt = (
        f"Produce final report; present both sides; note judgment rationale.\nJudge:\n{judge_text}\n\nMerged:\n{merged_text}\n\nDefenses:\n" +
        "\n\n".join([f"{d['model']}:\n{d['response']}" for d in defenses])
    )
    start = time.time()
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "start"}})
    final_resp = await query_model(chairman_model, [{"role": "user", "content": final_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    final_text = final_resp.get("content", "") if final_resp else ""

    steps = answers + [merged_step] + critiques + [judge_step] + defenses
    metadata = {"mode": "stacks", "steps": steps + [{"model": chairman_model, "response": final_text, "role": "chair_final", "prompt_preview": final_prompt[:500], "prompt_full": final_prompt, "est_tokens": max(len(final_prompt) // 4, 1), "context_tokens": context_map.get("__base__", context_tokens), "duration_ms": elapsed_ms}]}
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": total_steps, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "finish", "est_tokens": max(len(final_prompt)//4,1)}})
    return steps, [], {"model": chairman_model, "response": final_text, "role": "chair_final", "prompt_preview": final_prompt[:500], "prompt_full": final_prompt, "est_tokens": max(len(final_prompt) // 4, 1), "context_tokens": context_map.get("__base__", context_tokens), "duration_ms": elapsed_ms}, metadata


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
    if progress_cb:
        await progress_cb({"type": "mode_steps", "data": {"total": total_steps, "labels": ["extract", "expand", "extract", "expand", "chair_final"]}})
    step_idx = 0
    for hop in range(4):  # extract/expand twice
        if hop % 2 == 0:
            prompt = f"Extract: summarize intent and constraints; list key facts; propose the next prompt. Context:\n{user_query}\n\nPrior summary:\n{summary}\nPrior suggested:\n{suggested}"
            start = time.time()
            if progress_cb:
                await progress_cb({"type": "mode_progress", "data": {"completed": step_idx, "total": total_steps, "label": "extract", "active_model": extract_model, "state": "start"}})
            resp = await query_model(extract_model, [{"role": "user", "content": prompt}])
            elapsed_ms = int((time.time() - start) * 1000)
            text = resp.get("content", "") if resp else ""
            steps.append({"model": extract_model, "response": text, "role": "extract", "prompt_preview": prompt[:500], "prompt_full": prompt, "est_tokens": max(len(prompt) // 4, 1), "context_tokens": context_map.get(extract_model, context_map.get("__base__", context_tokens)), "duration_ms": elapsed_ms})
            summary = text or summary
            step_idx += 1
            if progress_cb:
                await progress_cb({"type": "mode_progress", "data": {"completed": step_idx, "total": total_steps, "label": "extract", "active_model": extract_model, "state": "finish"}})
        else:
            prompt = f"Expand the prior extract; elaborate actionable detail and improve the suggested prompt.\nPrior summary:\n{summary}\nPrior suggested:\n{suggested}"
            start = time.time()
            if progress_cb:
                await progress_cb({"type": "mode_progress", "data": {"completed": step_idx, "total": total_steps, "label": "expand", "active_model": expand_model, "state": "start"}})
            resp = await query_model(expand_model, [{"role": "user", "content": prompt}])
            elapsed_ms = int((time.time() - start) * 1000)
            text = resp.get("content", "") if resp else ""
            steps.append({"model": expand_model, "response": text, "role": "expand", "prompt_preview": prompt[:500], "prompt_full": prompt, "est_tokens": max(len(prompt) // 4, 1), "context_tokens": context_map.get(expand_model, context_map.get("__base__", context_tokens)), "duration_ms": elapsed_ms})
            suggested = text or suggested
            step_idx += 1
            if progress_cb:
                await progress_cb({"type": "mode_progress", "data": {"completed": step_idx, "total": total_steps, "label": "expand", "active_model": expand_model, "state": "finish"}})

    final_prompt = f"Use the latest extract/expand chain to answer the original question.\nOriginal question:\n{user_query}\n\nLatest summary:\n{summary}\nLatest expansion:\n{suggested}\n\nFirst, briefly summarize what you saw in each extract/expand step (2 sentences or a short paragraph per item), labeled 'What I saw'. Then provide the final answer."
    start = time.time()
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": step_idx, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "start"}})
    final_resp = await query_model(chairman_model, [{"role": "user", "content": final_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    final_text = final_resp.get("content", "") if final_resp else ""
    metadata = {"mode": "complex_iterative", "steps": steps}
    chair_step = {"model": chairman_model, "response": final_text, "role": "chair_final", "prompt_preview": final_prompt[:500], "prompt_full": final_prompt, "est_tokens": max(len(final_prompt) // 4, 1), "context_tokens": context_map.get("__base__", context_tokens), "duration_ms": elapsed_ms}
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": total_steps, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "finish", "est_tokens": chair_step["est_tokens"]}})
    metadata["steps"] = steps + [chair_step]
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
    if progress_cb:
        labels = (["answer"] * len(models)) + (["question_self"] * len(models)) + ["brief"] + (["muse"] * len(models)) + ["chair_final"]
        await progress_cb({"type": "mode_steps", "data": {"total": total_steps, "labels": labels}})
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
    answers = [{"model": a["model"], "response": a["response"], "role": "answer", "prompt_preview": a.get("prompt_preview"), "prompt_full": a.get("prompt_full", user_query), "est_tokens": a.get("est_tokens", max(len(user_query) // 4, 1)), "context_tokens": a.get("context_tokens", context_tokens)} for a in answers]
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
        if progress_cb:
            await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "question_self", "active_model": ans["model"], "state": "start"}})
        resp = await query_model(ans["model"], [{"role": "user", "content": question_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        questions.append({
            "model": ans["model"],
            "response": resp.get("content", "") if resp else "",
            "role": "question_self",
            "prompt_preview": question_prompt[:500],
            "prompt_full": question_prompt,
            "est_tokens": max(len(question_prompt) // 4, 1),
            "context_tokens": context_map.get(ans["model"], context_map.get("__base__", context_tokens)),
            "duration_ms": elapsed_ms,
        })
        cursor += 1
        if progress_cb:
            await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "question_self", "active_model": ans["model"], "state": "finish", "step": questions[-1]}})

    brief_prompt = (
        f"Summarize convergences/divergences and produce a concise brief.\nQuestion:\n{user_query}\n\nAnswers:\n" +
        "\n\n".join([f"{a['model']}:\n{a['response']}" for a in answers]) +
        "\n\nReflections:\n" +
        "\n\n".join([f"{q['model']}:\n{q['response']}" for q in questions])
    )
    start = time.time()
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "brief", "active_model": chairman_model, "state": "start"}})
    brief_resp = await query_model(chairman_model, [{"role": "user", "content": brief_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    brief_text = brief_resp.get("content", "") if brief_resp else ""
    brief_step = {"model": chairman_model, "response": brief_text, "role": "brief", "prompt_preview": brief_prompt[:500], "prompt_full": brief_prompt, "est_tokens": max(len(brief_prompt) // 4, 1), "context_tokens": context_map.get("__base__", context_tokens), "duration_ms": elapsed_ms}
    brief_step["context_tokens"] = context_map.get("__base__", context_tokens)
    cursor += 1
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "brief", "active_model": chairman_model, "state": "finish", "step": brief_step}})

    muses: List[Dict[str, Any]] = []
    for ans in answers:
        muse_prompt = (
            f"Consider the brief alone (no original context). Add reflections or corrections; avoid inventing new facts.\nBrief:\n{brief_text}"
        )
        start = time.time()
        if progress_cb:
            await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "muse", "active_model": ans["model"], "state": "start"}})
        resp = await query_model(ans["model"], [{"role": "user", "content": muse_prompt}])
        elapsed_ms = int((time.time() - start) * 1000)
        muses.append({
            "model": ans["model"],
            "response": resp.get("content", "") if resp else "",
            "role": "muse",
            "prompt_preview": muse_prompt[:500],
            "prompt_full": muse_prompt,
            "est_tokens": max(len(muse_prompt) // 4, 1),
            "context_tokens": context_map.get(ans["model"], context_map.get("__base__", context_tokens)),
            "duration_ms": elapsed_ms,
        })
        cursor += 1
        if progress_cb:
            await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "muse", "active_model": ans["model"], "state": "finish", "step": muses[-1]}})

    final_prompt = (
        f"Produce final answer based on debate and muse round; cite from earlier context if needed.\nBrief:\n{brief_text}\n\nMuse:\n" +
        "\n\n".join([f"{m['model']}:\n{m['response']}" for m in muses]) +
        "\n\nFirst, briefly summarize what you saw in each round (answers, self-questions, brief, muse) in 2 sentences or a short paragraph per item, labeled 'What I saw'. Then provide the final answer."
    )
    start = time.time()
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": cursor, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "start"}})
    final_resp = await query_model(chairman_model, [{"role": "user", "content": final_prompt}])
    elapsed_ms = int((time.time() - start) * 1000)
    final_text = final_resp.get("content", "") if final_resp else ""

    chair_step = {"model": chairman_model, "response": final_text, "role": "chair_final", "prompt_preview": final_prompt[:500], "prompt_full": final_prompt, "est_tokens": max(len(final_prompt) // 4, 1), "context_tokens": context_map.get("__base__", context_tokens), "duration_ms": elapsed_ms}
    steps = answers + questions + [brief_step] + muses
    metadata = {"mode": "complex_questioning", "steps": steps + [chair_step]}
    if progress_cb:
        await progress_cb({"type": "mode_progress", "data": {"completed": total_steps, "total": total_steps, "label": "chair_final", "active_model": chairman_model, "state": "finish", "est_tokens": chair_step["est_tokens"], "step": chair_step}})
    return steps, [], chair_step, metadata


# Mode runner registry
MODE_RUNNERS: Dict[str, Callable[..., Any]] = {
    "council": run_mode_council,
    "round_robin": run_mode_round_robin,
    "fight": run_mode_fight,
    "stacks": run_mode_stacks,
    "complex_iterative": run_mode_complex_iterative,
    "complex_questioning": run_mode_complex_questioning,
}

# Backwards compatibility aliases
run_full_council = run_full_arena  # Deprecated: use run_full_arena
