from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from .context import ContextEnvelopeBuilder
from .models import AgentConfig, ContextEnvelope, LaneRecord, LaneStatus, normalize_lane_key, utcnow_iso
from .runtime import AgentRuntime
from .rotation import RotationPolicy
from .state import ControlStore


class AgentLifecycleManager:
    def __init__(
        self,
        store: ControlStore,
        runtime: AgentRuntime,
        context_builder: ContextEnvelopeBuilder | None = None,
        handover_root: Path | None = None,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.context_builder = context_builder or ContextEnvelopeBuilder(store)
        self.handover_root = handover_root or (store.state_root.parent / "handovers")

    def _lane_config(self, lane: LaneRecord) -> AgentConfig:
        return AgentConfig.from_dict(
            {
                "model": lane.model or "composer-2.5",
                "cwd": lane.workspace,
                **(lane.config or {}),
            }
        )

    async def create(
        self,
        lane_key: str,
        *,
        objective: str,
        spec_id: str | None = None,
        owner: str | None = None,
        model: str | None = None,
    ) -> tuple[LaneRecord, str, ContextEnvelope]:
        lane_key = normalize_lane_key(lane_key)
        lane = self.store.ensure_lane(lane_key, owner=owner, model=model)
        envelope = self.context_builder.build(lane, spec_id=spec_id)
        envelope.objective = objective
        errors = self.context_builder.validate(envelope)
        if errors:
            raise ValueError("; ".join(errors))
        config = self._lane_config(lane)
        agent_id = await self.runtime.create_agent(config, envelope)
        lane.current_agent_id = agent_id
        lane.status = LaneStatus.ACTIVE
        lane.last_activity = utcnow_iso()
        lane.updated_at = utcnow_iso()
        self.store.upsert_lane(lane)
        self.store.append_event(
            "agent.created",
            entity_type="lane",
            entity_id=lane_key,
            payload={"agent_id": agent_id},
        )
        return lane, agent_id, envelope

    async def resume(
        self,
        lane_key: str,
        *,
        objective: str | None = None,
        spec_id: str | None = None,
    ) -> tuple[LaneRecord, str, ContextEnvelope]:
        lane_key = normalize_lane_key(lane_key)
        lane = self.store.ensure_lane(lane_key)
        if not lane.current_agent_id:
            return await self.create(lane_key, objective=objective or lane.lane_key, spec_id=spec_id)
        envelope = self.context_builder.build(lane, spec_id=spec_id)
        if objective:
            envelope.objective = objective
        config = self._lane_config(lane)
        agent_id = await self.runtime.resume_agent(lane.current_agent_id, config, envelope)
        lane.current_agent_id = agent_id
        lane.status = LaneStatus.ACTIVE
        lane.last_activity = utcnow_iso()
        lane.updated_at = utcnow_iso()
        self.store.upsert_lane(lane)
        self.store.append_event(
            "agent.resumed",
            entity_type="lane",
            entity_id=lane_key,
            payload={"agent_id": agent_id},
        )
        return lane, agent_id, envelope

    async def rotate(
        self,
        lane_key: str,
        *,
        objective: str,
        spec_id: str | None = None,
        reason: str = "context rotation",
    ) -> tuple[LaneRecord, str, ContextEnvelope]:
        lane_key = normalize_lane_key(lane_key)
        lane = self.store.ensure_lane(lane_key)
        prior = lane.current_agent_id
        if prior:
            await self.runtime.dispose_agent(prior)
            lane.prior_agent_ids = list(lane.prior_agent_ids) + [prior]
        handover_path = self._write_handover(lane_key, prior, objective)
        lane.handover_path = str(handover_path)
        lane.status = LaneStatus.ROTATING
        lane.context_health_score = 1.0
        RotationPolicy.reset(lane)
        lane.updated_at = utcnow_iso()
        self.store.upsert_lane(lane)
        lane, agent_id, envelope = await self.create(
            lane_key,
            objective=objective,
            spec_id=spec_id,
            owner=lane.owner,
            model=lane.model,
        )
        self.store.append_event(
            "agent.rotated",
            entity_type="lane",
            entity_id=lane_key,
            payload={"old_agent_id": prior, "new_agent_id": agent_id, "reason": reason},
        )
        return lane, agent_id, envelope

    async def dispose(self, lane_key: str) -> LaneRecord:
        lane_key = normalize_lane_key(lane_key)
        lane = self.store.ensure_lane(lane_key)
        if lane.current_agent_id:
            await self.runtime.dispose_agent(lane.current_agent_id)
            lane.prior_agent_ids = list(lane.prior_agent_ids) + [lane.current_agent_id]
            lane.current_agent_id = None
        lane.status = LaneStatus.RETIRED
        lane.updated_at = utcnow_iso()
        self.store.upsert_lane(lane)
        self.store.append_event("agent.disposed", entity_type="lane", entity_id=lane_key)
        return lane

    def _write_handover(self, lane_key: str, prior_agent_id: str | None, objective: str) -> Path:
        self.handover_root.mkdir(parents=True, exist_ok=True)
        from .state import workspace_hash

        path = self.handover_root / f"{workspace_hash(self.store.workspace)}_{lane_key}.md"
        content = (
            f"# Handover {lane_key}\n\n"
            f"- workspace: {self.store.workspace}\n"
            f"- prior_agent_id: {prior_agent_id}\n"
            f"- objective: {objective}\n"
            f"- generated_at: {utcnow_iso()}\n"
        )
        path.write_text(content, encoding="utf-8")
        return path
