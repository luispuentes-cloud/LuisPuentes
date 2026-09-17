from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import ContextEnvelope, LaneRecord, TaskEnvelope


@dataclass(frozen=True)
class RotationDecision:
    rotate: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class RotationPolicy:
    max_runs: int = 8
    max_active_seconds: int = 14_400
    min_health: float = 0.45
    max_envelope_bytes: int = 24_000
    max_corrections: int = 2
    max_task_boundaries: int = 5
    max_startup_failures: int = 2

    def evaluate(
        self,
        lane: LaneRecord,
        task: TaskEnvelope,
        envelope: ContextEnvelope,
        *,
        now: datetime | None = None,
    ) -> RotationDecision:
        counters = dict(lane.config.get("rotation", {}))
        reasons: list[str] = []
        if int(counters.get("run_count", 0)) >= self.max_runs:
            reasons.append("run_count")
        active_since = counters.get("active_since")
        if active_since:
            current = now or datetime.now(timezone.utc)
            if (current - datetime.fromisoformat(active_since)).total_seconds() >= self.max_active_seconds:
                reasons.append("active_age")
        if lane.context_health_score <= self.min_health:
            reasons.append("context_health")
        if len(json.dumps(envelope.to_dict()).encode("utf-8")) >= self.max_envelope_bytes:
            reasons.append("envelope_size")
        if int(counters.get("correction_count", 0)) >= self.max_corrections:
            reasons.append("repeated_correction")
        if int(counters.get("task_boundary_count", 0)) >= self.max_task_boundaries:
            reasons.append("task_boundary")
        prior_spec = counters.get("last_spec_id")
        if prior_spec and task.spec_id and prior_spec != task.spec_id:
            reasons.append("workstream_shift")
        return RotationDecision(bool(reasons), reasons)

    def record_task_start(
        self,
        lane: LaneRecord,
        task: TaskEnvelope,
        envelope: ContextEnvelope,
    ) -> None:
        counters = dict(lane.config.get("rotation", {}))
        counters.setdefault("active_since", lane.last_activity or task.created_at)
        counters["last_spec_id"] = task.spec_id
        counters["last_objective"] = task.objective
        counters["last_envelope_bytes"] = len(
            json.dumps(envelope.to_dict()).encode("utf-8")
        )
        counters["correction_count"] = int(
            task.metadata.get("correction_count", counters.get("correction_count", 0))
        )
        lane.config["rotation"] = counters

    def record_startup_failure(self, lane: LaneRecord, error: str) -> int:
        """Count consecutive startup failures on a lane; return the new count.

        Lives in ``lane.config`` so the count survives a coordinator restart.
        """
        counters = dict(lane.config.get("rotation", {}))
        count = int(counters.get("startup_failure_count", 0)) + 1
        counters["startup_failure_count"] = count
        counters["last_startup_error"] = error[:2000]
        lane.config["rotation"] = counters
        return count

    @staticmethod
    def clear_startup_failures(lane: LaneRecord) -> None:
        counters = dict(lane.config.get("rotation", {}))
        counters.pop("startup_failure_count", None)
        counters.pop("last_startup_error", None)
        lane.config["rotation"] = counters

    def record_task_end(self, lane: LaneRecord) -> None:
        counters = dict(lane.config.get("rotation", {}))
        counters["run_count"] = int(counters.get("run_count", 0)) + 1
        counters["task_boundary_count"] = int(
            counters.get("task_boundary_count", 0)
        ) + 1
        lane.config["rotation"] = counters

    @staticmethod
    def reset(lane: LaneRecord) -> None:
        lane.config["rotation"] = {
            "run_count": 0,
            "task_boundary_count": 0,
            "correction_count": 0,
            "active_since": datetime.now(timezone.utc).isoformat(),
            "last_spec_id": None,
            "last_objective": None,
            "last_envelope_bytes": 0,
        }
