from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator.coordinator import Coordinator
from orchestrator.dashboard import render_dashboard
from orchestrator.models import FailureKind, Permissions, RunOutcome, TaskStatus
from orchestrator.policy import PolicyRegistry
from orchestrator.runtime import FakeRuntime, StartupError
from orchestrator.state import ControlStore, workspace_db_path, workspace_hash


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def workspace_a(tmp_path: Path) -> Path:
    path = tmp_path / "workspace_a"
    path.mkdir()
    return path


@pytest.fixture
def workspace_b(tmp_path: Path) -> Path:
    path = tmp_path / "workspace_b"
    path.mkdir()
    return path


def make_coordinator(workspace: Path, state_root: Path, runtime: FakeRuntime | None = None) -> Coordinator:
    return Coordinator(str(workspace), runtime or FakeRuntime(), state_root=state_root)


def test_workspace_isolation(state_root: Path, workspace_a: Path, workspace_b: Path) -> None:
    runtime_a = FakeRuntime()
    runtime_b = FakeRuntime()
    coord_a = make_coordinator(workspace_a, state_root, runtime_a)
    coord_b = make_coordinator(workspace_b, state_root, runtime_b)

    task_a = coord_a.submit_task(lane_key="lane-1", objective="task in A", idempotency_key="same-key")
    task_b = coord_b.submit_task(lane_key="lane-1", objective="task in B", idempotency_key="same-key")

    assert task_a.task_id != task_b.task_id
    assert workspace_db_path(str(workspace_a), state_root) != workspace_db_path(str(workspace_b), state_root)
    assert coord_a.get_status(task_a.task_id) is not None
    assert coord_a.get_status(task_b.task_id) is None
    assert coord_b.get_status(task_b.task_id) is not None

    coord_a.close()
    coord_b.close()


@pytest.mark.asyncio
async def test_orphan_expiry_and_dead_letter(state_root: Path, workspace_a: Path) -> None:
    coord = make_coordinator(workspace_a, state_root)
    expired_task = coord.submit_task(
        lane_key="ops",
        objective="expire me",
        ttl_seconds=1,
    )
    message = coord.inbox_send(target="ops", objective="orphan", ttl_seconds=1)
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    coord.store.connect().execute(
        "UPDATE tasks SET expires_at = ? WHERE task_id = ?",
        (past.isoformat(), expired_task.task_id),
    )
    coord.store.connect().execute(
        "UPDATE messages SET expires_at = ? WHERE message_id = ?",
        (past.isoformat(), message.message_id),
    )
    coord.store.connect().commit()

    result = coord.recover()
    assert result["expired"]["tasks"] == 1
    assert result["expired"]["messages"] == 1
    assert coord.get_status(expired_task.task_id).status == TaskStatus.EXPIRED

    failed = coord.submit_task(lane_key="ops", objective="fail")
    failed.status = TaskStatus.FAILED
    failed.metadata["retry_exhausted"] = True
    failed.error_message = "boom"
    coord.store.save_task(failed)
    result = coord.recover()
    assert result["dead_lettered"] == 1
    assert coord.get_status(failed.task_id).status == TaskStatus.DEAD_LETTER
    coord.close()


def test_lock_exclusivity_and_stale_recovery(state_root: Path, workspace_a: Path) -> None:
    coord = make_coordinator(workspace_a, state_root)
    coord.locks.acquire("shared/model.xlsx", "lane-a", "tester", write_capable=True)
    with pytest.raises(PermissionError):
        coord.locks.acquire("shared/model.xlsx", "lane-b", "tester", write_capable=True)

    claim = coord.store.get_active_write_claim("shared/model.xlsx")
    assert claim is not None
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    claim.expires_at = past.isoformat()
    coord.store.save_claim(claim)
    recovered = coord.locks.recover_stale()
    assert len(recovered) == 1
    coord.locks.acquire("shared/model.xlsx", "lane-b", "tester", write_capable=True)
    coord.close()


