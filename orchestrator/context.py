from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ContextEnvelope, LaneRecord, TaskEnvelope, utcnow_iso
from .policy import PolicyRegistry
from .state import ControlStore


class ContextEnvelopeBuilder:
    def __init__(self, store: ControlStore, policy_registry: PolicyRegistry | None = None) -> None:
        self.store = store
        self.policy_registry = policy_registry or PolicyRegistry()

    def load_spec(self, spec_id: str) -> dict[str, Any]:
        specs_dir = Path(__file__).resolve().parent.parent / "specs"
        path = specs_dir / f"{spec_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Execution spec not found: {spec_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def build(
        self,
        lane: LaneRecord,
        task: TaskEnvelope | None = None,
        *,
        spec_id: str | None = None,
    ) -> ContextEnvelope:
        spec: dict[str, Any] = {}
        resolved_spec_id = spec_id or (task.spec_id if task else None)
        if resolved_spec_id:
            spec = self.load_spec(resolved_spec_id)

        open_tasks = [
            t.objective
            for t in self.store.list_tasks()
            if t.lane_key == lane.lane_key and t.status.value in {"queued", "running", "paused"}
        ]
        claims = [c.artifact_path for c in self.store.list_active_claims() if c.lane_key == lane.lane_key]
        policy_ids = self.policy_registry.policy_ids_for_spec(spec) if spec else self.policy_registry.list_policy_ids()

        envelope = ContextEnvelope(
            workspace=lane.workspace,
            lane_key=lane.lane_key,
            objective=task.objective if task else spec.get("objective", lane.lane_key),
            canonical_sources=list(spec.get("evidence", {}).get("canonical_sources", [])),
            latest_decisions=list(spec.get("evidence", {}).get("latest_decisions", [])),
            open_work=open_tasks,
            artifact_claims=claims,
            allowed_actions=list(spec.get("controls", {}).get("allowed_actions", ["read", "summarize", "validate"])),
            policy_ids=policy_ids,
            spec_id=resolved_spec_id,
            generated_at=utcnow_iso(),
        )
        return envelope

    def validate(self, envelope: ContextEnvelope) -> list[str]:
        errors: list[str] = []
        if not envelope.workspace:
            errors.append("workspace is required")
        if not envelope.lane_key:
            errors.append("lane_key is required")
        if not envelope.objective:
            errors.append("objective is required")
        if not envelope.policy_ids:
            errors.append("at least one policy id is required")
        return errors

    def render_task_prompt(
        self,
        task: TaskEnvelope,
        envelope: ContextEnvelope,
    ) -> str:
        """Render the complete governed prompt as deterministic JSON."""
        spec = self.load_spec(task.spec_id) if task.spec_id else {}
        payload = {
            "protocol": "cursor-local-orchestrator-task/v1",
            "context_envelope": envelope.to_dict(),
            "task": {
                "task_id": task.task_id,
                "objective": task.objective,
                "sender": task.sender,
                "target": task.target,
                "permissions": task.permissions.to_dict(),
                "evidence_pointers": list(task.evidence),
                "artifact_paths": list(task.artifacts),
                "reply_to": task.reply_to,
                "idempotency_key": task.idempotency_key,
                "metadata": dict(task.metadata),
            },
            "execution_spec": {
                "id": spec.get("id"),
                "version": spec.get("version"),
                "objective": spec.get("objective"),
                "kpi": spec.get("kpi", []),
                "work_graph": spec.get("work_graph", []),
                "decision_rights": spec.get("decision_rights", {}),
                "controls": spec.get("controls", {}),
                "dependencies": spec.get("dependencies", {}),
                "integrations": spec.get("integrations", {}),
                "evidence": spec.get("evidence", {}),
                "failure_scenarios": spec.get("failure_scenarios", []),
                "policy_ids": spec.get("policy_ids", []),
            },
            "supervision": {
                "instructions": [
                    "Operate only inside the supplied workspace and context envelope.",
                    "Stop before any file write, external-system write, cross-lane merge, destructive action, or action outside the task permissions.",
                    "Do not claim or perform an approval-gated action unless the task metadata records coordinator approval.",
                    "Return evidence and artifact pointers through the coordinator; do not message another agent directly.",
                    "If a canonical source is missing, stale, duplicated, or conflicting, stop and report the issue.",
                ],
                "approval_required_for": [
                    "file_write",
                    "external_write",
                    "cross_lane_merge",
                    "destructive_action",
                    "out_of_envelope_action",
                ],
            },
            "response_contract": {
                "format": "json",
                "required": [
                    "summary",
                    "status",
                    "evidence",
                    "proposed_messages",
                ],
                "schema": {
                    "summary": "string",
                    "status": "completed|partial|blocked|failed",
                    "evidence": ["string pointer"],
                    "proposed_messages": [
                        {
                            "target": "existing lane key",
                            "objective": "bounded read-only objective",
                            "evidence": ["optional string pointer"],
                            "reply_to": "optional message or task id",
                        }
                    ],
                },
                "constraints": [
                    "Do not include workspace; routing is limited to this workspace.",
                    "Proposed messages are read-only and cannot request sensitive permissions.",
                    "Unknown target lanes are rejected and dead-lettered.",
                    "Return no more than 8 proposed messages.",
                ],
            },
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
