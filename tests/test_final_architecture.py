from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from orchestrator import cli
from orchestrator.bootstrap import bootstrap_handovers
from orchestrator.coordinator import Coordinator
from orchestrator.legacy import audit_or_import_legacy_inbox
from orchestrator.models import Permissions, TaskStatus, normalize_lane_key
from orchestrator.runtime import CursorSDKRuntime, FakeRuntime
from orchestrator.service import (
    ServiceAlreadyRunningError,
    WorkspaceServiceLock,
    request_service_stop,
    serve,
    service_status,
)
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


@pytest.mark.asyncio
async def test_governed_prompt_is_complete_and_workspace_isolated(
    tmp_path: Path,
) -> None:
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    state_root = tmp_path / "state"
    runtime_a = FakeRuntime()
    coord_a = make_coordinator(workspace_a, state_root, runtime_a)
    coord_b = make_coordinator(workspace_b, state_root)
    coord_b.submit_task(
        lane_key="lane",
        objective="UNRELATED_WORKSPACE_SECRET",
        evidence=["other-secret-source"],
    )
    task = coord_a.submit_task(
        lane_key="lane",
        objective="Extract directives",
        spec_id="meeting_to_action",
        idempotency_key="prompt-test",
        reply_to="message-123",
        evidence=["transcript.docx", "decision-log.md"],
        artifacts=["brief.md"],
        permissions=Permissions(read=True),
    )
    await coord_a.process()
    agent = next(iter(runtime_a.agents.values()))
    prompt = agent.runs[0]["prompt"]
    payload = json.loads(prompt)

    assert payload["protocol"] == "cursor-local-orchestrator-task/v1"
    assert payload["context_envelope"]["workspace"] == str(workspace_a.resolve())
    assert payload["task"]["task_id"] == task.task_id
    assert payload["task"]["permissions"]["read"] is True
    assert payload["task"]["evidence_pointers"] == [
        "transcript.docx",
        "decision-log.md",
    ]
    assert payload["task"]["artifact_paths"] == ["brief.md"]
    assert payload["task"]["reply_to"] == "message-123"
    spec = payload["execution_spec"]
    assert spec["version"] == "1.0.0"
    assert spec["work_graph"]
    assert spec["decision_rights"]
    assert spec["controls"]
    assert spec["dependencies"]
    assert "approval_required_for" in payload["supervision"]
    assert "UNRELATED_WORKSPACE_SECRET" not in prompt
    assert "other-secret-source" not in prompt
    await coord_a.aclose()
    await coord_b.aclose()


