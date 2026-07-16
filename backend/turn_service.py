"""Agent turn lifecycle: create, advance council steps, cancel."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from .arena import (
    calculate_aggregate_rankings,
    stage1_collect_responses,
    stage2_collect_rankings,
    stage3_synthesize_final,
)
from .config import ARENA_MODELS, CHAIRMAN_MODEL
from .cost_tracking import sum_usage_fields, summarize_turn_cost
from .openrouter import query_model
from .dependencies import get_context_engine
from .execution_quality import assess_from_response_dict
from .execution_trace import build_execution_trace
from .models import TurnCheckpoint, TurnRecord, TurnStatus
from .run_turn import _assistant_metadata
from .storage_service import StorageService
from .turn_store import TurnCreationInProgress, TurnStore

logger = logging.getLogger(__name__)

COUNCIL_STEP_TOTAL = 3


class TurnService:
    """Orchestrates agent turns with council step checkpoints."""

    def __init__(
        self,
        storage: StorageService,
        turn_store: Optional[TurnStore] = None,
    ):
        self.storage = storage
        self.turn_store = turn_store or TurnStore()

    async def create_turn(
        self,
        conversation_id: str,
        content: str,
        *,
        settings: Dict[str, Any],
        manual_context: Optional[List[Dict[str, Any]]] = None,
        agent_id: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> TurnRecord:
        try:
            with self.turn_store.creation_guard(conversation_id):
                return await self._create_turn_locked(
                    conversation_id,
                    content,
                    settings=settings,
                    manual_context=manual_context,
                    agent_id=agent_id,
                    origin=origin,
                )
        except TurnCreationInProgress as exc:
            raise ValueError(str(exc)) from exc

    async def _create_turn_locked(
        self,
        conversation_id: str,
        content: str,
        *,
        settings: Dict[str, Any],
        manual_context: Optional[List[Dict[str, Any]]] = None,
        agent_id: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> TurnRecord:
        conversation = self.storage.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError("Conversation not found")

        active = self.turn_store.active_turn(conversation_id)
        if active is not None:
            raise ValueError(
                f"Conversation has active turn {active.turn_id} ({active.status.value})"
            )

        mode = conversation.get("mode", "council")
        if mode not in {"council", "baseline"}:
            raise ValueError(
                f"Step API supports council mode only (conversation mode={mode!r})"
            )

        arena_models = settings.get("arena_models", ARENA_MODELS)
        chairman_model = settings.get("chairman_model", CHAIRMAN_MODEL)

        ctx = await get_context_engine().prepare_context(
            conversation_id=conversation_id,
            user_input=content,
            mode=mode,
            manual_context=manual_context,
            conversation=conversation,
            arena_models=arena_models,
            chairman_model=chairman_model,
        )

        if ctx.directives.reset:
            self.storage.reset_conversation(conversation_id)
            raise ValueError("Reset directive handled; conversation cleared")

        self.storage.add_user_message(
            conversation_id,
            ctx.clean_query,
            caller=agent_id,
            origin=origin or ("mcp" if agent_id else "api"),
        )

        checkpoint = TurnCheckpoint(
            augmented_content=ctx.base_prompt,
            per_model_prompts=dict(ctx.per_model_prompts or {}),
            context_token_map=dict(ctx.context_token_map or {}),
            context_block=ctx.context_block,
            context_sources=list(ctx.context_sources or []),
            directives=ctx.directives.dict(),
            warnings=list(ctx.warnings or []),
            arena_models=list(arena_models),
            chairman_model=chairman_model,
            context_from_last_chair=ctx.context_from_last_chair,
            iterations_override=ctx.directives.iterations_override,
        )

        turn = TurnRecord(
            turn_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            status=TurnStatus.PENDING,
            step_index=0,
            step_total=COUNCIL_STEP_TOTAL,
            mode="council",
            agent_id=agent_id,
            user_query=ctx.clean_query,
            user_query_raw=content,
            checkpoint=checkpoint,
            metadata={"arena_squad": settings.get("arena_squad")},
        )
        return self._save_turn(turn)

    async def advance_turn(
        self,
        conversation_id: str,
        turn_id: str,
    ) -> TurnRecord:
        turn = self.turn_store.get(conversation_id, turn_id)
        if turn is None:
            raise ValueError("Turn not found")
        if turn.status in {TurnStatus.CANCELLED, TurnStatus.FAILED}:
            raise ValueError(f"Turn is {turn.status.value}")
        if turn.status == TurnStatus.COMPLETE:
            raise ValueError("Turn already complete")
        if turn.status == TurnStatus.AWAIT_USER:
            raise ValueError("Turn awaits user input; use resume (Phase 2)")

        ckpt = turn.checkpoint
        try:
            if turn.step_index == 0:
                turn = await self._run_stage1(turn)
            elif turn.step_index == 1:
                turn = await self._run_stage2(turn)
            elif turn.step_index == 2:
                turn = await self._run_stage3(turn)
            else:
                raise ValueError("Invalid step index")
        except Exception as exc:
            logger.exception("Turn advance failed (convo=%s turn=%s)", conversation_id, turn_id)
            turn.status = TurnStatus.FAILED
            turn.error = str(exc)
            return self._save_turn(turn)

        return self._save_turn(turn)

    async def _run_stage1(self, turn: TurnRecord) -> TurnRecord:
        ckpt = turn.checkpoint
        model_failures = list(turn.metadata.get("model_failures") or [])
        stage1_results = await stage1_collect_responses(
            ckpt.augmented_content,
            ckpt.per_model_prompts or None,
            ckpt.arena_models,
            context_tokens_map=ckpt.context_token_map,
            progress_cb=None,
            emit_steps=False,
            model_failures=model_failures,
        )
        turn.metadata["model_failures"] = model_failures
        if not stage1_results:
            turn.status = TurnStatus.FAILED
            turn.error = "All models failed in stage 1"
            return turn

        turn.stage1 = stage1_results
        turn.step_index = 1
        turn.status = TurnStatus.STAGE1_COMPLETE
        turn.metadata["stage1_count"] = len(stage1_results)
        return turn

    async def _run_stage2(self, turn: TurnRecord) -> TurnRecord:
        ckpt = turn.checkpoint
        model_failures = list(turn.metadata.get("model_failures") or [])
        stage2_results, label_to_model, mid_turn_jobs = await stage2_collect_rankings(
            turn.user_query,
            turn.stage1,
            ckpt.arena_models,
            query_model_fn=query_model,
            chairman_model=ckpt.chairman_model,
            budget_override=(ckpt.directives or {}).get("budget_override"),
            model_failures=model_failures,
        )
        turn.metadata["model_failures"] = model_failures
        aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

        turn.stage2 = stage2_results
        turn.step_index = 2
        turn.status = TurnStatus.STAGE2_COMPLETE
        turn.metadata["label_to_model"] = label_to_model
        turn.metadata["aggregate_rankings"] = aggregate_rankings
        if mid_turn_jobs:
            existing = list(turn.metadata.get("summarize_jobs") or [])
            existing.extend(j.to_dict() for j in mid_turn_jobs)
            turn.metadata["summarize_jobs"] = existing
        return turn

    async def _run_stage3(self, turn: TurnRecord) -> TurnRecord:
        ckpt = turn.checkpoint
        model_failures = list(turn.metadata.get("model_failures") or [])
        stage3_result = await stage3_synthesize_final(
            turn.user_query,
            turn.stage1,
            turn.stage2,
            chairman_model=ckpt.chairman_model,
            model_failures=model_failures,
        )
        turn.metadata["model_failures"] = model_failures

        rankings_step = {
            "model": "arena",
            "response": "\n\n".join(
                f"{r['model']}:\n{(r.get('ranking') or '')[:1200]}"
                for r in turn.stage2
            ),
            "role": "rankings",
            "prompt_preview": "Peer rankings aggregation",
            "context_tokens": 0,
            "est_tokens": 0,
            **sum_usage_fields(turn.stage2),
        }
        chair_step = dict(stage3_result, role="chair_final")
        steps = list(turn.stage1) + [rankings_step, chair_step]

        turn.stage3 = stage3_result
        turn.step_index = 3
        turn.status = TurnStatus.COMPLETE
        turn.metadata.update(
            {
                "mode": "council",
                "steps": steps,
                "cost": summarize_turn_cost(steps),
                "chairman_model": ckpt.chairman_model,
                "arena_models": ckpt.arena_models,
                "directives": ckpt.directives,
                "warnings": ckpt.warnings,
                "context_from_last_chair": ckpt.context_from_last_chair,
            }
        )
        turn.metadata["execution_trace"] = build_execution_trace(
            mode="council",
            metadata_steps=steps,
            stage1=turn.stage1,
            stage2=turn.stage2,
            stage3=turn.stage3,
            failures=turn.metadata.get("model_failures") or [],
            arena_models=ckpt.arena_models,
            chairman_model=ckpt.chairman_model,
            has_context=bool(ckpt.context_block),
            context_source_count=len(ckpt.context_sources),
        )
        turn.metadata["execution_quality"] = assess_from_response_dict(
            {
                "stage1": turn.stage1,
                "stage2": turn.stage2,
                "stage3": turn.stage3,
                "metadata": turn.metadata,
            }
        )

        from .directives import ParsedDirectives

        directives = ParsedDirectives(**ckpt.directives)
        ctx_stub = type(
            "Ctx",
            (),
            {
                "directives": directives,
                "warnings": ckpt.warnings,
                "context_from_last_chair": ckpt.context_from_last_chair,
            },
        )()

        self.storage.add_assistant_message(
            turn.conversation_id,
            turn.stage1,
            turn.stage2,
            turn.stage3,
            ckpt.context_sources,
            metadata=_assistant_metadata(
                turn.metadata,
                ctx_stub,
                mode="council",
                arena_models=ckpt.arena_models,
                chairman_model=ckpt.chairman_model,
            ),
        )
        return turn

    def cancel_turn(self, conversation_id: str, turn_id: str) -> TurnRecord:
        turn = self.turn_store.get(conversation_id, turn_id)
        if turn is None:
            raise ValueError("Turn not found")
        if turn.status == TurnStatus.COMPLETE:
            raise ValueError("Cannot cancel a completed turn")
        turn.status = TurnStatus.CANCELLED
        return self._save_turn(turn)

    def _save_turn(self, turn: TurnRecord) -> TurnRecord:
        saved = self.turn_store.save(turn)
        self.storage.refresh_catalog(turn.conversation_id)
        return saved

    def get_turn(self, conversation_id: str, turn_id: str) -> Optional[TurnRecord]:
        return self.turn_store.get(conversation_id, turn_id)
