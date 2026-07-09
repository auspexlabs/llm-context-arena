"""Pydantic models for LLM Context Arena.

Provides typed data structures for arena execution, stages, and results.
These models standardize the internal state passed between components.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ArenaMode(str, Enum):
    """Available arena deliberation modes."""
    COUNCIL = "council"  # Multi-model answer → peer review → chairman synthesis
    ROUND_ROBIN = "round_robin"  # Sequential refinement
    FIGHT = "fight"  # Adversarial debate
    STACKS = "stacks"  # Hierarchical merge + attack
    COMPLEX_ITERATIVE = "complex_iterative"  # Extract/expand alternation
    COMPLEX_QUESTIONING = "complex_questioning"  # Socratic method


class ModelResponse(BaseModel):
    """A single model's response to a query."""
    model: str = Field(description="Model identifier (e.g., 'openai/gpt-4')")
    response: str = Field(description="The model's response content")
    role: str = Field(default="answer", description="Role in the arena (answer, critique, defense, etc.)")
    prompt_preview: Optional[str] = Field(default=None, description="Preview of the prompt sent")
    prompt_full: Optional[str] = Field(default=None, description="Full prompt sent to model")
    est_tokens: int = Field(default=0, description="Estimated tokens in the prompt")
    context_tokens: int = Field(default=0, description="Context tokens used")
    reasoning_details: Optional[str] = Field(default=None, description="Extended reasoning (for o1-style models)")
    latency_ms: Optional[float] = Field(default=None, description="Response latency in milliseconds")

    class Config:
        extra = "allow"  # Allow additional fields for backwards compatibility


class RankingResult(BaseModel):
    """A single model's ranking of peer responses."""
    model: str = Field(description="Model that performed the ranking")
    ranking: str = Field(description="Raw ranking text from the model")
    parsed_ranking: List[str] = Field(default_factory=list, description="Parsed ordered list of response labels")

    class Config:
        extra = "allow"


class AggregateRanking(BaseModel):
    """Aggregate ranking statistics for a model."""
    model: str = Field(description="Model identifier")
    avg_rank: float = Field(description="Average rank position (lower is better)")
    votes: int = Field(description="Number of rankings this model received")
    rank_positions: List[int] = Field(default_factory=list, description="Individual rank positions received")


class Stage1Result(BaseModel):
    """Result of Stage 1: Initial model responses."""
    responses: List[ModelResponse] = Field(default_factory=list, description="List of model responses")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_dicts(cls, results: List[Dict[str, Any]]) -> "Stage1Result":
        """Create from list of response dicts (legacy format)."""
        responses = [ModelResponse(**r) for r in results]
        return cls(responses=responses)

    def to_dicts(self) -> List[Dict[str, Any]]:
        """Convert to list of dicts (legacy format)."""
        return [r.model_dump(exclude_none=True) for r in self.responses]


class Stage2Result(BaseModel):
    """Result of Stage 2: Peer rankings."""
    rankings: List[RankingResult] = Field(default_factory=list, description="Individual rankings from each model")
    label_to_model: Dict[str, str] = Field(default_factory=dict, description="Mapping of anonymous labels to models")
    aggregate_rankings: List[AggregateRanking] = Field(default_factory=list, description="Aggregate ranking statistics")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_dicts(
        cls,
        rankings: List[Dict[str, Any]],
        label_to_model: Dict[str, str],
        aggregate: Optional[List[Dict[str, Any]]] = None,
    ) -> "Stage2Result":
        """Create from legacy format."""
        ranking_results = [RankingResult(**r) for r in rankings]
        agg_results = [AggregateRanking(**a) for a in (aggregate or [])]
        return cls(
            rankings=ranking_results,
            label_to_model=label_to_model,
            aggregate_rankings=agg_results,
        )

    def to_dicts(self) -> List[Dict[str, Any]]:
        """Convert rankings to list of dicts (legacy format)."""
        return [r.model_dump(exclude_none=True) for r in self.rankings]


