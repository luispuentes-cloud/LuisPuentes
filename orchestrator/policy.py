from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Permissions, TaskEnvelope


@dataclass
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    policy_id: str
    reason: str


class PolicyRegistry:
    def __init__(self, registry_path: Path | None = None) -> None:
        default = Path(__file__).resolve().parent.parent / "policies" / "registry.json"
        self.registry_path = registry_path or default
        self.policies = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"policies": []}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def reload(self) -> None:
        self.policies = self._load()

    def list_policy_ids(self) -> list[str]:
        return [p["id"] for p in self.policies.get("policies", [])]

    def _policy_matches(self, policy: dict[str, Any], action: str, task: TaskEnvelope) -> bool:
        actions = policy.get("actions", [])
        if action not in actions and "*" not in actions:
            return False
        when = policy.get("when", {})
        if when.get("metadata_flag") and not task.metadata.get(when["metadata_flag"]):
            return False
        if when.get("permission") and not getattr(task.permissions, when["permission"], False):
            return False
        return True

    def evaluate_action(self, action: str, task: TaskEnvelope, workspace: str) -> PolicyDecision:
        approval_decision: PolicyDecision | None = None
        for policy in self.policies.get("policies", []):
            if policy.get("workspace_scope") and policy["workspace_scope"] != workspace:
                continue
            if not self._policy_matches(policy, action, task):
                continue
            if policy.get("client_isolation") and task.workspace != workspace:
                return PolicyDecision(
                    allowed=False,
                    requires_approval=False,
                    policy_id=policy["id"],
                    reason="Cross-workspace action blocked by client isolation policy",
                )
            if policy.get("client_isolation"):
                continue
            requires_approval = bool(policy.get("requires_approval", False))
            if policy.get("write_authorization") and action in {"write_files", "execute"}:
                if task.permissions.write_files:
                    approval_decision = PolicyDecision(
                        allowed=False,
                        requires_approval=True,
                        policy_id=policy["id"],
                        reason=policy.get("reason", "Write authorization requires supervised approval"),
                    )
                    continue
                if action == "write_files":
                    approval_decision = PolicyDecision(
                        allowed=False,
                        requires_approval=requires_approval,
                        policy_id=policy["id"],
                        reason="Write authorization required",
                    )
                continue
            if policy.get("external_write") and not task.permissions.external_write:
                approval_decision = PolicyDecision(
                    allowed=False,
                    requires_approval=True,
                    policy_id=policy["id"],
                    reason="External write requires approval",
                )
                continue
            if policy.get("destructive") and not task.permissions.destructive:
                approval_decision = PolicyDecision(
                    allowed=False,
                    requires_approval=True,
                    policy_id=policy["id"],
                    reason="Destructive action requires approval",
                )
                continue
            if requires_approval:
                approval_decision = PolicyDecision(
                    allowed=False,
                    requires_approval=True,
                    policy_id=policy["id"],
                    reason=policy.get("reason", f"Action {action} requires supervised approval"),
                )
        if approval_decision:
            return approval_decision
        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            policy_id="default",
            reason="No matching restrictive policy",
        )

    def permissions_for_spec(self, spec: dict[str, Any]) -> Permissions:
        controls = spec.get("controls", {})
        return Permissions(
            read=controls.get("read", True),
            write_files=controls.get("write_files", False),
            external_write=controls.get("external_write", False),
            cross_lane_merge=controls.get("cross_lane_merge", False),
            destructive=controls.get("destructive", False),
        )

    def policy_ids_for_spec(self, spec: dict[str, Any]) -> list[str]:
        return list(spec.get("policy_ids", []))
