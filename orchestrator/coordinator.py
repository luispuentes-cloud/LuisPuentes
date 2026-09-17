from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .agents import AgentLifecycleManager
from .context import ContextEnvelopeBuilder
from .events import EventLedger
from .locks import ArtifactLockManager
from .models import (
    ApprovalRequest,
    ApprovalStatus,
    ContextEnvelope,
    FailureKind,
    LaneRecord,
    LaneStatus,
    MessageEnvelope,
    MessageStatus,
    Permissions,
    RunOutcome,
    TaskEnvelope,
    TaskStatus,
    normalize_lane_key,
    utcnow_iso,
)
from .policy import PolicyRegistry
from .runtime import AgentBusyError, AgentRuntime, StartupError
from .rotation import RotationPolicy
from .state import ControlStore, compute_expires_at


class Coordinator:
    def __init__(
        self,
        workspace: str,
        runtime: AgentRuntime,
        *,
        state_root: Path | None = None,
        policy_registry: PolicyRegistry | None = None,
        mode: str = "supervised",
        rotation_policy: RotationPolicy | None = None,
    ) -> None:
        if mode not in {"shadow", "read-only", "supervised"}:
            raise ValueError(f"Unsupported operating mode: {mode}")
        self.workspace = str(Path(workspace).resolve())
        self.store = ControlStore(self.workspace, state_root=state_root)
        self.runtime = runtime
        self.mode = mode
        self.policy = policy_registry or PolicyRegistry()
        self.rotation_policy = rotation_policy or RotationPolicy()
        self.context_builder = ContextEnvelopeBuilder(self.store, self.policy)
        self.agents = AgentLifecycleManager(self.store, runtime, self.context_builder)
        self.locks = ArtifactLockManager(self.store)
        self.events = EventLedger(self.store)
        self._lane_locks: dict[str, asyncio.Lock] = {}
        self._paused_lanes: set[str] = set()
        self.execution_owner = f"coordinator:{uuid4()}"
        self.last_cycle_stats = {"processed_tasks": 0, "proposed_routes": 0}
        self.last_coordination_held = 0
        self._recover_interrupted_runs()

    def set_service_owner(self, token: str) -> None:
        self.execution_owner = token

    def _recover_interrupted_runs(self) -> list[str]:
        live_token = self.store.live_service_owner_token()
        recovered = self.store.recover_interrupted_tasks(
            live_service_token=live_token,
        )
        if recovered:
            self.events.metric(
                "restart_recovery",
                len(recovered),
                {"task_ids": recovered},
            )
            self.store.export_lane_registry()
        return recovered

    def _lane_lock(self, lane_key: str) -> asyncio.Lock:
        lane_key = normalize_lane_key(lane_key)
        if lane_key not in self._lane_locks:
            self._lane_locks[lane_key] = asyncio.Lock()
        return self._lane_locks[lane_key]

    def submit_task(
        self,
        *,
        lane_key: str,
        objective: str,
        sender: str = "user",
        target: str = "lane",
        permissions: Permissions | None = None,
        idempotency_key: str | None = None,
        reply_to: str | None = None,
        artifacts: list[str] | None = None,
        evidence: list[str] | None = None,
        spec_id: str | None = None,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskEnvelope:
        requested_permissions = permissions or Permissions()
        if self.mode == "read-only" and (
            requested_permissions.write_files
            or requested_permissions.external_write
            or requested_permissions.cross_lane_merge
            or requested_permissions.destructive
        ):
            raise PermissionError("Read-only mode denies write-capable permissions")
        if idempotency_key:
            existing = self.store.get_task_by_idempotency(idempotency_key)
            if existing:
                return existing
        now = utcnow_iso()
        lane_key = normalize_lane_key(lane_key)
        task = TaskEnvelope(
            task_id=str(uuid4()),
            workspace=self.workspace,
            lane_key=lane_key,
            objective=objective,
            sender=sender,
            target=target,
            status=TaskStatus.QUEUED,
            permissions=requested_permissions,
            idempotency_key=idempotency_key,
            reply_to=reply_to,
            evidence=evidence or [],
            artifacts=artifacts or [],
            spec_id=spec_id,
            ttl_seconds=ttl_seconds,
            created_at=now,
            updated_at=now,
            expires_at=compute_expires_at(ttl_seconds, now),
            metadata=metadata or {},
        )
        self.store.ensure_lane(lane_key)
        self.store.save_task(task)
        self.store.export_lane_registry()
        self.events.record("task.submitted", entity_type="task", entity_id=task.task_id)
        if task.metadata.get("stale_source"):
            self.events.metric("stale_source_incident", 1, {"lane_key": lane_key})
        return task

    def delegate_task(
        self,
        parent_task_id: str,
        *,
        task_type: str,
        objective: str,
        lane_key: str | None = None,
    ) -> TaskEnvelope:
        parent = self.store.get_task(parent_task_id)
        if not parent:
            raise KeyError(parent_task_id)
        if task_type not in {"extraction", "review"}:
            raise PermissionError("Delegation is limited to extraction and review")
        depth = int(parent.metadata.get("delegation_depth", 0))
        if depth >= 1:
            raise PermissionError("Recursive delegation is prohibited")
        return self.submit_task(
            lane_key=normalize_lane_key(lane_key or parent.lane_key),
            objective=objective,
            sender="coordinator",
            target="child",
            permissions=Permissions(read=True),
            idempotency_key=f"child:{parent.task_id}:{task_type}",
            evidence=list(parent.evidence),
            spec_id=parent.spec_id,
            metadata={
                "parent_task_id": parent.task_id,
                "delegation_depth": depth + 1,
                "task_type": task_type,
                "coordinator_controlled": True,
            },
        )

    def inbox_send(
        self,
        *,
        target: str,
        objective: str,
        sender: str = "user",
        permissions: Permissions | None = None,
        reply_to: str | None = None,
        evidence: list[str] | None = None,
        ttl_seconds: int | None = 86400,
        metadata: dict[str, Any] | None = None,
        executable: bool = False,
    ) -> MessageEnvelope:
        now = utcnow_iso()
        message_metadata = dict(metadata or {})
        message_metadata["executable"] = bool(executable)
        message = MessageEnvelope(
            message_id=str(uuid4()),
            workspace=self.workspace,
            sender=sender,
            target=target,
            objective=objective,
            status=MessageStatus.PENDING,
            permissions=permissions or Permissions(),
            reply_to=reply_to,
            evidence=evidence or [],
            ttl_seconds=ttl_seconds,
            created_at=now,
            updated_at=now,
            expires_at=compute_expires_at(ttl_seconds, now),
            metadata=message_metadata,
        )
        self.store.save_message(message)
        self.events.record("message.sent", entity_type="message", entity_id=message.message_id)
        return message

    def promote_message(self, message_id: str, *, actor: str = "user") -> MessageEnvelope:
        """Allow a held message to become agent work on the next cycle.

        This is the deliberate step between an agent proposing work and that
        work running. Without it, an agent could schedule the next agent.
        """
        message = self.store.get_message(message_id)
        if message is None:
            raise KeyError(message_id)
        if message.status != MessageStatus.PENDING:
            raise PermissionError(
                f"Only pending messages can be promoted; {message_id} is {message.status.value}"
            )
        now = utcnow_iso()
        message.metadata["executable"] = True
        message.metadata["promoted_by"] = actor
        message.metadata["promoted_at"] = now
        message.updated_at = now
        self.store.save_message(message)
        self.events.record(
            "message.promoted",
            entity_type="message",
            entity_id=message.message_id,
            payload={"actor": actor},
        )
        return message

    def acknowledge_message(
        self,
        message_id: str,
        *,
        actor: str = "user",
        note: str | None = None,
    ) -> MessageEnvelope:
        """Close out coordination mail that has already been actioned.

        Without this, a message stays pending until its TTL lapses and reads as
        outstanding work to whoever picks the lane up next.
        """
        message = self.store.get_message(message_id)
        if message is None:
            raise KeyError(message_id)
        message.status = MessageStatus.DELIVERED
        message.updated_at = utcnow_iso()
        message.metadata["acknowledged_by"] = actor
        message.metadata["acknowledged_at"] = message.updated_at
        if note:
            message.metadata["acknowledged_note"] = note[:2000]
        self.store.save_message(message)
        self.events.record(
            "message.acknowledged",
            entity_type="message",
            entity_id=message.message_id,
            payload={"actor": actor},
        )
        return message

    def _dead_letter_message(self, message: MessageEnvelope, reason: str) -> None:
        message.status = MessageStatus.DEAD_LETTER
        message.updated_at = utcnow_iso()
        message.metadata["dead_letter_reason"] = reason
        self.store.save_message(message)
        self.events.record(
            "message.dead_lettered",
            entity_type="message",
            entity_id=message.message_id,
            payload={"reason": reason},
        )

    def route_pending_messages(self, *, max_messages: int = 100) -> list[TaskEnvelope]:
        routed: list[TaskEnvelope] = []
        held = 0
        pending = self.store.list_messages(status=MessageStatus.PENDING)
        for message in pending[:max_messages]:
            try:
                target = normalize_lane_key(message.target)
            except ValueError:
                self._dead_letter_message(message, "invalid_target_lane")
                continue
            lane = self.store.get_lane(target)
            if lane is None or lane.status == LaneStatus.RETIRED:
                self._dead_letter_message(message, "unknown_target_lane")
                continue
            # Target validation above runs for every message so a typo still
            # dead-letters, but only explicitly executable mail becomes work.
            if not message.executable:
                held += 1
                continue
            try:
                task = self.submit_task(
                    lane_key=target,
                    objective=message.objective,
                    sender=message.sender,
                    target="message",
                    permissions=message.permissions,
                    idempotency_key=f"message:{message.message_id}",
                    reply_to=message.reply_to,
                    evidence=list(message.evidence),
                    spec_id=message.metadata.get("spec_id"),
                    ttl_seconds=message.ttl_seconds,
                    metadata={
                        "source_message_id": message.message_id,
                        "message_routed_at": utcnow_iso(),
                    },
                )
            except PermissionError as err:
                self._dead_letter_message(message, str(err))
                continue
            message.status = MessageStatus.ROUTED
            message.updated_at = utcnow_iso()
            message.metadata["routed_task_id"] = task.task_id
            self.store.save_message(message)
            self.events.record(
                "message.routed",
                entity_type="message",
                entity_id=message.message_id,
                payload={"task_id": task.task_id, "lane_key": target},
            )
            routed.append(task)
            self._sync_source_message(task)
        self.last_coordination_held = held
        return routed

    def _sync_source_message(self, task: TaskEnvelope) -> None:
        message_id = task.metadata.get("source_message_id")
        if not isinstance(message_id, str):
            return
        message = self.store.get_message(message_id)
        if message is None:
            return
        if task.status == TaskStatus.COMPLETED:
            message.status = MessageStatus.DELIVERED
            message.updated_at = utcnow_iso()
            message.metadata["completed_task_id"] = task.task_id
            self.store.save_message(message)
            self.events.record(
                "message.delivered",
                entity_type="message",
                entity_id=message.message_id,
                payload={"task_id": task.task_id},
            )
        elif task.status in {
            TaskStatus.FAILED,
            TaskStatus.DEAD_LETTER,
            TaskStatus.EXPIRED,
        }:
            self._dead_letter_message(
                message,
                task.error_message or f"source_task_{task.status.value}",
            )

    def _record_rejected_proposal(
        self,
        task: TaskEnvelope,
        proposal: Any,
        reason: str,
    ) -> None:
        item = proposal if isinstance(proposal, dict) else {}
        objective = str(item.get("objective", "Rejected agent message"))[:4000]
        target = str(item.get("target", "(invalid)"))[:200]
        now = utcnow_iso()
        message = MessageEnvelope(
            message_id=str(uuid4()),
            workspace=self.workspace,
            sender=task.lane_key,
            target=target,
            objective=objective,
            status=MessageStatus.DEAD_LETTER,
            permissions=Permissions(read=True),
            reply_to=task.task_id,
            evidence=[],
            created_at=now,
            updated_at=now,
            metadata={
                "source_task_id": task.task_id,
                "dead_letter_reason": reason,
                "agent_proposed": True,
            },
        )
        self.store.save_message(message)
        self.events.record(
            "message.proposal_rejected",
            entity_type="message",
            entity_id=message.message_id,
            payload={"task_id": task.task_id, "reason": reason},
        )

    def _enqueue_agent_proposal(
        self,
        task: TaskEnvelope,
        proposal: Any,
    ) -> str | None:
        if not isinstance(proposal, dict):
            self._record_rejected_proposal(task, proposal, "invalid_message_shape")
            return None
        target = proposal.get("target")
        objective = proposal.get("objective")
        if not isinstance(target, str) or not isinstance(objective, str):
            self._record_rejected_proposal(task, proposal, "missing_target_or_objective")
            return None
        if len(target) > 200 or len(objective) > 4000:
            self._record_rejected_proposal(task, proposal, "message_length_exceeded")
            return None
        requested_workspace = proposal.get("workspace")
        if requested_workspace is not None:
            if not isinstance(requested_workspace, str) or os.path.normcase(
                str(Path(requested_workspace).resolve())
            ) != os.path.normcase(self.workspace):
                self._record_rejected_proposal(task, proposal, "cross_workspace_route")
                return None
        requested_permissions = proposal.get("permissions")
        if requested_permissions is not None:
            if not isinstance(requested_permissions, dict):
                self._record_rejected_proposal(task, proposal, "invalid_permissions")
                return None
            parsed_permissions = Permissions.from_dict(requested_permissions)
            if (
                parsed_permissions.write_files
                or parsed_permissions.external_write
                or parsed_permissions.cross_lane_merge
                or parsed_permissions.destructive
            ):
                self._record_rejected_proposal(task, proposal, "sensitive_permissions")
                return None
        try:
            lane_key = normalize_lane_key(target)
        except ValueError:
            self._record_rejected_proposal(task, proposal, "invalid_target_lane")
            return None
        lane = self.store.get_lane(lane_key)
        if lane is None or lane.status == LaneStatus.RETIRED:
            self._record_rejected_proposal(task, proposal, "unknown_target_lane")
            return None
        evidence_value = proposal.get("evidence", [])
        evidence = (
            [item[:2048] for item in evidence_value[:20] if isinstance(item, str)]
            if isinstance(evidence_value, list)
            else []
        )
        reply_to = proposal.get("reply_to")
        message = self.inbox_send(
            target=lane_key,
            objective=objective,
            sender=task.lane_key,
            permissions=Permissions(read=True),
            reply_to=reply_to[:200] if isinstance(reply_to, str) else task.task_id,
            evidence=evidence,
            metadata={
                "source_task_id": task.task_id,
                "agent_proposed": True,
            },
        )
        return message.message_id

    async def _dispatch_run(
        self,
        task: TaskEnvelope,
        agent_id: str,
        envelope: ContextEnvelope,
    ) -> RunOutcome:
        def persist_run_id(run_id: str) -> None:
            task.run_id = run_id
            task.updated_at = utcnow_iso()
            self.store.save_task(task)
            self.events.record(
                "run.started",
                entity_type="task",
                entity_id=task.task_id,
                payload={"run_id": run_id, "agent_id": agent_id},
            )

        governed_prompt = self.context_builder.render_task_prompt(task, envelope)
        return await self.runtime.run_task(
            agent_id,
            governed_prompt,
            idempotency_key=task.idempotency_key,
            on_started=persist_run_id,
        )

    async def _recover_startup_failure(
        self,
        task: TaskEnvelope,
        err: StartupError,
    ) -> tuple[LaneRecord, str, ContextEnvelope]:
        """Rotate a lane whose agent will not start, once failures repeat.

        A single failure may be a transient bridge blip, so the first one is
        only counted and the task fails as before. Rotating on the count
        threshold is what keeps a lane from staying dead when its agent never
        starts again.
        """
        lane = self.store.ensure_lane(task.lane_key)
        failures = self.rotation_policy.record_startup_failure(lane, str(err))
        lane.updated_at = utcnow_iso()
        self.store.upsert_lane(lane)
        self.events.record(
            "lane.startup_failed",
            entity_type="lane",
            entity_id=task.lane_key,
            payload={
                "task_id": task.task_id,
                "agent_id": lane.current_agent_id,
                "consecutive_failures": failures,
                "retryable": err.retryable,
            },
        )
        if failures < self.rotation_policy.max_startup_failures:
            raise err
        lane, agent_id, envelope = await self.agents.rotate(
            task.lane_key,
            objective=task.objective,
            spec_id=task.spec_id,
            reason="startup_failure",
        )
        self.events.metric(
            "rotation_success",
            1,
            {"lane_key": task.lane_key, "kind": "startup_recovery"},
        )
        return lane, agent_id, envelope

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        match = re.fullmatch(
            r"```(?:json)?[^\S\n]*\n(.*)\n```", text.strip(), re.DOTALL
        )
        return match.group(1) if match else text

    def _apply_agent_response(self, task: TaskEnvelope, result_text: str | None) -> None:
        if not result_text:
            return
        bounded_plain = result_text[:20_000]
        try:
            payload = json.loads(self._strip_code_fence(result_text))
        except (json.JSONDecodeError, TypeError):
            task.metadata["agent_response"] = {
                "structured": False,
                "summary": bounded_plain,
            }
            return
        valid_statuses = {"completed", "partial", "blocked", "failed"}
        if not (
            isinstance(payload, dict)
            and isinstance(payload.get("summary"), str)
            and payload.get("status") in valid_statuses
            and isinstance(payload.get("evidence"), list)
            and all(isinstance(item, str) for item in payload["evidence"])
            and isinstance(payload.get("proposed_messages"), list)
        ):
            task.metadata["agent_response"] = {
                "structured": False,
                "summary": bounded_plain,
            }
            return
        response_evidence = [item[:2048] for item in payload["evidence"][:20]]
        for pointer in response_evidence:
            if pointer not in task.evidence:
                task.evidence.append(pointer)
        proposal_ids: list[str] = []
        proposals = payload["proposed_messages"]
        for proposal in proposals[:8]:
            message_id = self._enqueue_agent_proposal(task, proposal)
            if message_id:
                proposal_ids.append(message_id)
        task.metadata["agent_response"] = {
            "structured": True,
            "summary": payload["summary"][:20_000],
            "status": payload["status"],
            "evidence": response_evidence,
            "proposed_message_ids": proposal_ids,
            "rejected_over_limit": max(0, len(proposals) - 8),
        }

    def get_status(self, task_id: str) -> TaskEnvelope | None:
        return self.store.get_task(task_id)

    def pause_lane(self, lane_key: str) -> None:
        lane_key = normalize_lane_key(lane_key)
        self._paused_lanes.add(lane_key)
        lane = self.store.ensure_lane(lane_key)
        lane.status = LaneStatus.PAUSED
        lane.updated_at = utcnow_iso()
        self.store.upsert_lane(lane)
        self.events.record("lane.paused", entity_type="lane", entity_id=lane_key)

    def resume_lane(self, lane_key: str) -> None:
        lane_key = normalize_lane_key(lane_key)
        self._paused_lanes.discard(lane_key)
        lane = self.store.ensure_lane(lane_key)
        lane.status = LaneStatus.ACTIVE if lane.current_agent_id else LaneStatus.IDLE
        lane.updated_at = utcnow_iso()
        self.store.upsert_lane(lane)
        self.events.record("lane.resumed", entity_type="lane", entity_id=lane_key)

    def pause_task(self, task_id: str) -> TaskEnvelope:
        task = self.store.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        task.status = TaskStatus.PAUSED
        task.updated_at = utcnow_iso()
        self.store.save_task(task)
        self.events.record("task.paused", entity_type="task", entity_id=task_id)
        return task

    def resume_task(self, task_id: str) -> TaskEnvelope:
        task = self.store.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        task.status = TaskStatus.QUEUED
        task.updated_at = utcnow_iso()
        self.store.save_task(task)
        self.events.record("task.resumed", entity_type="task", entity_id=task_id)
        return task

    def request_approval(self, task: TaskEnvelope, action: str, reason: str) -> ApprovalRequest:
        approval = ApprovalRequest(
            approval_id=str(uuid4()),
            workspace=self.workspace,
            task_id=task.task_id,
            lane_key=task.lane_key,
            action=action,
            reason=reason,
            status=ApprovalStatus.PENDING,
            requested_at=utcnow_iso(),
        )
        self.store.save_approval(approval)
        task.status = TaskStatus.AWAITING_APPROVAL
        task.updated_at = utcnow_iso()
        task.metadata["pending_approval_id"] = approval.approval_id
        self.store.save_task(task)
        self.events.record("approval.requested", entity_type="approval", entity_id=approval.approval_id)
        return approval

    def approve(self, approval_id: str, resolver: str = "user") -> ApprovalRequest:
        approval = self.store.get_approval(approval_id)
        if not approval:
            raise KeyError(approval_id)
        approval.status = ApprovalStatus.APPROVED
        approval.resolved_at = utcnow_iso()
        approval.resolver = resolver
        self.store.save_approval(approval)
        task = self.store.get_task(approval.task_id)
        if task:
            task.status = TaskStatus.QUEUED
            task.metadata.pop("pending_approval_id", None)
            approved_actions = list(task.metadata.get("approved_actions", []))
            for action in {approval.action, *(
                ["write_files"] if approval.action == "execute" and task.permissions.write_files else []
            )}:
                if action not in approved_actions:
                    approved_actions.append(action)
            task.metadata["approved_actions"] = approved_actions
            task.updated_at = utcnow_iso()
            self.store.save_task(task)
        latency = (
            datetime.fromisoformat(approval.resolved_at)
            - datetime.fromisoformat(approval.requested_at)
        ).total_seconds()
        self.events.metric(
            "approval_latency_seconds",
            latency,
            {"action": approval.action, "resolution": "approved"},
        )
        self.events.record("approval.approved", entity_type="approval", entity_id=approval_id)
        return approval

    def reject(self, approval_id: str, resolver: str = "user") -> ApprovalRequest:
        approval = self.store.get_approval(approval_id)
        if not approval:
            raise KeyError(approval_id)
        approval.status = ApprovalStatus.REJECTED
        approval.resolved_at = utcnow_iso()
        approval.resolver = resolver
        self.store.save_approval(approval)
        task = self.store.get_task(approval.task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error_message = "approval rejected"
            task.updated_at = utcnow_iso()
            self.store.save_task(task)
            self._sync_source_message(task)
        latency = (
            datetime.fromisoformat(approval.resolved_at)
            - datetime.fromisoformat(approval.requested_at)
        ).total_seconds()
        self.events.metric(
            "approval_latency_seconds",
            latency,
            {"action": approval.action, "resolution": "rejected"},
        )
        self.events.metric("task_failure", 1, {"reason": "approval_rejected"})
        self.events.record("approval.rejected", entity_type="approval", entity_id=approval_id)
        return approval

    async def rotate_lane(self, lane_key: str, *, objective: str, spec_id: str | None = None) -> dict[str, Any]:
        lane_key = normalize_lane_key(lane_key)
        if self.mode == "shadow":
            self.events.record(
                "rotation.proposed",
                entity_type="lane",
                entity_id=lane_key,
                payload={"objective": objective, "spec_id": spec_id},
            )
            return {
                "lane_key": lane_key,
                "agent_id": None,
                "handover_path": None,
                "proposed": True,
            }
        lane, agent_id, envelope = await self.agents.rotate(lane_key, objective=objective, spec_id=spec_id)
        self.events.metric("rotation_success", 1, {"lane_key": lane_key, "kind": "manual"})
        self.store.export_lane_registry()
        return {"lane_key": lane.lane_key, "agent_id": agent_id, "handover_path": lane.handover_path}

    def recover(
        self,
        *,
        restore_backup: Path | None = None,
        retention_days: int = 14,
    ) -> dict[str, Any]:
        restored = None
        if restore_backup is not None:
            restored = str(self.store.restore_backup(restore_backup))
            self.events.metric("backup_recovery", 1, {"source": "backup"})
        expired = self.store.expire_orphans()
        stale_claims = self.locks.recover_stale()
        dead_lettered = 0
        for task in self.store.list_tasks(status=TaskStatus.FAILED):
            if task.metadata.get("retry_exhausted"):
                self.store.dead_letter_task(task.task_id, task.error_message or "retry exhausted")
                recovered_task = self.store.get_task(task.task_id)
                if recovered_task:
                    self._sync_source_message(recovered_task)
                dead_lettered += 1
        backup_path = self.store.backup_daily(retention_days=retention_days)
        registry_path = self.store.export_lane_registry()
        return {
            "restored_backup": restored,
            "backup": str(backup_path),
            "registry": str(registry_path),
            "expired": expired,
            "stale_claims_recovered": len(stale_claims),
            "dead_lettered": dead_lettered,
        }

    async def process(self, *, max_tasks: int = 10) -> list[TaskEnvelope]:
        self.recover()
        self.route_pending_messages(max_messages=max_tasks)
        queued = [t for t in self.store.list_tasks(status=TaskStatus.QUEUED)]
        results: list[TaskEnvelope] = []
        self.last_cycle_stats = {"processed_tasks": 0, "proposed_routes": 0}
        if not queued:
            return results
        if self.mode == "shadow":
            proposed = 0
            for task in queued[:max_tasks]:
                if "shadow_proposed_at" in task.metadata:
                    continue
                task.metadata["proposed_route"] = {
                    "lane_key": task.lane_key,
                    "spec_id": task.spec_id,
                    "requires_approval": task.permissions.write_files,
                }
                task.metadata["shadow_proposed_at"] = utcnow_iso()
                task.updated_at = utcnow_iso()
                self.store.save_task(task)
                self.events.record(
                    "route.proposed",
                    entity_type="task",
                    entity_id=task.task_id,
                    payload=task.metadata["proposed_route"],
                )
                proposed += 1
            self.last_cycle_stats["proposed_routes"] = proposed
            return queued[:max_tasks]

        by_lane: dict[str, list[TaskEnvelope]] = {}
        for task in queued[:max_tasks]:
            by_lane.setdefault(task.lane_key, []).append(task)

        async def run_lane(lane_key: str, tasks: list[TaskEnvelope]) -> list[TaskEnvelope]:
            lane = self.store.get_lane(lane_key)
            if lane_key in self._paused_lanes or (
                lane and lane.status == LaneStatus.PAUSED
            ):
                return []
            async with self._lane_lock(lane_key):
                completed: list[TaskEnvelope] = []
                for task in tasks:
                    done = await self._execute_task(task)
                    self._sync_source_message(done)
                    completed.append(done)
                return completed

        lane_results = await asyncio.gather(
            *[run_lane(lane_key, lane_tasks) for lane_key, lane_tasks in by_lane.items()]
        )
        for batch in lane_results:
            results.extend(batch)
        self.last_cycle_stats["processed_tasks"] = len(results)
        self.store.export_lane_registry()
        return results

    async def _execute_task(self, task: TaskEnvelope) -> TaskEnvelope:
        if self.mode == "read-only" and task.permissions.write_files:
            task.status = TaskStatus.FAILED
            task.error_message = "Read-only mode denied write-capable task"
            task.updated_at = utcnow_iso()
            self.store.save_task(task)
            self.events.metric("task_failure", 1, {"reason": "read_only_denial"})
            return task
        approved_actions = set(task.metadata.get("approved_actions", []))
        decision = self.policy.evaluate_action("execute", task, self.workspace)
        if not decision.allowed and not decision.requires_approval:
            task.status = TaskStatus.FAILED
            task.error_message = decision.reason
            task.updated_at = utcnow_iso()
            self.store.save_task(task)
            self.events.metric("task_failure", 1, {"reason": "policy_denial"})
            return task
        if decision.requires_approval and "execute" not in approved_actions:
            self.request_approval(task, "execute", decision.reason)
            return self.store.get_task(task.task_id) or task

        if task.permissions.write_files:
            write_decision = self.policy.evaluate_action("write_files", task, self.workspace)
            if write_decision.requires_approval and "write_files" not in approved_actions:
                self.request_approval(task, "write_files", write_decision.reason)
                return self.store.get_task(task.task_id) or task

        acquired_artifacts: list[str] = []
        for artifact in task.artifacts:
            try:
                self.locks.acquire(
                    artifact,
                    task.lane_key,
                    task.sender,
                    task_id=task.task_id,
                    write_capable=task.permissions.write_files,
                )
                acquired_artifacts.append(artifact)
            except PermissionError as err:
                for acquired in acquired_artifacts:
                    self.locks.release(acquired, task.lane_key)
                task.status = TaskStatus.FAILED
                task.error_message = str(err)
                task.updated_at = utcnow_iso()
                self.store.save_task(task)
                self.events.metric("task_failure", 1, {"reason": "artifact_lock"})
                return task

        lane = self.store.ensure_lane(task.lane_key)
        task.status = TaskStatus.RUNNING
        task.metadata["run_owner"] = self.execution_owner
        task.metadata["run_started_at"] = utcnow_iso()
        task.updated_at = utcnow_iso()
        self.store.save_task(task)

        try:
            preview = self.context_builder.build(lane, task)
            rotation = self.rotation_policy.evaluate(lane, task, preview)
            if lane.current_agent_id and rotation.rotate:
                lane, agent_id, envelope = await self.agents.rotate(
                    task.lane_key,
                    objective=task.objective,
                    spec_id=task.spec_id,
                    reason=",".join(rotation.reasons),
                )
                self.events.metric(
                    "rotation_success",
                    1,
                    {"lane_key": task.lane_key, "kind": "automatic"},
                )
            elif lane.current_agent_id:
                try:
                    lane, agent_id, envelope = await self.agents.resume(
                        task.lane_key,
                        objective=task.objective,
                        spec_id=task.spec_id,
                    )
                except StartupError as err:
                    lane, agent_id, envelope = await self._recover_startup_failure(
                        task, err
                    )
            else:
                lane, agent_id, envelope = await self.agents.create(
                    task.lane_key,
                    objective=task.objective,
                    spec_id=task.spec_id,
                )
            task.agent_id = agent_id
            self.rotation_policy.clear_startup_failures(lane)
            self.rotation_policy.record_task_start(lane, task, envelope)
            self.store.upsert_lane(lane)
            self.store.save_task(task)

            try:
                outcome = await self._dispatch_run(task, agent_id, envelope)
            except AgentBusyError:
                lane, agent_id, envelope = await self.agents.rotate(
                    task.lane_key,
                    objective=task.objective,
                    spec_id=task.spec_id,
                    reason="agent_busy",
                )
                task.agent_id = agent_id
                self.rotation_policy.record_task_start(lane, task, envelope)
                self.store.upsert_lane(lane)
                self.store.save_task(task)
                self.events.metric(
                    "rotation_success",
                    1,
                    {"lane_key": task.lane_key, "kind": "recovery"},
                )
                outcome = await self._dispatch_run(task, agent_id, envelope)
            task.run_id = outcome.run_id
            self._apply_agent_response(task, outcome.result_text)
            if outcome.status == "error":
                task.status = TaskStatus.FAILED
                task.failure_kind = FailureKind.RUN
                task.error_message = outcome.error_message
                self.events.metric("task_failure", 1, {"kind": "run"})
            else:
                task.status = TaskStatus.COMPLETED
                self.events.metric("task_throughput", 1, {"lane_key": task.lane_key})
            task.updated_at = utcnow_iso()
            self.store.save_task(task)
            self.events.record(
                "task.completed" if task.status == TaskStatus.COMPLETED else "task.failed",
                entity_type="task",
                entity_id=task.task_id,
                payload={"run_id": outcome.run_id, "failure_kind": task.failure_kind.value if task.failure_kind else None},
            )
        except StartupError as err:
            task.status = TaskStatus.FAILED
            task.failure_kind = FailureKind.STARTUP
            task.error_message = str(err)
            task.updated_at = utcnow_iso()
            self.store.save_task(task)
            self.events.metric("task_failure", 1, {"kind": "startup"})
            self.events.record(
                "task.startup_failed",
                entity_type="task",
                entity_id=task.task_id,
                payload={"retryable": err.retryable},
            )
        except Exception as err:
            task.status = TaskStatus.FAILED
            task.failure_kind = FailureKind.STARTUP
            task.error_message = str(err)
            task.updated_at = utcnow_iso()
            self.store.save_task(task)
            self.events.metric("task_failure", 1, {"kind": "startup"})
            self.events.record(
                "task.startup_failed",
                entity_type="task",
                entity_id=task.task_id,
                payload={"retryable": False, "unexpected": True},
            )
        finally:
            for artifact in acquired_artifacts:
                self.locks.release(artifact, task.lane_key)
            lane = self.store.get_lane(task.lane_key)
            if lane and lane.current_agent_id:
                await self.runtime.dispose_agent(lane.current_agent_id)
                lane.status = LaneStatus.IDLE
                self.rotation_policy.record_task_end(lane)
                lane.updated_at = utcnow_iso()
                self.store.upsert_lane(lane)
        return self.store.get_task(task.task_id) or task

    def snapshot(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "mode": self.mode,
            "lanes": [lane.to_dict() for lane in self.store.list_lanes()],
            "tasks": [task.to_dict() for task in self.store.list_tasks()],
            "messages": [message.to_dict() for message in self.store.list_messages()],
            "approvals": [approval.to_dict() for approval in self.store.list_approvals()],
            "claims": [claim.to_dict() for claim in self.store.list_active_claims()],
            "events": self.store.list_events(limit=100),
            "metrics": self.store.list_metrics(),
            "backups": [str(path) for path in self.store.list_backups()],
            "registry_path": str(self.store.registry_path),
            "heartbeat": self.store.get_service_heartbeat() or {},
        }

    async def aclose(self) -> None:
        await self.runtime.close()
        self.store.close()

    def close(self) -> None:
        """Close only local state; async callers should use ``aclose``."""
        self.store.close()