class Stage3Result(BaseModel):
    """Result of Stage 3: Chairman synthesis."""
    model: str = Field(description="Chairman model identifier")
    response: str = Field(description="Synthesized final response")
    role: str = Field(default="chair_final", description="Role identifier")
    prompt_preview: Optional[str] = Field(default=None, description="Preview of synthesis prompt")
    est_tokens: int = Field(default=0, description="Estimated tokens in prompt")
    context_tokens: int = Field(default=0, description="Context tokens used")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_dict(cls, result: Dict[str, Any]) -> "Stage3Result":
        """Create from dict (legacy format)."""
        return cls(**result)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict (legacy format)."""
        return self.model_dump(exclude_none=True, exclude={"timestamp"})


class ModeStep(BaseModel):
    """A single step in a multi-step arena mode."""
    model: str
    role: str
    response: str
    prompt_preview: Optional[str] = None
    est_tokens: int = 0
    context_tokens: int = 0
    iteration: Optional[int] = None

    class Config:
        extra = "allow"


class ArenaMetadata(BaseModel):
    """Metadata for an arena execution."""
    mode: ArenaMode = Field(default=ArenaMode.COUNCIL)
    chairman_model: str = Field(default="")
    arena_models: List[str] = Field(default_factory=list)
    label_to_model: Optional[Dict[str, str]] = None
    aggregate_rankings: Optional[List[Dict[str, Any]]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    directives: Optional[Dict[str, Any]] = None
    warnings: List[str] = Field(default_factory=list)
    total_execution_time_ms: Optional[float] = None

    class Config:
        extra = "allow"


class ArenaExecution(BaseModel):
    """Complete execution record for an arena query."""
    conversation_id: str = Field(description="ID of the conversation")
    mode: ArenaMode = Field(default=ArenaMode.COUNCIL, description="Arena mode used")
    user_query: str = Field(description="Original user query (cleaned)")
    user_query_raw: Optional[str] = Field(default=None, description="Raw user query with directives")

    # Context information
    context_block: str = Field(default="", description="Context provided to models")
    context_sources: List[Dict[str, Any]] = Field(default_factory=list, description="Sources of context")
    rag_used: bool = Field(default=False, description="Whether RAG retrieval was used")

    # Stage results
    stage1: Optional[Stage1Result] = None
    stage2: Optional[Stage2Result] = None  # Some modes skip Stage 2
    stage3: Optional[Stage3Result] = None

    # Execution metadata
    metadata: ArenaMetadata = Field(default_factory=ArenaMetadata)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    total_execution_time_ms: float = Field(default=0.0)

    def to_response_dict(self) -> Dict[str, Any]:
        """Convert to API response format (legacy compatibility)."""
        return {
            "stage1": self.stage1.to_dicts() if self.stage1 else [],
            "stage2": self.stage2.to_dicts() if self.stage2 else [],
            "stage3": self.stage3.to_dict() if self.stage3 else {},
            "metadata": self.metadata.model_dump(exclude_none=True),
            "context_sources": self.context_sources,
            "directives": self.metadata.directives,
            "warnings": self.metadata.warnings,
        }


# ----- Message Models -----

class UserMessage(BaseModel):
    """A user message in a conversation."""
    role: str = Field(default="user")
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AssistantMessage(BaseModel):
    """An assistant message containing arena execution results."""
    role: str = Field(default="assistant")
    stage1: List[Dict[str, Any]] = Field(default_factory=list)
    stage2: List[Dict[str, Any]] = Field(default_factory=list)
    stage3: Dict[str, Any] = Field(default_factory=dict)
    context_sources: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ConversationMessage(BaseModel):
    """Union type for conversation messages."""
    role: str
    content: Optional[str] = None  # For user messages
    stage1: Optional[List[Dict[str, Any]]] = None  # For assistant messages
    stage2: Optional[List[Dict[str, Any]]] = None
    stage3: Optional[Dict[str, Any]] = None
    context_sources: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


# ----- Conversation Models -----

class ConversationCreate(BaseModel):
    """Request to create a new conversation."""
    mode: ArenaMode = Field(default=ArenaMode.COUNCIL)
    title: Optional[str] = None


class ConversationSummary(BaseModel):
    """Summary information for conversation list view."""
    id: str
    created_at: str
    title: str
    message_count: int
    mode: ArenaMode = Field(default=ArenaMode.COUNCIL)


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[ConversationMessage] = Field(default_factory=list)
    mode: ArenaMode = Field(default=ArenaMode.COUNCIL)

    class Config:
        extra = "allow"


# ----- Agent turn state (PIV-001 Phase 1) -----


class TurnStatus(str, Enum):
    """Lifecycle for agent-driven turns."""

    PENDING = "pending"
    STAGE1_COMPLETE = "stage1_complete"
    STAGE2_COMPLETE = "stage2_complete"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAIT_USER = "await_user"


class TurnCheckpoint(BaseModel):
    """Serializable council checkpoint between advance calls."""

    augmented_content: str
    per_model_prompts: Dict[str, str] = Field(default_factory=dict)
    context_token_map: Dict[str, int] = Field(default_factory=dict)
    context_block: str = ""
    context_sources: List[Dict[str, Any]] = Field(default_factory=list)
    directives: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    arena_models: List[str] = Field(default_factory=list)
    chairman_model: str = ""
    context_from_last_chair: bool = False
    iterations_override: Optional[int] = None


class TurnRecord(BaseModel):
    """Agent turn with step checkpoints (council first)."""

    turn_id: str
    conversation_id: str
    status: TurnStatus = TurnStatus.PENDING
    step_index: int = 0
    step_total: int = 3
    mode: str = "council"
    agent_id: Optional[str] = None
    user_query: str = ""
    user_query_raw: str = ""
    checkpoint: TurnCheckpoint
    stage1: List[Dict[str, Any]] = Field(default_factory=list)
    stage2: List[Dict[str, Any]] = Field(default_factory=list)
    stage3: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    await_reason: Optional[str] = None
    await_prompt: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_api_dict(self) -> Dict[str, Any]:
        """API-facing turn snapshot."""
        payload = self.model_dump(mode="json")
        payload["next_step"] = self.next_step_name()
        payload["execution"] = None
        if self.status == TurnStatus.COMPLETE:
            payload["execution"] = {
                "stage1": self.stage1,
                "stage2": self.stage2,
                "stage3": self.stage3,
                "metadata": self.metadata,
                "context_sources": self.checkpoint.context_sources,
            }
        return payload

    def next_step_name(self) -> Optional[str]:
        if self.status in {TurnStatus.COMPLETE, TurnStatus.CANCELLED, TurnStatus.FAILED}:
            return None
        if self.status == TurnStatus.AWAIT_USER:
            return "resume"
        mapping = {0: "stage1", 1: "stage2", 2: "stage3"}
        return mapping.get(self.step_index)