@pytest.mark.asyncio
async def test_supervised_approval_flow(state_root: Path, workspace_a: Path) -> None:
    coord = make_coordinator(workspace_a, state_root)
    task = coord.submit_task(
        lane_key="write-lane",
        objective="edit workbook",
        permissions=Permissions(write_files=True),
        artifacts=["shared/model.xlsx"],
    )
    processed = await coord.process(max_tasks=1)
    assert processed[0].status == TaskStatus.AWAITING_APPROVAL
    approval_id = processed[0].metadata["pending_approval_id"]
    coord.approve(approval_id)
    completed = await coord.process(max_tasks=1)
    assert completed[0].status == TaskStatus.COMPLETED
    coord.close()


@pytest.mark.asyncio
async def test_three_tasks_two_lanes(state_root: Path, workspace_a: Path) -> None:
    runtime = FakeRuntime()
    coord = make_coordinator(workspace_a, state_root, runtime)
    tasks = [
        coord.submit_task(lane_key="lane-a", objective="a1", idempotency_key="a1"),
        coord.submit_task(lane_key="lane-a", objective="a2", idempotency_key="a2"),
        coord.submit_task(lane_key="lane-b", objective="b1", idempotency_key="b1"),
    ]
    completed = await coord.process(max_tasks=10)
    assert len(completed) == 3
    assert all(t.status == TaskStatus.COMPLETED for t in completed)
    assert len(runtime.created) >= 2
    coord.close()


@pytest.mark.asyncio
async def test_fresh_agent_rotation(state_root: Path, workspace_a: Path) -> None:
    runtime = FakeRuntime()
    coord = make_coordinator(workspace_a, state_root, runtime)
    lane, first_agent, _ = await coord.agents.create("rotate-lane", objective="initial")
    result = await coord.rotate_lane("rotate-lane", objective="rotated objective")
    lane = coord.store.get_lane("rotate-lane")
    assert lane is not None
    assert lane.current_agent_id != first_agent
    assert first_agent in lane.prior_agent_ids
    assert first_agent in runtime.disposed
    assert result["agent_id"] == lane.current_agent_id
    coord.close()


@pytest.mark.asyncio
async def test_db_reopen_restart_recovery(state_root: Path, workspace_a: Path) -> None:
    runtime = FakeRuntime()
    coord = make_coordinator(workspace_a, state_root, runtime)
    task = coord.submit_task(lane_key="recover-lane", objective="survive restart", idempotency_key="restart-1")
    db_path = coord.store.db_path
    coord.store.close()

    coord2 = make_coordinator(workspace_a, state_root, runtime)
    assert coord2.store.db_path == db_path
    restored = coord2.get_status(task.task_id)
    assert restored is not None
    assert restored.objective == "survive restart"
    completed = await coord2.process(max_tasks=1)
    assert completed[0].status == TaskStatus.COMPLETED
    coord2.close()


def test_idempotency_key(state_root: Path, workspace_a: Path) -> None:
    coord = make_coordinator(workspace_a, state_root)
    first = coord.submit_task(lane_key="lane", objective="once", idempotency_key="dup")
    second = coord.submit_task(lane_key="lane", objective="once", idempotency_key="dup")
    assert first.task_id == second.task_id
    coord.close()


@pytest.mark.asyncio
async def test_startup_vs_run_failure(state_root: Path, workspace_a: Path) -> None:
    runtime = FakeRuntime()
    runtime.run_results["startup"] = StartupError("auth failed", retryable=True)
    coord = make_coordinator(workspace_a, state_root, runtime)
    startup_task = coord.submit_task(
        lane_key="fail-lane",
        objective="startup",
        idempotency_key="startup",
    )
    done = await coord.process(max_tasks=1)
    assert done[0].failure_kind == FailureKind.STARTUP

    runtime.run_results.clear()
    runtime.run_results["run"] = RunOutcome(
        agent_id="x",
        run_id="r1",
        status="error",
        failure_kind=FailureKind.RUN,
        error_message="tool failed",
    )
    run_task = coord.submit_task(
        lane_key="fail-lane",
        objective="run",
        idempotency_key="run",
    )
    done = await coord.process(max_tasks=1)
    assert done[0].failure_kind == FailureKind.RUN
    coord.close()


