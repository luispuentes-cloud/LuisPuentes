from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cursor_sdk import CursorAgentError

from orchestrator import cli
from orchestrator.coordinator import Coordinator
from orchestrator.dashboard import render_dashboard
from orchestrator.models import (
    AgentConfig,
    FailureKind,
    Permissions,
    TaskStatus,
)
from orchestrator.rotation import RotationPolicy
from orchestrator.runtime import (
    AgentBusyError,
    CursorSDKRuntime,
    FakeRuntime,
    StartupError,
)
from orchestrator.state import ControlStore


class MockRun:
    def __init__(self, result: Any, run_id: str = "run-live") -> None:
        self.id = run_id
        self._result = result

    async def wait(self) -> Any:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class MockAgent:
    def __init__(self, agent_id: str, run: MockRun | Exception) -> None:
        self.agent_id = agent_id
        self.run = run
        self.closed = 0
        self.send_calls: list[tuple[str, str | None]] = []

    async def send(self, prompt: str, *, idempotency_key: str | None = None) -> MockRun:
        self.send_calls.append((prompt, idempotency_key))
        if isinstance(self.run, Exception):
            raise self.run
        return self.run

    async def close(self) -> None:
        self.closed += 1


class MockClient:
    def __init__(self, agent: MockAgent) -> None:
        self.agent = agent
        self.created_options: list[dict[str, Any]] = []
        self.resumed_options: list[tuple[str, dict[str, Any]]] = []
        self.aclosed = 0
        self.get_agent_called = False

    async def create_agent(self, options: dict[str, Any]) -> MockAgent:
        self.created_options.append(options)
        return self.agent

    async def resume_agent(self, agent_id: str, options: dict[str, Any]) -> MockAgent:
        self.resumed_options.append((agent_id, options))
        return self.agent

    async def get_agent(self, agent_id: str) -> None:
        self.get_agent_called = True
        return None

    async def aclose(self) -> None:
        self.aclosed += 1


class FailingCreateClient(MockClient):
    async def create_agent(self, options: dict[str, Any]) -> MockAgent:
        raise CursorAgentError("missing key", is_retryable=False)


def coordinator(
    workspace: Path,
    state_root: Path,
    runtime: FakeRuntime | None = None,
    *,
    mode: str = "supervised",
    rotation_policy: RotationPolicy | None = None,
) -> Coordinator:
    return Coordinator(
        str(workspace),
        runtime or FakeRuntime(),
        state_root=state_root,
        mode=mode,
        rotation_policy=rotation_policy,
    )


@pytest.mark.asyncio
async def test_sdk_runtime_uses_actual_close_and_ids(tmp_path: Path) -> None:
    result = SimpleNamespace(
        id="result-id",
        agent_id="agent-1",
        status="finished",
        result="done",
    )
    agent = MockAgent("agent-1", MockRun(result))
    client = MockClient(agent)
    runtime = CursorSDKRuntime(
        client,
        api_key="test-key",
        config_overrides={
            "model": "model-x",
            "mcp_servers": {"local": {"command": "safe-test-double"}},
            "sandbox": {"enabled": True},
            "tools": ["ReadFile"],
            "disallowed_tools": ["Shell"],
        },
    )
    config = AgentConfig(model="old-model", cwd=str(tmp_path))
    agent_id = await runtime.create_agent(config, SimpleNamespace())
    started: list[str] = []
    outcome = await runtime.run_task(
        agent_id,
        "hello",
        idempotency_key="idem",
        on_started=started.append,
    )

    assert outcome.run_id == "result-id"
    assert started == ["run-live"]
    assert agent.send_calls == [("hello", None)]
    options = client.created_options[0]
    assert options["model"] == "model-x"
    assert options["api_key"] == "test-key"
    assert options["mcp_servers"]["local"]["command"] == "safe-test-double"
    assert options["tools"] == ["ReadFile"]
    assert options["disallowed_tools"] == ["Shell"]
    assert options["local"]["cwd"] == str(tmp_path)
    json.dumps(options)

    await runtime.dispose_agent(agent_id)
    await runtime.close()
    assert agent.closed == 1
    assert client.aclosed == 1


