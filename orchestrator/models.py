from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def normalize_lane_key(lane_key: str) -> str:
    """Collapse leading, trailing, and repeated whitespace. Keep underscores."""
    normalized = " ".join(str(lane_key).split())
    if not normalized:
        raise ValueError("lane_key is empty")
    return normalized


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    EXPIRED = "expired"


class MessageStatus(str, Enum):
    PENDING = "pending"
    ROUTED = "routed"
    DELIVERED = "delivered"
    EXPIRED = "expired"
    DEAD_LETTER = "dead_letter"


class LaneStatus(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    ROTATING = "rotating"
    PAUSED = "paused"
    RETIRED = "retired"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class FailureKind(str, Enum):
    STARTUP = "startup"
    RUN = "run"


@dataclass
class Permissions:
    read: bool = True
    write_files: bool = False
    external_write: bool = False
    cross_lane_merge: bool = False
    destructive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Permissions:
        if not data:
            return cls()
        return cls(**{k: bool(data.get(k, getattr(cls(), k))) for k in asdict(cls()).keys()})


@dataclass
class TaskEnvelope:
    task_id: str
    workspace: str
    lane_key: str
    objective: str
    sender: str
    target: str
    status: TaskStatus
    permissions: Permissions
    idempotency_key: str | None = None
    reply_to: str | None = None
    evidence: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    spec_id: str | None = None
    ttl_seconds: int | None = None
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)
    expires_at: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    failure_kind: FailureKind | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["permissions"] = self.permissions.to_dict()
        if self.failure_kind:
            payload["failure_kind"] = self.failure_kind.value
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskEnvelope:
        failure = data.get("failure_kind")
        return cls(
            task_id=data["task_id"],
            workspace=data["workspace"],
            lane_key=data["lane_key"],
            objective=data["objective"],
            sender=data["sender"],
            target=data["target"],
            status=TaskStatus(data["status"]),
            permissions=Permissions.from_dict(data.get("permissions")),
            idempotency_key=data.get("idempotency_key"),
            reply_to=data.get("reply_to"),
            evidence=list(data.get("evidence") or []),
            artifacts=list(data.get("artifacts") or []),
            spec_id=data.get("spec_id"),
            ttl_seconds=data.get("ttl_seconds"),
            created_at=data.get("created_at", utcnow_iso()),
            updated_at=data.get("updated_at", utcnow_iso()),
            expires_at=data.get("expires_at"),
            agent_id=data.get("agent_id"),
            run_id=data.get("run_id"),
            failure_kind=FailureKind(failure) if failure else None,
            error_message=data.get("error_message"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class MessageEnvelope:
    message_id: str
    workspace: str
    sender: str
    target: str
    objective: str
    status: MessageStatus
    permissions: Permissions
    reply_to: str | None = None
    evidence: list[str] = field(default_factory=list)
    ttl_seconds: int | None = None
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def executable(self) -> bool:
        """Whether this message may be converted into agent work.

        Coordination mail between sessions is the common case and must never
        execute on its own, so the absence of the flag means no. Messages
        written before the flag existed therefore read as coordination-only.
        """
        return bool(self.metadata.get("executable"))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["permissions"] = self.permissions.to_dict()
        payload["executable"] = self.executable
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageEnvelope:
        return cls(
            message_id=data["message_id"],
            workspace=data["workspace"],
            sender=data["sender"],
            target=data["target"],
            objective=data["objective"],
            status=MessageStatus(data["status"]),
            permissions=Permissions.from_dict(data.get("permissions")),
            reply_to=data.get("reply_to"),
            evidence=list(data.get("evidence") or []),
            ttl_seconds=data.get("ttl_seconds"),
            created_at=data.get("created_at", utcnow_iso()),
            updated_at=data.get("updated_at", utcnow_iso()),
            expires_at=data.get("expires_at"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class LaneRecord:
    workspace: str
    lane_key: str
    status: LaneStatus
    current_agent_id: str | None = None
    prior_agent_ids: list[str] = field(default_factory=list)
    handover_path: str | None = None
    last_activity: str | None = None
    context_health_score: float = 1.0
    owner: str | None = None
    active_artifact_claims: list[str] = field(default_factory=list)
    model: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LaneRecord:
        return cls(
            workspace=data["workspace"],
            lane_key=data["lane_key"],
            status=LaneStatus(data["status"]),
            current_agent_id=data.get("current_agent_id"),
            prior_agent_ids=list(data.get("prior_agent_ids") or []),
            handover_path=data.get("handover_path"),
            last_activity=data.get("last_activity"),
            context_health_score=float(data.get("context_health_score", 1.0)),
            owner=data.get("owner"),
            active_artifact_claims=list(data.get("active_artifact_claims") or []),
            model=data.get("model"),
            config=dict(data.get("config") or {}),
            created_at=data.get("created_at", utcnow_iso()),
            updated_at=data.get("updated_at", utcnow_iso()),
        )


@dataclass
class ArtifactClaim:
    claim_id: str
    workspace: str
    artifact_path: str
    lane_key: str
    task_id: str | None
    owner: str
    write_capable: bool
    acquired_at: str
    expires_at: str | None = None
    released_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactClaim:
        return cls(**data)


@dataclass
class ApprovalRequest:
    approval_id: str
    workspace: str
    task_id: str
    lane_key: str
    action: str
    reason: str
    status: ApprovalStatus
    requested_at: str
    resolved_at: str | None = None
    resolver: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRequest:
        return cls(
            approval_id=data["approval_id"],
            workspace=data["workspace"],
            task_id=data["task_id"],
            lane_key=data["lane_key"],
            action=data["action"],
            reason=data["reason"],
            status=ApprovalStatus(data["status"]),
            requested_at=data["requested_at"],
            resolved_at=data.get("resolved_at"),
            resolver=data.get("resolver"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class ContextEnvelope:
    workspace: str
    lane_key: str
    objective: str
    canonical_sources: list[str] = field(default_factory=list)
    latest_decisions: list[str] = field(default_factory=list)
    open_work: list[str] = field(default_factory=list)
    artifact_claims: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    policy_ids: list[str] = field(default_factory=list)
    spec_id: str | None = None
    generated_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextEnvelope:
        return cls(**{k: data.get(k, getattr(cls("", "", ""), k)) for k in asdict(cls("", "", "")).keys()})


@dataclass
class AgentConfig:
    model: str = "composer-2.5"
    api_key: str | None = None
    cwd: str | None = None
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)
    sandbox: dict[str, Any] = field(default_factory=dict)
    policies: list[str] = field(default_factory=list)
    setting_sources: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AgentConfig:
        if not data:
            return cls()
        return cls(
            model=data.get("model", "composer-2.5"),
            api_key=data.get("api_key"),
            cwd=data.get("cwd"),
            mcp_servers=dict(data.get("mcp_servers") or {}),
            sandbox=dict(data.get("sandbox") or {}),
            policies=list(data.get("policies") or []),
            setting_sources=list(data.get("setting_sources") or []),
            tools=list(data.get("tools") or []),
            disallowed_tools=list(data.get("disallowed_tools") or []),
        )


@dataclass
class RunOutcome:
    agent_id: str
    run_id: str
    status: str
    failure_kind: FailureKind | None = None
    error_message: str | None = None
    result_text: str | None = None