def test_dashboard_generation(state_root: Path, workspace_a: Path, tmp_path: Path) -> None:
    coord = make_coordinator(workspace_a, state_root)
    coord.submit_task(lane_key="dash-lane", objective="show me")
    output = tmp_path / "dashboard.html"
    path = render_dashboard(coord.snapshot(), output)
    content = path.read_text(encoding="utf-8")
    assert "Local Agent Orchestrator" in content
    assert "dash-lane" in content
    assert "__ORCH_SNAPSHOT__" in content
    assert "Lane Control Grid" in content
    assert "Inspector" in content
    assert "https://" not in content.split("</style>")[0]
    coord.close()


def test_dashboard_does_not_attribute_events_across_lanes(
    state_root: Path, workspace_a: Path, tmp_path: Path
) -> None:
    coord = make_coordinator(workspace_a, state_root)
    coord.submit_task(lane_key="busy-lane", objective="has work")
    coord.store.ensure_lane("quiet-lane")
    content = render_dashboard(coord.snapshot(), tmp_path / "dashboard.html").read_text(
        encoding="utf-8"
    )
    quiet_panel = content.split(
        'class="inspector-panel" data-lane="quiet-lane"'
    )[1].split("</div></div>")[0]
    assert "No events for this lane" in quiet_panel
    assert "task.submitted" not in quiet_panel
    coord.close()


def test_dashboard_escapes_untrusted_task_text(state_root: Path, workspace_a: Path, tmp_path: Path) -> None:
    coord = make_coordinator(workspace_a, state_root)
    payload = "<script>alert(1)</script>"
    coord.submit_task(lane_key="xss-lane", objective=payload)
    content = render_dashboard(coord.snapshot(), tmp_path / "dashboard.html").read_text(
        encoding="utf-8"
    )
    assert payload not in content
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content
    assert "\\u003cscript\\u003e" in content
    coord.close()


def test_context_envelope_builder(state_root: Path, workspace_a: Path) -> None:
    coord = make_coordinator(workspace_a, state_root)
    lane = coord.store.ensure_lane("ctx-lane")
    task = coord.submit_task(lane_key="ctx-lane", objective="build envelope", spec_id="session_lifecycle")
    envelope = coord.context_builder.build(lane, task)
    assert envelope.workspace == str(workspace_a.resolve())
    assert envelope.spec_id == "session_lifecycle"
    assert "client_isolation" in envelope.policy_ids
    errors = coord.context_builder.validate(envelope)
    assert errors == []
    coord.close()


def test_policy_registry_loads() -> None:
    registry = PolicyRegistry()
    assert "client_isolation" in registry.list_policy_ids()


def test_resume_reapplies_config(state_root: Path, workspace_a: Path) -> None:
    runtime = FakeRuntime()
    coord = make_coordinator(workspace_a, state_root, runtime)
    lane = coord.store.ensure_lane("cfg-lane", model="composer-2.5")
    lane.config = {"cwd": str(workspace_a)}
    coord.store.upsert_lane(lane)
    import asyncio

    async def _run() -> None:
        _, agent_id, _ = await coord.agents.create("cfg-lane", objective="first")
        _, resumed_id, _ = await coord.agents.resume("cfg-lane", objective="second")
        assert agent_id == resumed_id
        assert runtime.resumed == [agent_id]
        state = runtime.agents[agent_id]
        assert state.config.model == "composer-2.5"

    asyncio.run(_run())
    coord.close()