@pytest.mark.asyncio
async def test_sdk_runtime_resume_reapplies_config_and_no_get_fallback(
    tmp_path: Path,
) -> None:
    result = SimpleNamespace(
        id="run-2", agent_id="agent-1", status="finished", result=""
    )
    agent = MockAgent("agent-1", MockRun(result))
    client = MockClient(agent)
    runtime = CursorSDKRuntime(client, api_key="key")
    config = AgentConfig(model="model-y", cwd=str(tmp_path))

    await runtime.resume_agent("agent-1", config, SimpleNamespace())
    assert client.resumed_options[0][1]["model"] == "model-y"
    await runtime.dispose_agent("agent-1")
    with pytest.raises(StartupError, match="resume it"):
        await runtime.run_task("agent-1", "not live")
    assert client.get_agent_called is False
    await runtime.close()


@pytest.mark.asyncio
async def test_sdk_runtime_distinguishes_startup_and_run_failure(
    tmp_path: Path,
) -> None:
    startup_agent = MockAgent(
        "agent-startup",
        CursorAgentError("bridge failed", is_retryable=True),
    )
    startup_runtime = CursorSDKRuntime(MockClient(startup_agent))
    await startup_runtime.create_agent(
        AgentConfig(model="m", cwd=str(tmp_path)), SimpleNamespace()
    )
    with pytest.raises(StartupError) as exc:
        await startup_runtime.run_task("agent-startup", "prompt")
    assert exc.value.retryable is True

    run_result = SimpleNamespace(
        id="run-error",
        agent_id="agent-run",
        status="error",
        result="tool failed",
    )
    run_agent = MockAgent("agent-run", MockRun(run_result))
    run_runtime = CursorSDKRuntime(MockClient(run_agent))
    await run_runtime.create_agent(
        AgentConfig(model="m", cwd=str(tmp_path)), SimpleNamespace()
    )
    outcome = await run_runtime.run_task("agent-run", "prompt")
    assert outcome.failure_kind == FailureKind.RUN
    assert outcome.run_id == "run-error"
    assert outcome.error_message == "tool failed"


@pytest.mark.asyncio
async def test_sdk_runtime_maps_untyped_busy_error(tmp_path: Path) -> None:
    agent = MockAgent(
        "agent-busy",
        CursorAgentError("Agent agent-busy already has active run"),
    )
    runtime = CursorSDKRuntime(MockClient(agent))
    await runtime.create_agent(
        AgentConfig(model="m", cwd=str(tmp_path)), SimpleNamespace()
    )
    with pytest.raises(AgentBusyError):
        await runtime.run_task("agent-busy", "prompt")


@pytest.mark.asyncio
async def test_sdk_runtime_wraps_create_configuration_failure(
    tmp_path: Path,
) -> None:
    agent = MockAgent("unused", MockRun(SimpleNamespace()))
    runtime = CursorSDKRuntime(FailingCreateClient(agent))
    with pytest.raises(StartupError, match="missing key") as exc:
        await runtime.create_agent(
            AgentConfig(model="m", cwd=str(tmp_path)), SimpleNamespace()
        )
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_shadow_and_read_only_modes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    shadow_runtime = FakeRuntime()
    shadow = coordinator(workspace, state_root, shadow_runtime, mode="shadow")
    task = shadow.submit_task(lane_key="lane", objective="propose")
    result = await shadow.process()
    assert result[0].status == TaskStatus.QUEUED
    assert result[0].metadata["proposed_route"]["lane_key"] == "lane"
    assert shadow_runtime.created == []
    rotation = await shadow.rotate_lane("lane", objective="propose rotation")
    assert rotation["proposed"] is True
    assert shadow_runtime.created == []
    await shadow.aclose()

    read_only = coordinator(
        workspace, tmp_path / "readonly-state", FakeRuntime(), mode="read-only"
    )
    with pytest.raises(PermissionError, match="Read-only"):
        read_only.submit_task(
            lane_key="lane",
            objective="write",
            permissions=Permissions(write_files=True),
        )
    await read_only.aclose()


