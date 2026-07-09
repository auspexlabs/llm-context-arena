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
from .cost_tracking import summarize_turn_cost
from .dependencies import get_context_engine
from .models import TurnCheckpoint, TurnRecord, TurnStatus
from .run_turn import _assistant_metadata
from .storage_service import StorageService
from .turn_store import TurnStore

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
            from .storage import reset_conversation

            reset_conversation(conversation_id)
            raise ValueError("Reset directive handled; conversation cleared")

        self.storage.add_user_message(conversation_id, ctx.clean_query)

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
        )
        return self.turn_store.save(turn)

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
            return self.turn_store.save(turn)

        return self.turn_store.save(turn)

    async def _run_stage1(self, turn: TurnRecord) -> TurnRecord:
        ckpt = turn.checkpoint
        stage1_results = await stage1_collect_responses(
            ckpt.augmented_content,
            ckpt.per_model_prompts or None,
            ckpt.arena_models,
            context_tokens_map=ckpt.context_token_map,
            progress_cb=None,
            emit_steps=False,
        )
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
        stage2_results, label_to_model = await stage2_collect_rankings(
            turn.user_query,
            turn.stage1,
            ckpt.arena_models,
        )
        aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

        turn.stage2 = stage2_results
        turn.step_index = 2
        turn.status = TurnStatus.STAGE2_COMPLETE
        turn.metadata["label_to_model"] = label_to_model
        turn.metadata["aggregate_rankings"] = aggregate_rankings
        return turn

    async def _run_stage3(self, turn: TurnRecord) -> TurnRecord:
        ckpt = turn.checkpoint
        stage3_result = await stage3_synthesize_final(
            turn.user_query,
            turn.stage1,
            turn.stage2,
            chairman_model=ckpt.chairman_model,
        )

        rankings_step = {
            "model": "arena",
            "response": "\n\n".join(
                f"{r['model']}:\n{(r.get('ranking') or '')[:1200]}"
                for r in turn.stage2
            ),
            "role": "rankings",
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
        return self.turn_store.save(turn)

    def get_turn(self, conversation_id: str, turn_id: str) -> Optional[TurnRecord]:
        return self.turn_store.get(conversation_id, turn_id)