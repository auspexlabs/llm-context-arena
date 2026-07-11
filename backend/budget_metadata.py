"""BudgetDecision, SummarizeJob, and PromptComponentBudget records (DEC-018)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PromptComponentBudget:
    """Per-model token breakdown by prompt component."""

    rag: int = 0
    system: int = 0
    mode: int = 0
    turn: int = 0
    user: int = 0
    directives: int = 0
    total: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BudgetDecision:
    """Per-model limit and component budget for a turn."""

    model_id: str
    registered_limit: int
    effective_limit: int
    available_tokens: int
    tag_modifier: float
    model_modifier: float
    summarized: bool
    components: PromptComponentBudget
    tags: List[str] = field(default_factory=list)
    budget_override: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["components"] = self.components.to_dict()
        return data


@dataclass
class SummarizeJob:
    """One summarizer invocation (fresh one-shot session)."""

    prompt_id: str
    target_model_id: str
    summarizer_model: str
    chairman_fallback: bool
    duration_ms: int
    input_tokens: int
    output_tokens: int
    target_tokens: int
    cache_hit: bool
    outcome: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)