@pytest.mark.asyncio
async def test_automatic_rotation_and_restart_safe_counters(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    runtime = FakeRuntime()
    policy = RotationPolicy(max_runs=1)
    first = coordinator(
        workspace, state_root, runtime, rotation_policy=policy
    )
    first_task = first.submit_task(lane_key="lane", objective="one")
    await first.process()
    lane = first.store.get_lane("lane")
    assert lane is not None
    first_agent = lane.current_agent_id
    assert lane.config["rotation"]["run_count"] == 1
    first.close()

    restarted = coordinator(
        workspace, state_root, runtime, rotation_policy=policy
    )
    restored_lane = restarted.store.get_lane("lane")
    assert restored_lane is not None
    assert restored_lane.config["rotation"]["run_count"] == 1
    restarted.submit_task(lane_key="lane", objective="two")
    await restarted.process()
    rotated_lane = restarted.store.get_lane("lane")
    assert rotated_lane is not None
    assert rotated_lane.current_agent_id != first_agent
    assert first_agent in rotated_lane.prior_agent_ids
    assert any(m["name"] == "rotation_success" for m in restarted.store.list_metrics())
    await restarted.aclose()


def test_rotation_policy_all_signals(tmp_path: Path) -> None:
    store = ControlStore(str(tmp_path), tmp_path / "state")
    lane = store.ensure_lane("lane")
    lane.context_health_score = 0.1
    lane.config["rotation"] = {
        "run_count": 8,
        "active_since": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "correction_count": 3,
        "task_boundary_count": 5,
        "last_spec_id": "old",
    }
    store.upsert_lane(lane)
    coord = Coordinator(
        str(tmp_path),
        FakeRuntime(),
        state_root=tmp_path / "state",
        rotation_policy=RotationPolicy(max_envelope_bytes=1),
    )
    task = coord.submit_task(
        lane_key="lane",
        objective="new",
        spec_id="session_lifecycle",
    )
    envelope = coord.context_builder.build(lane, task)
    decision = coord.rotation_policy.evaluate(lane, task, envelope)
    assert set(decision.reasons) == {
        "run_count",
        "active_age",
        "context_health",
        "envelope_size",
        "repeated_correction",
        "task_boundary",
        "workstream_shift",
    }
    coord.close()


def test_bounded_delegation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    coord = coordinator(workspace, tmp_path / "state")
    parent = coord.submit_task(lane_key="lane", objective="parent")
    child = coord.delegate_task(
        parent.task_id,
        task_type="review",
        objective="review parent",
    )
    assert child.metadata["delegation_depth"] == 1
    assert child.metadata["parent_task_id"] == parent.task_id
    with pytest.raises(PermissionError, match="Recursive"):
        coord.delegate_task(
            child.task_id,
            task_type="extraction",
            objective="not allowed",
        )
    with pytest.raises(PermissionError, match="limited"):
        coord.delegate_task(parent.task_id, task_type="scheduling", objective="no")
    coord.close()


def test_backup_restore_retention_and_registry(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    store = ControlStore(str(workspace), state_root)
    lane = store.ensure_lane("lane", model="m")
    lane.config["api_key"] = "must-not-export"
    store.upsert_lane(lane)
    old = store.backup_root / "2020-01-01.sqlite3"
    store.backup_root.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"old")
    backup = store.backup_daily(
        retention_days=2,
        now=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    assert backup.exists()
    assert not old.exists()

    store.ensure_lane("later")
    assert store.get_lane("later") is not None
    store.restore_backup(backup)
    assert store.get_lane("later") is None

    registry = store.export_lane_registry()
    payload = json.loads(registry.read_text(encoding="utf-8"))
    assert payload["workspace_hash"]
    assert str(workspace.resolve()) not in registry.read_text(encoding="utf-8")
    assert "must-not-export" not in registry.read_text(encoding="utf-8")
    store.close()


def test_concurrent_lane_upserts_keep_latest_registry(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = ControlStore(str(workspace), tmp_path / "state")
    count = 24

    def upsert_and_export(index: int) -> tuple[str, Path]:
        key = f"lane-{index:02d}"
        lane = store.ensure_lane(key)
        lane.owner = f"owner-{index}"
        store.upsert_lane(lane)
        path = store.export_lane_registry()
        return key, path

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(upsert_and_export, index) for index in range(count)]
        keys = {future.result()[0] for future in as_completed(futures)}
    assert keys == {f"lane-{index:02d}" for index in range(count)}
    payload = json.loads(store.registry_path.read_text(encoding="utf-8"))
    exported = {lane["lane_key"] for lane in payload["lanes"]}
    assert exported == keys
    leftovers = list(store.registry_path.parent.glob("*.tmp"))
    assert leftovers == []
    store.close()


@pytest.mark.asyncio
async def test_metrics_locks_and_dashboard_coverage(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    coord = coordinator(workspace, tmp_path / "state")
    task = coord.submit_task(
        lane_key="lane",
        objective="write",
        permissions=Permissions(write_files=True),
        artifacts=["model.xlsx"],
        metadata={"stale_source": True},
    )
    paused = await coord.process()
    assert paused[0].status == TaskStatus.AWAITING_APPROVAL
    assert coord.store.list_active_claims() == []
    approval_id = paused[0].metadata["pending_approval_id"]
    coord.approve(approval_id)
    completed = await coord.process()
    assert completed[0].status == TaskStatus.COMPLETED
    assert coord.store.list_active_claims() == []

    names = {metric["name"] for metric in coord.store.list_metrics()}
    assert {
        "approval_latency_seconds",
        "stale_source_incident",
        "task_throughput",
    } <= names

    coord.store.dead_letter_message(
        coord.inbox_send(target="lane", objective="message").message_id,
        "orphan",
    )
    output = render_dashboard(coord.snapshot(), tmp_path / "dashboard.html")
    content = output.read_text(encoding="utf-8")
    assert "unverified reply" in content
    for label in (
        "Queued work",
        "Active runs",
        "Pending Approvals",
        "Health",
        "Artifact Claims",
        "Failures and Dead Letters",
        "Messages and Dead Letters",
        "Metrics",
        "Prior Agents",
    ):
        assert label in content
    await coord.aclose()


@pytest.mark.asyncio
async def test_cli_selects_sdk_only_for_worker_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    connected: list[str] = []
    fake_sdk = FakeRuntime()

    async def fake_connect(
        cls: type[CursorSDKRuntime],
        workspace: str,
        **kwargs: Any,
    ) -> FakeRuntime:
        connected.append(workspace)
        return fake_sdk

    monkeypatch.setattr(CursorSDKRuntime, "connect", classmethod(fake_connect))
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    common = {
        "workspace": str(workspace),
        "state_root": str(tmp_path / "state"),
        "runtime": "sdk",
        "mode": "supervised",
        "model": "model",
        "api_key_env": "CURSOR_API_KEY",
        "config": None,
    }
    status_args = argparse.Namespace(command="status", **common)
    coord = await cli._coordinator(status_args)
    assert isinstance(coord.runtime, FakeRuntime)
    assert connected == []
    await coord.aclose()

    process_args = argparse.Namespace(command="process", **common)
    coord = await cli._coordinator(process_args)
    assert coord.runtime is fake_sdk
    assert connected == [str(workspace)]
    await coord.aclose()


@pytest.mark.asyncio
async def test_cli_requires_api_key_before_sdk_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    args = argparse.Namespace(
        command="process",
        workspace=str(workspace),
        state_root=str(tmp_path / "state"),
        runtime="sdk",
        mode="read-only",
        model="model",
        api_key_env="CURSOR_API_KEY",
        config=None,
    )
    with pytest.raises(RuntimeError, match="CURSOR_API_KEY is required"):
        await cli._coordinator(args)