def test_wal_busy_timeout_and_service_lock(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = ControlStore(str(workspace), tmp_path / "state")
    conn = store.connect()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    first = WorkspaceServiceLock(store.workspace, store.state_root)
    second = WorkspaceServiceLock(store.workspace, store.state_root)
    first.acquire()
    with pytest.raises(ServiceAlreadyRunningError):
        second.acquire()
    first.release()
    store.close()


@pytest.mark.asyncio
async def test_service_bounded_cycles_heartbeat_dashboard_and_stop(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime()
    coord = make_coordinator(workspace, tmp_path / "state", runtime)
    coord.submit_task(lane_key="lane", objective="service task")
    dashboard = tmp_path / "dashboard.html"
    result = await serve(
        coord,
        poll_interval=0.01,
        max_tasks=2,
        dashboard_refresh=0,
        dashboard_output=dashboard,
        max_cycles=2,
    )
    assert result == {
        "state": "completed",
        "cycles": 2,
        "processed_tasks": 1,
        "proposed_routes": 0,
    }
    assert dashboard.exists()
    heartbeat = coord.store.get_service_heartbeat()
    assert heartbeat is not None
    assert heartbeat["state"] == "completed"
    assert heartbeat["cycles"] == 2
    assert service_status(coord)["lock_exists"] is False
    await coord.aclose()
    assert runtime.closed is True


@pytest.mark.asyncio
async def test_service_stop_file_shutdown(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    coord = make_coordinator(workspace, tmp_path / "state")
    custom_stop = tmp_path / "service.stop"

    async def request_stop() -> None:
        await asyncio.sleep(0.03)
        request_service_stop(
            coord.workspace,
            coord.store.state_root,
            custom_stop,
        )

    stopper = asyncio.create_task(request_stop())
    result = await serve(
        coord,
        poll_interval=0.01,
        stop_file=custom_stop,
        max_cycles=100,
    )
    await stopper
    assert result["state"] == "stopped"
    assert not custom_stop.exists()
    await coord.aclose()


@pytest.mark.asyncio
async def test_serve_runtime_defaults_to_sdk_except_fake_or_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    connected: list[str] = []

    async def fake_connect(
        cls: type[CursorSDKRuntime],
        workspace: str,
        **kwargs: Any,
    ) -> FakeRuntime:
        connected.append(workspace)
        return FakeRuntime()

    monkeypatch.setattr(CursorSDKRuntime, "connect", classmethod(fake_connect))
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    common = {
        "workspace": str(workspace),
        "state_root": str(tmp_path / "state"),
        "model": "model",
        "api_key_env": "CURSOR_API_KEY",
        "config": None,
        "command": "serve",
    }
    sdk_coord = await cli._coordinator(
        argparse.Namespace(runtime=None, mode="supervised", **common)
    )
    assert connected == [str(workspace)]
    await sdk_coord.aclose()

    fake_coord = await cli._coordinator(
        argparse.Namespace(runtime="fake", mode="supervised", **common)
    )
    assert isinstance(fake_coord.runtime, FakeRuntime)
    await fake_coord.aclose()

    shadow_coord = await cli._coordinator(
        argparse.Namespace(runtime=None, mode="shadow", **common)
    )
    assert isinstance(shadow_coord.runtime, FakeRuntime)
    await shadow_coord.aclose()


def test_bootstrap_only_top_level_active_undated_handovers(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SESSION_HANDOVER_Value_Case.md").write_text(
        "value", encoding="utf-8"
    )
    (workspace / "SESSION_HANDOVER_Brain.md").write_text(
        "# Session Handover — Brain\n\n**Lane:** Brain\n",
        encoding="utf-8",
    )
    (workspace / "SESSION_HANDOVER_Ops_2026-09-02.md").write_text(
        "archive", encoding="utf-8"
    )
    nested = workspace / "archive"
    nested.mkdir()
    (nested / "SESSION_HANDOVER_Nested.md").write_text(
        "nested", encoding="utf-8"
    )
    store = ControlStore(str(workspace), tmp_path / "state")
    result = bootstrap_handovers(store, workspace)
    assert [item["lane_key"] for item in result["imported"]] == ["Value Case"]
    reasons = {item["reason"] for item in result["skipped"]}
    assert {"brain_excluded", "dated_archive"} <= reasons
    assert store.get_lane("Nested") is None
    assert Path(result["registry"]).exists()

    included = bootstrap_handovers(store, workspace, include_brain=True)
    assert "Brain" in [item["lane_key"] for item in included["imported"]]
    store.close()


def test_bootstrap_uses_lane_header_and_filename_fallback(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SESSION_HANDOVER_Pepsi_Ops.md").write_text(
        "# Session Handover — Pepsi Ops\n\n"
        "**Lane:**  Pepsi   Ops  \n"
        "**Workspace:** example\n"
        "**Updated:** 2026-09-02\n",
        encoding="utf-8",
    )
    (workspace / "SESSION_HANDOVER_Change_Orders.md").write_text(
        "no header present\n",
        encoding="utf-8",
    )
    (workspace / "SESSION_HANDOVER_Brain.md").write_text(
        "# Session Handover — Brain\n\n**Lane:** Brain\n",
        encoding="utf-8",
    )
    store = ControlStore(str(workspace), tmp_path / "state")
    result = bootstrap_handovers(store, workspace)
    keys = [item["lane_key"] for item in result["imported"]]
    assert keys == ["Change Orders", "Pepsi Ops"]
    assert store.get_lane("Pepsi Ops") is not None
    assert store.get_lane("Pepsi_Ops") is None
    assert store.get_lane("Change_Orders") is None

    included = bootstrap_handovers(store, workspace, include_brain=True)
    assert "Brain" in [item["lane_key"] for item in included["imported"]]
    assert store.get_lane("Brain") is not None
    store.close()


def test_bootstrap_removes_empty_stale_alias_and_reports_in_use_conflict(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    handover = workspace / "SESSION_HANDOVER_Pepsi_Ops.md"
    handover.write_text(
        "# Session Handover — Pepsi Ops\n\n**Lane:** Pepsi Ops\n",
        encoding="utf-8",
    )
    store = ControlStore(str(workspace), tmp_path / "state")
    stale = store.ensure_lane("Pepsi_Ops")
    stale.handover_path = str(handover.resolve())
    store.upsert_lane(stale)

    result = bootstrap_handovers(store, workspace)
    assert [item["lane_key"] for item in result["imported"]] == ["Pepsi Ops"]
    assert result["conflicts"] == []
    assert store.get_lane("Pepsi_Ops") is None
    canonical = store.get_lane("Pepsi Ops")
    assert canonical is not None
    assert canonical.handover_path == str(handover.resolve())

    occupied = workspace / "SESSION_HANDOVER_Value_Case.md"
    occupied.write_text(
        "**Lane:** Value Case\n",
        encoding="utf-8",
    )
    busy = store.ensure_lane("Value_Case")
    busy.handover_path = str(occupied.resolve())
    busy.current_agent_id = "fake-agent"
    store.upsert_lane(busy)
    conflicted = bootstrap_handovers(store, workspace)
    reasons = {item["reason"] for item in conflicted["skipped"]}
    assert "stale_alias_conflict" in reasons
    assert any(
        item["stale_lane_key"] == "Value_Case"
        and item["canonical_lane_key"] == "Value Case"
        for item in conflicted["conflicts"]
    )
    assert store.get_lane("Value_Case") is not None
    assert store.get_lane("Value Case") is None
    store.close()


def test_coordinator_normalizes_spaces_but_keeps_explicit_underscores(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    coord = make_coordinator(workspace, tmp_path / "state")
    spaced = coord.submit_task(lane_key="  Pepsi   Ops  ", objective="route")
    assert spaced.lane_key == "Pepsi Ops"
    assert coord.store.get_lane("Pepsi Ops") is not None
    underscored = coord.submit_task(lane_key="Pepsi_Ops", objective="alias")
    assert underscored.lane_key == "Pepsi_Ops"
    assert normalize_lane_key("Pepsi_Ops") == "Pepsi_Ops"
    assert coord.store.get_lane("Pepsi_Ops") is not None
    coord.close()


def test_legacy_inbox_audit_explicit_mapping_and_deduplication(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inbox = tmp_path / "_inbox"
    inbox.mkdir()
    source = inbox / "Value_Case.md"
    original = "CONFIDENTIAL LEGACY CONTENT"
    source.write_text(original, encoding="utf-8")
    nested = inbox / "nested"
    nested.mkdir()
    (nested / "Ignored.md").write_text("ignored", encoding="utf-8")
    coord = make_coordinator(workspace, tmp_path / "state")

    audit = audit_or_import_legacy_inbox(coord, inbox)
    assert audit["imported"] == []
    assert [item["filename"] for item in audit["inventory"]] == ["Value_Case.md"]
    assert coord.store.list_messages() == []
    assert original not in json.dumps(audit)

    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "Value_Case.md": {
                    "workspace": str(workspace),
                    "target": "value-case",
                }
            }
        ),
        encoding="utf-8",
    )
    first = audit_or_import_legacy_inbox(coord, inbox, mapping_path=mapping)
    second = audit_or_import_legacy_inbox(coord, inbox, mapping_path=mapping)
    assert len(first["imported"]) == 1
    assert second["skipped"][0]["reason"] == "already_imported"
    messages = coord.store.list_messages()
    assert len(messages) == 1
    assert messages[0].metadata["content_imported"] is False
    assert original not in json.dumps(messages[0].to_dict())
    assert source.read_text(encoding="utf-8") == original
    coord.close()


def test_legacy_mapping_rejects_other_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    other = tmp_path / "other"
    inbox = tmp_path / "_inbox"
    workspace.mkdir()
    other.mkdir()
    inbox.mkdir()
    (inbox / "Ops.md").write_text("do not read", encoding="utf-8")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {"Ops.md": {"workspace": str(other), "target": "ops"}}
        ),
        encoding="utf-8",
    )
    coord = make_coordinator(workspace, tmp_path / "state")
    with pytest.raises(ValueError, match="differs"):
        audit_or_import_legacy_inbox(coord, inbox, mapping_path=mapping)
    assert coord.store.list_messages() == []
    coord.close()


def test_cli_serve_bootstrap_legacy_and_service_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    (workspace / "SESSION_HANDOVER_Ops.md").write_text(
        "handover",
        encoding="utf-8",
    )
    inbox = tmp_path / "_inbox"
    inbox.mkdir()
    (inbox / "Ops.md").write_text("legacy", encoding="utf-8")
    common = [
        "--workspace",
        str(workspace),
        "--state-root",
        str(state_root),
    ]

    assert cli.main([*common, "--runtime", "fake", "serve", "--max-cycles", "1"]) == 0
    serve_result = json.loads(capsys.readouterr().out)
    assert serve_result["state"] == "completed"

    assert cli.main([*common, "service-status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["heartbeat"]["state"] == "completed"

    assert cli.main([*common, "bootstrap"]) == 0
    bootstrap_result = json.loads(capsys.readouterr().out)
    assert bootstrap_result["imported"][0]["lane_key"] == "Ops"

    assert cli.main(
        [*common, "legacy-inbox", "--inbox-root", str(inbox)]
    ) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["inventory"][0]["filename"] == "Ops.md"
    assert audit["imported"] == []

    assert cli.main([*common, "stop-service"]) == 0
    stop_path = Path(capsys.readouterr().out.strip())
    assert stop_path.exists()
