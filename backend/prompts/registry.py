"""First-class prompt registry — templates with prompt_id + version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PromptEntry:
    prompt_id: str
    version: str
    mode: str
    template: str
    variables: tuple[str, ...]
    description: str = ""


_PROMPTS: Dict[str, PromptEntry] = {}


def _register(entry: PromptEntry) -> None:
    _PROMPTS[entry.prompt_id] = entry


_register(
    PromptEntry(
        prompt_id="context.summarize.rag",
        version="1",
        mode="context",
        variables=("user_question", "context_block", "target_tokens"),
        description="Compress RAG context to fit a model's effective window.",
        template=(
            "You are the Chairman of an LLM arena. Summarize the provided context so it can be fed to"
            " another model with a smaller input window. Keep critical facts, constraints, and code/API"
            " signatures. Prefer bullet points. Include source hints (filenames/sections) when present."
            " Fit the context portion into roughly {target_tokens} tokens or less. Do not omit key safety"
            " constraints or numbers. Return only the compressed context, not an answer."
            "\n\nUser question:\n{user_question}\n\nContext to compress:\n{context_block}"
        ),
    )
)

_register(
    PromptEntry(
        prompt_id="context.summarize.user",
        version="1",
        mode="context",
        variables=("user_content", "target_tokens"),
        description="Compress user input alone to fit a model's effective window.",
        template=(
            "Compress the user's question or input so it can be fed to another model with a smaller"
            " input window. Preserve intent, constraints, numbers, and named entities. Prefer bullet"
            " points when helpful. Fit the user portion into roughly {target_tokens} tokens or less."
            " Return only the compressed user input, not an answer."
            "\n\nUser input to compress:\n{user_content}"
        ),
    )
)

_register(
    PromptEntry(
        prompt_id="mid_turn.semantic",
        version="1",
        mode="context",
        variables=("user_query", "responses_text", "target_tokens"),
        description="Between-stage semantic compression for peer evaluation (council/fight).",
        template=(
            "You are compressing intermediate arena responses for peer evaluation. Preserve each"
            " response's key claims, reasoning, and distinctive points. Keep response labels"
            " (Response A, Response B, etc.) intact. Fit the combined responses into roughly"
            " {target_tokens} tokens or less. Return only the compressed responses block."
            "\n\nOriginal question:\n{user_query}\n\nResponses to compress:\n{responses_text}"
        ),
    )
)

_register(
    PromptEntry(
        prompt_id="rag.control",
        version="1",
        mode="context",
        variables=(),
        description="Retrieval guidance appended when RAG context is injected.",
        template=(
            "\n\n# Retrieval guidance\n"
            "If the provided context seems incomplete or missing related files or functions, "
            "explicitly say what seems missing (by filename or concept) and ask the user to provide it."
        ),
    )
)

_register(
    PromptEntry(
        prompt_id="council.stage1",
        version="1",
        mode="council",
        variables=("prompt",),
        description="Stage 1 individual answer — single model, no panel voice.",
        template=(
            "Answer the user question directly. You are a single model providing your own answer.\n"
            "Do not speak for other models or imply a panel.\n\nUser question:\n{prompt}"
        ),
    )
)

_register(
    PromptEntry(
        prompt_id="council.rank",
        version="1",
        mode="council",
        variables=("user_query", "responses_text"),
        description="Stage 2 anonymized peer ranking.",
        template="""You are evaluating different responses to the following question:

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

Now provide your evaluation and ranking:""",
    )
)

_register(
    PromptEntry(
        prompt_id="council.chair",
        version="1",
        mode="council",
        variables=("user_query", "stage1_text", "stage2_text"),
        description="Stage 3 chairman synthesis for council mode.",
        template="""You are the Chairman of an LLM Arena. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

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

Provide a clear, well-reasoned final answer that represents the arena's collective wisdom:""",
    )
)

_register(
    PromptEntry(
        prompt_id="round_robin.turn",
        version="1",
        mode="round_robin",
        variables=("iteration", "passes", "turn", "model_count", "user_query", "prior_for_prompt"),
        description="Per-turn refinement instruction in round robin.",
        template=(
            "Round Robin pass {iteration}/{passes}, turn {turn}/{model_count}. "
            "You see the latest draft below. Improve accuracy and clarity; keep useful detail. "
            "Do not ignore the prior draft when one is provided.\n\n"
            "Original question: {user_query}\n\nLatest draft:\n{prior_for_prompt}"
        ),
    )
)

_register(
    PromptEntry(
        prompt_id="round_robin.chair",
        version="1",
        mode="round_robin",
        variables=("prior_text", "user_query"),
        description="Round robin chairman final synthesis.",
        template=(
            "Final draft from round robin:\n{prior_text}\n\nOriginal question:\n{user_query}\n\n"
            "Produce the final answer building on the latest draft; fix any errors and cite context if present."
        ),
    )
)

_MODE_PROMPTS = {
    "baseline": "Mode: Council. Multiple models answer, then rank, then chairman synthesizes.",
    "council": "Mode: Council. Multiple models answer, then rank, then chairman synthesizes.",
    "round_robin": (
        "Mode: Round Robin. Consider prior drafts, improve accuracy/clarity, keep useful detail."
    ),
    "fight": (
        "Mode: Fight. Take a clear position on the question and be ready to defend it. "
        "Later prompts will explicitly guide critiques and defenses."
    ),
    "stacks": (
        "Mode: Stacks. Provide an answer suitable for later merge/judge steps; retain optionality."
    ),
    "complex_iterative": (
        "Mode: Complex Iterative. Extract constraints and propose next steps succinctly."
    ),
    "complex_questioning": (
        "Mode: Complex Questioning. Provide answer and note uncertainties for later reflection."
    ),
}

for mode_key, text in _MODE_PROMPTS.items():
    _register(
        PromptEntry(
            prompt_id=f"mode.{mode_key}",
            version="1",
            mode=mode_key,
            variables=(),
            description=f"Mode instruction block for {mode_key}.",
            template=text,
        )
    )


def list_prompts(mode: Optional[str] = None) -> List[Dict[str, Any]]:
    """List registered prompts (optional mode filter)."""
    entries = sorted(_PROMPTS.values(), key=lambda e: e.prompt_id)
    if mode:
        mode_key = mode.lower()
        entries = [e for e in entries if e.mode == mode_key or e.prompt_id.startswith(f"mode.{mode_key}")]
    return [
        {
            "prompt_id": e.prompt_id,
            "version": e.version,
            "mode": e.mode,
            "variables": list(e.variables),
            "description": e.description,
        }
        for e in entries
    ]


def get_prompt(prompt_id: str) -> Optional[PromptEntry]:
    return _PROMPTS.get(prompt_id)


def render_prompt(prompt_id: str, **variables: Any) -> str:
    entry = _PROMPTS.get(prompt_id)
    if entry is None:
        raise KeyError(f"Unknown prompt_id: {prompt_id}")
    if entry.variables:
        missing = [v for v in entry.variables if v not in variables]
        if missing:
            raise ValueError(f"Missing variables for {prompt_id}: {missing}")
        return entry.template.format(**variables)
    return entry.template