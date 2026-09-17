from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from orchestrator import cli
from orchestrator.coordinator import Coordinator
from orchestrator.dashboard import render_dashboard
from orchestrator.models import (
    FailureKind,
    MessageStatus,
    Permissions,
    RunOutcome,
    TaskStatus,
    utcnow_iso,
)
from orchestrator.runtime import AgentBusyError, FakeRuntime, StartupError
from orchestrator.service import WorkspaceServiceLock, serve
from orchestrator.state import ControlStore


def make_coordinator(
    workspace: Path,
    state_root: Path,
    runtime: FakeRuntime | None = None,
    *,
    mode: str = "supervised",
) -> Coordinator:
    return Coordinator(
        str(workspace),
        runtime or FakeRuntime(),
        state_root=state_root,
        mode=mode,
    )


def test_restart_recovery_only_counts_interrupted_tasks(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    first = make_coordinator(workspace, state_root)
    task = first.submit_task(
        lane_key="Lane A",
        objective="interrupted",
        artifacts=["draft.md"],
    )
    task.status = TaskStatus.RUNNING
    task.run_id = "run-interrupted"
    task.metadata["run_owner"] = "dead-process"
    first.store.save_task(task)
    first.locks.acquire(
        "draft.md",
        "Lane A",
        "dead-process",
        task_id=task.task_id,
    )
    first.close()

    recovered = make_coordinator(workspace, state_root)
    restored = recovered.store.get_task(task.task_id)
    assert restored is not None
    assert restored.status == TaskStatus.QUEUED
    assert restored.run_id is None
    assert restored.metadata["interrupted_run_id"] == "run-interrupted"
    assert restored.metadata["restart_recovery_count"] == 1
    assert recovered.store.list_active_claims() == []
    recovery_metrics = recovered.store.list_metrics("restart_recovery")
    assert len(recovery_metrics) == 1
    assert recovery_metrics[0]["value"] == 1
    assert any(
        event["event_type"] == "task.restart_recovered"
        for event in recovered.store.list_events()
    )
    recovered.close()

    ordinary_open = make_coordinator(workspace, state_root)
    assert len(ordinary_open.store.list_metrics("restart_recovery")) == 1
    ordinary_open.close()


def test_ordinary_cli_open_does_not_record_restart_recovery(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    common = [
        "--workspace",
        str(workspace),
        "--state-root",
        str(state_root),
    ]
    assert cli.main(
        [
            *common,
            "submit",
            "--lane",
            "Lane A",
            "--objective",
            "ordinary submit",
        ]
    ) == 0
    task_id = json.loads(capsys.readouterr().out)["task_id"]
    assert cli.main([*common, "status", "--task-id", task_id]) == 0
    capsys.readouterr()
    store = ControlStore(str(workspace), state_root)
    assert store.list_metrics("restart_recovery") == []
    store.close()


def test_live_service_owned_run_is_not_recovered(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    first = make_coordinator(workspace, state_root)
    task = first.submit_task(lane_key="Lane A", objective="active")
    lock = WorkspaceServiceLock(first.workspace, first.store.state_root)
    lock.acquire()
    task.status = TaskStatus.RUNNING
    task.metadata["run_owner"] = lock.token
    first.store.save_task(task)
    first.close()
    try:
        observer = make_coordinator(workspace, state_root)
        active = observer.store.get_task(task.task_id)
        assert active is not None
        assert active.status == TaskStatus.RUNNING
        assert observer.store.list_metrics("restart_recovery") == []
        observer.close()
    finally:
        lock.release()


@pytest.mark.asyncio
async def test_structured_agent_message_routes_lane_a_to_lane_b(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime()
    response = {
        "summary": "Lane A extraction complete",
        "status": "completed",
        "evidence": ["brief.md"],
        "proposed_messages": [
            {
                "target": "Lane B",
                "objective": "Review Lane A findings",
                "evidence": ["brief.md"],
                "reply_to": "review-thread",
            }
        ],
    }
    runtime.run_results["task-a"] = RunOutcome(
        agent_id="configured",
        run_id="configured",
        status="finished",
        result_text=json.dumps(response),
    )
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    coord.store.ensure_lane("Lane B")
    task_a = coord.submit_task(
        lane_key="Lane A",
        objective="Extract",
        idempotency_key="task-a",
    )

    first_cycle = await coord.process()
    assert first_cycle[0].status == TaskStatus.COMPLETED
    stored_a = coord.store.get_task(task_a.task_id)
    assert stored_a is not None
    assert stored_a.metadata["agent_response"]["summary"] == response["summary"]
    assert "brief.md" in stored_a.evidence
    proposed = coord.store.list_messages(status=MessageStatus.PENDING)
    assert len(proposed) == 1
    assert proposed[0].sender == "Lane A"

    # An agent proposal is held, not executed: without promotion an agent
    # would be scheduling the next agent.
    held_cycle = await coord.process()
    assert held_cycle == []
    assert coord.last_coordination_held == 1
    assert coord.store.get_message(proposed[0].message_id).status == MessageStatus.PENDING

    coord.promote_message(proposed[0].message_id)
    second_cycle = await coord.process()
    assert len(second_cycle) == 1
    task_b = second_cycle[0]
    assert task_b.lane_key == "Lane B"
    assert task_b.status == TaskStatus.COMPLETED
    assert task_b.sender == "Lane A"
    assert task_b.reply_to == "review-thread"
    assert task_b.metadata["source_message_id"] == proposed[0].message_id
    delivered = coord.store.get_message(proposed[0].message_id)
    assert delivered is not None
    assert delivered.status == MessageStatus.DELIVERED
    assert stored_a.agent_id != task_b.agent_id
    assert coord.store.get_lane("Lane A").current_agent_id == stored_a.agent_id
    assert coord.store.get_lane("Lane B").current_agent_id == task_b.agent_id
    await coord.aclose()


@pytest.mark.asyncio
async def test_agent_proposals_reject_unknown_cross_workspace_and_write(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    other = tmp_path / "other"
    workspace.mkdir()
    other.mkdir()
    runtime = FakeRuntime()
    response = {
        "summary": "Unsafe proposals attempted",
        "status": "completed",
        "evidence": [],
        "proposed_messages": [
            {"target": "Missing Lane", "objective": "unknown"},
            {
                "target": "Lane B",
                "objective": "cross",
                "workspace": str(other),
            },
            {
                "target": "Lane B",
                "objective": "write",
                "permissions": {"write_files": True},
            },
        ],
    }
    runtime.run_results["unsafe"] = RunOutcome(
        agent_id="configured",
        run_id="configured",
        status="finished",
        result_text=json.dumps(response),
    )
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    coord.store.ensure_lane("Lane B")
    coord.submit_task(
        lane_key="Lane A",
        objective="Attempt messages",
        idempotency_key="unsafe",
    )
    await coord.process()

    rejected = coord.store.list_messages(status=MessageStatus.DEAD_LETTER)
    assert len(rejected) == 3
    reasons = {item.metadata["dead_letter_reason"] for item in rejected}
    assert reasons == {
        "unknown_target_lane",
        "cross_workspace_route",
        "sensitive_permissions",
    }
    assert coord.store.get_lane("Missing Lane") is None
    assert coord.store.list_messages(status=MessageStatus.PENDING) == []
    await coord.aclose()


@pytest.mark.asyncio
async def test_invalid_agent_output_is_summary_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime()
    runtime.run_results["plain"] = RunOutcome(
        agent_id="configured",
        run_id="configured",
        status="finished",
        result_text="plain non-json result",
    )
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    task = coord.submit_task(
        lane_key="Lane A",
        objective="Plain output",
        idempotency_key="plain",
    )
    await coord.process()
    stored = coord.store.get_task(task.task_id)
    assert stored.metadata["agent_response"] == {
        "structured": False,
        "summary": "plain non-json result",
    }
    assert coord.store.list_messages() == []
    await coord.aclose()


@pytest.mark.asyncio
async def test_busy_agent_rotates_lane_and_retries_once(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime()
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    _, wedged_agent_id, _ = await coord.agents.create("Lane A", objective="seed")
    runtime.run_results[wedged_agent_id] = AgentBusyError(
        f"Agent {wedged_agent_id} already has active run"
    )
    task = coord.submit_task(
        lane_key="Lane A",
        objective="Count lines",
        idempotency_key="busy",
    )
    processed = await coord.process()

    assert processed[0].task_id == task.task_id
    assert processed[0].status == TaskStatus.COMPLETED
    assert processed[0].agent_id != wedged_agent_id
    lane = coord.store.get_lane("Lane A")
    assert wedged_agent_id in lane.prior_agent_ids
    assert wedged_agent_id in runtime.disposed
    await coord.aclose()


@pytest.mark.asyncio
async def test_busy_agent_after_rotation_fails_the_task(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime()
    runtime.run_results["*"] = AgentBusyError("already has active run")
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    task = coord.submit_task(
        lane_key="Lane A",
        objective="Count lines",
        idempotency_key="always-busy",
    )
    processed = await coord.process()

    assert processed[0].task_id == task.task_id
    assert processed[0].status == TaskStatus.FAILED
    assert processed[0].failure_kind == FailureKind.STARTUP
    await coord.aclose()


@dataclass
class ResumeFailingRuntime(FakeRuntime):
    """Creating an agent works; resuming an existing one always times out."""

    resume_attempts: int = 0

    async def resume_agent(self, agent_id: str, config: Any, context: Any) -> str:
        self.resume_attempts += 1
        raise StartupError("Bridge request timed out: ReadTimeout", retryable=True)


@dataclass
class FlakyResumeRuntime(FakeRuntime):
    """Resume fails once, then works — a transient bridge blip."""

    resume_attempts: int = 0

    async def resume_agent(self, agent_id: str, config: Any, context: Any) -> str:
        self.resume_attempts += 1
        if self.resume_attempts == 1:
            raise StartupError("Bridge request timed out: ReadTimeout", retryable=True)
        return await super().resume_agent(agent_id, config, context)


@pytest.mark.asyncio
async def test_first_resume_failure_counts_without_rotating(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = ResumeFailingRuntime()
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    _, wedged_agent_id, _ = await coord.agents.create("Lane A", objective="seed")
    task = coord.submit_task(
        lane_key="Lane A",
        objective="Count lines",
        idempotency_key="resume-1",
    )
    processed = await coord.process()

    assert processed[0].task_id == task.task_id
    assert processed[0].status == TaskStatus.FAILED
    assert processed[0].failure_kind == FailureKind.STARTUP
    lane = coord.store.get_lane("Lane A")
    assert lane.current_agent_id == wedged_agent_id
    assert lane.prior_agent_ids == []
    assert lane.config["rotation"]["startup_failure_count"] == 1
    await coord.aclose()


@pytest.mark.asyncio
async def test_second_resume_failure_rotates_to_a_fresh_agent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = ResumeFailingRuntime()
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    _, wedged_agent_id, _ = await coord.agents.create("Lane A", objective="seed")
    coord.submit_task(
        lane_key="Lane A",
        objective="Count lines",
        idempotency_key="resume-1",
    )
    await coord.process()
    coord.submit_task(
        lane_key="Lane A",
        objective="Count lines again",
        idempotency_key="resume-2",
    )
    processed = await coord.process()

    assert processed[0].status == TaskStatus.COMPLETED
    assert processed[0].agent_id != wedged_agent_id
    assert runtime.resume_attempts == 2
    lane = coord.store.get_lane("Lane A")
    assert wedged_agent_id in lane.prior_agent_ids
    assert "startup_failure_count" not in lane.config["rotation"]
    await coord.aclose()


@pytest.mark.asyncio
async def test_successful_resume_clears_the_startup_failure_count(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FlakyResumeRuntime()
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    _, agent_id, _ = await coord.agents.create("Lane A", objective="seed")
    coord.submit_task(
        lane_key="Lane A",
        objective="Count lines",
        idempotency_key="flaky-1",
    )
    await coord.process()
    coord.submit_task(
        lane_key="Lane A",
        objective="Count lines again",
        idempotency_key="flaky-2",
    )
    processed = await coord.process()

    assert processed[0].status == TaskStatus.COMPLETED
    assert processed[0].agent_id == agent_id
    lane = coord.store.get_lane("Lane A")
    assert lane.prior_agent_ids == []
    assert "startup_failure_count" not in lane.config["rotation"]
    await coord.aclose()


@pytest.mark.asyncio
async def test_startup_failure_count_survives_restart(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    first = make_coordinator(workspace, state_root, ResumeFailingRuntime())
    _, wedged_agent_id, _ = await first.agents.create("Lane A", objective="seed")
    first.submit_task(
        lane_key="Lane A",
        objective="Count lines",
        idempotency_key="resume-1",
    )
    await first.process()
    first.close()

    second = make_coordinator(workspace, state_root, ResumeFailingRuntime())
    second.submit_task(
        lane_key="Lane A",
        objective="Count lines again",
        idempotency_key="resume-2",
    )
    processed = await second.process()

    assert processed[0].status == TaskStatus.COMPLETED
    assert processed[0].agent_id != wedged_agent_id
    lane = second.store.get_lane("Lane A")
    assert wedged_agent_id in lane.prior_agent_ids
    await second.aclose()


@pytest.mark.asyncio
async def test_fenced_agent_json_is_structured(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime()
    response = {
        "summary": "5",
        "status": "completed",
        "evidence": ["README.md"],
        "proposed_messages": [],
    }
    runtime.run_results["fenced"] = RunOutcome(
        agent_id="configured",
        run_id="configured",
        status="finished",
        result_text="```json\n%s\n```" % json.dumps(response, indent=2),
    )
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    task = coord.submit_task(
        lane_key="Lane A",
        objective="Count lines",
        idempotency_key="fenced",
    )
    await coord.process()
    stored = coord.store.get_task(task.task_id)
    assert stored.metadata["agent_response"]["structured"] is True
    assert stored.metadata["agent_response"]["summary"] == "5"
    assert "README.md" in stored.evidence
    await coord.aclose()


@pytest.mark.asyncio
async def test_message_restart_routing_is_idempotent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    first = make_coordinator(workspace, state_root)
    first.store.ensure_lane("Lane B")
    message = first.inbox_send(
        target="Lane B",
        objective="Resume routing",
        sender="Lane A",
        executable=True,
        evidence=["evidence.md"],
    )
    existing = first.submit_task(
        lane_key="Lane B",
        objective=message.objective,
        sender=message.sender,
        target="message",
        permissions=message.permissions,
        idempotency_key=f"message:{message.message_id}",
        reply_to=message.reply_to,
        evidence=message.evidence,
        metadata={"source_message_id": message.message_id},
    )
    first.close()

    restarted = make_coordinator(workspace, state_root)
    routed = restarted.route_pending_messages()
    assert routed[0].task_id == existing.task_id
    assert len(
        [
            task
            for task in restarted.store.list_tasks()
            if task.idempotency_key == f"message:{message.message_id}"
        ]
    ) == 1
    assert restarted.store.get_message(message.message_id).status == MessageStatus.ROUTED
    await restarted.process()
    assert restarted.store.get_message(message.message_id).status == MessageStatus.DELIVERED
    await restarted.aclose()


@pytest.mark.asyncio
async def test_coordination_message_is_held_not_executed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime()
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    coord.store.ensure_lane("Lane B")
    message = coord.inbox_send(
        target="Lane B",
        objective="Rotate now; your successor picks up the model edits",
        sender="Brain",
    )

    processed = await coord.process()

    assert processed == []
    assert coord.last_coordination_held == 1
    assert coord.store.get_message(message.message_id).status == MessageStatus.PENDING
    assert coord.store.list_tasks() == []
    assert runtime.created == []
    await coord.aclose()


@pytest.mark.asyncio
async def test_legacy_message_without_the_flag_is_held(tmp_path: Path) -> None:
    """Mail written before the flag existed must read as coordination-only."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    coord = make_coordinator(workspace, tmp_path / "state")
    coord.store.ensure_lane("Lane B")
    message = coord.inbox_send(target="Lane B", objective="Pre-flag message")
    message.metadata.pop("executable")
    coord.store.save_message(message)

    processed = await coord.process()

    assert processed == []
    assert coord.store.get_message(message.message_id).status == MessageStatus.PENDING
    await coord.aclose()


@pytest.mark.asyncio
async def test_promoted_message_routes_and_acknowledge_closes_mail(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    coord = make_coordinator(workspace, tmp_path / "state", FakeRuntime())
    coord.store.ensure_lane("Lane B")
    held = coord.inbox_send(target="Lane B", objective="Bounded read-only check")
    acknowledged = coord.inbox_send(target="Lane B", objective="Already actioned")

    coord.acknowledge_message(acknowledged.message_id, actor="Luis", note="done in lane")
    coord.promote_message(held.message_id)
    processed = await coord.process()

    assert len(processed) == 1
    assert processed[0].metadata["source_message_id"] == held.message_id
    assert coord.store.get_message(held.message_id).status == MessageStatus.DELIVERED
    closed = coord.store.get_message(acknowledged.message_id)
    assert closed.status == MessageStatus.DELIVERED
    assert closed.metadata["acknowledged_by"] == "Luis"
    with pytest.raises(PermissionError):
        coord.promote_message(acknowledged.message_id)
    await coord.aclose()


@pytest.mark.asyncio
async def test_dashboard_marks_dispatched_work_and_reply_quality(
    tmp_path: Path,
) -> None:
    from orchestrator.dashboard import render_dashboard

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime()
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    coord.store.ensure_lane("Lane B")
    message = coord.inbox_send(
        target="Lane B",
        objective="Report the line count of README.md",
        evidence=["README.md"],
        executable=True,
    )
    runtime.run_results[f"message:{message.message_id}"] = RunOutcome(
        agent_id="configured",
        run_id="configured",
        status="finished",
        result_text=json.dumps(
            {
                "summary": "5",
                "status": "completed",
                "evidence": ["README.md"],
                "proposed_messages": [],
            }
        ),
    )
    await coord.process()

    output = render_dashboard(coord.snapshot(), tmp_path / "dashboard.html")
    content = output.read_text(encoding="utf-8")
    assert "dispatched" in content
    assert "governed reply" in content
    assert "unverified reply" not in content
    assert "README.md" in content
    await coord.aclose()


@pytest.mark.asyncio
async def test_console_can_promote_and_acknowledge_mail(tmp_path: Path) -> None:
    from orchestrator.dashboard import render_dashboard_html
    from orchestrator.webapp import ConsoleApplication

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    coord = make_coordinator(workspace, tmp_path / "state", FakeRuntime())
    coord.store.ensure_lane("Lane B")
    held = coord.inbox_send(target="Lane B", objective="Bounded check")
    note = coord.inbox_send(target="Lane B", objective="Rotate now")
    app = ConsoleApplication(coord, operator="luis")

    html = render_dashboard_html(coord.snapshot(), console_token="t")
    assert "coordination" in html
    assert "promote_message" in html

    await app.dispatch("promote_message", {"message_id": held.message_id})
    await app.dispatch("acknowledge_message", {"message_id": note.message_id})

    assert coord.store.get_message(held.message_id).executable is True
    closed = coord.store.get_message(note.message_id)
    assert closed.status == MessageStatus.DELIVERED
    assert closed.metadata["acknowledged_by"] == "luis"

    processed = await coord.process()
    assert [t.metadata["source_message_id"] for t in processed] == [held.message_id]
    await coord.aclose()


def test_workspace_menu_marks_active_and_flags_approvals(tmp_path: Path) -> None:
    from orchestrator.dashboard import render_dashboard_html
    from orchestrator.state import list_known_workspaces

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    coord = make_coordinator(workspace, state_root)
    coord.submit_task(lane_key="Lane A", objective="queued work")
    snapshot = coord.snapshot()

    discovered = list_known_workspaces(state_root)
    assert [entry["workspace"] for entry in discovered] == [str(workspace.resolve())]
    assert discovered[0]["queued"] == 1
    assert discovered[0]["live"] is False

    other = dict(discovered[0])
    other["workspace"] = str(tmp_path / "other client")
    other["awaiting_approval"] = 3
    html = render_dashboard_html(
        snapshot, console_token="t", workspaces=discovered + [other]
    )
    assert '<ul class="workspace-list">' in html
    assert ">active<" in html
    assert "3 to approve" in html

    # Falls back to a plain label when discovery returns nothing.
    assert '<ul class="workspace-list">' not in render_dashboard_html(
        snapshot, console_token="t"
    )
    coord.close()


@pytest.mark.asyncio
async def test_unknown_typed_message_is_dead_lettered(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    coord = make_coordinator(workspace, tmp_path / "state")
    message = coord.inbox_send(target="Unknown", objective="Do not invent lane")
    assert coord.store.get_lane("Unknown") is None
    await coord.process()
    stored = coord.store.get_message(message.message_id)
    assert stored.status == MessageStatus.DEAD_LETTER
    assert stored.metadata["dead_letter_reason"] == "unknown_target_lane"
    assert coord.store.get_lane("Unknown") is None
    await coord.aclose()


@pytest.mark.asyncio
async def test_failed_message_task_dead_letters_source(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime()
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    coord.store.ensure_lane("Lane B")
    message = coord.inbox_send(target="Lane B", objective="Fail safely", executable=True)
    runtime.run_results[f"message:{message.message_id}"] = RunOutcome(
        agent_id="configured",
        run_id="configured",
        status="error",
        error_message="agent run failed",
    )
    result = await coord.process()
    assert result[0].status == TaskStatus.FAILED
    stored = coord.store.get_message(message.message_id)
    assert stored.status == MessageStatus.DEAD_LETTER
    assert stored.metadata["dead_letter_reason"] == "agent run failed"
    await coord.aclose()


@pytest.mark.asyncio
async def test_shadow_service_counts_unique_proposals(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    coord = make_coordinator(
        workspace,
        tmp_path / "state",
        mode="shadow",
    )
    for index in range(3):
        coord.submit_task(lane_key="Lane", objective=f"Task {index}")
    dashboard = tmp_path / "dashboard.html"
    result = await serve(
        coord,
        poll_interval=0.01,
        dashboard_refresh=0,
        dashboard_output=dashboard,
        max_cycles=2,
    )
    assert result["processed_tasks"] == 0
    assert result["proposed_routes"] == 3
    heartbeat = coord.store.get_service_heartbeat()
    assert heartbeat["processed_tasks"] == 0
    assert heartbeat["proposed_routes"] == 3
    content = dashboard.read_text(encoding="utf-8")
    assert "Queued shadow proposals" in content
    await coord.aclose()
