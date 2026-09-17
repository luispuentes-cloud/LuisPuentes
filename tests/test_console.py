from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from orchestrator.coordinator import Coordinator
from orchestrator.dashboard import render_dashboard_html
from orchestrator.runtime import FakeRuntime
from orchestrator.webapp import ConsoleApplication, _handler_factory, run_console


def coordinator(workspace: Path, state_root: Path, *, mode: str = "shadow") -> Coordinator:
    workspace.mkdir(exist_ok=True)
    return Coordinator(
        str(workspace),
        FakeRuntime(),
        state_root=state_root,
        mode=mode,
    )


@pytest.mark.asyncio
async def test_console_dispatch_is_idempotent_and_processes_shadow(tmp_path: Path) -> None:
    coord = coordinator(tmp_path / "workspace", tmp_path / "state")
    app = ConsoleApplication(coord, operator="tester")
    payload = {
        "lane": "Pilot",
        "objective": "Read a synthetic file",
        "artifact": "",
        "evidence": "",
        "idempotency_key": "same-request",
        "write_files": False,
    }
    first = await app.dispatch("submit", payload)
    second = await app.dispatch("submit", payload)
    assert first["task_id"] == second["task_id"]
    processed = await app.dispatch("process", {"max_tasks": 5})
    assert processed[0]["metadata"]["proposed_route"]["requires_approval"] is False
    assert processed[0]["agent_id"] is None
    await coord.aclose()


@pytest.mark.asyncio
async def test_console_rejects_write_submission_in_read_only_mode(tmp_path: Path) -> None:
    coord = coordinator(
        tmp_path / "workspace",
        tmp_path / "state",
        mode="read-only",
    )
    app = ConsoleApplication(coord)
    with pytest.raises(PermissionError, match="Read-only mode"):
        await app.dispatch(
            "submit",
            {
                "lane": "Pilot",
                "objective": "Try to write",
                "artifact": "sample.xlsx",
                "evidence": "",
                "idempotency_key": "denied-write",
                "write_files": True,
            },
        )
    assert coord.store.list_tasks() == []
    await coord.aclose()


@pytest.mark.asyncio
async def test_console_http_requires_token_and_marshals_to_loop(tmp_path: Path) -> None:
    coord = coordinator(tmp_path / "workspace", tmp_path / "state")
    app = ConsoleApplication(coord)
    app.bind_loop()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_factory(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    for _ in range(20):
        try:
            urlopen(f"{url}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.05)

    def post(token: str) -> tuple[int, dict[str, object]]:
        request = Request(
            f"{url}/api/submit",
            data=json.dumps(
                {
                    "lane": "HTTP Pilot",
                    "objective": "Synthetic task",
                    "artifact": "",
                    "evidence": "",
                    "idempotency_key": "http-pilot",
                    "write_files": False,
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Orchestrator-Token": token,
                "Origin": url,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as err:
            return err.code, json.loads(err.read())

    denied_status, _ = await asyncio.to_thread(post, "wrong")
    accepted_status, accepted = await asyncio.to_thread(post, app.token)
    assert denied_status == 403
    assert accepted_status == 200
    assert accepted["result"]["lane_key"] == "HTTP Pilot"

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    await coord.aclose()


@pytest.mark.asyncio
async def test_console_approval_uses_fixed_operator_identity(tmp_path: Path) -> None:
    coord = coordinator(
        tmp_path / "workspace",
        tmp_path / "state",
        mode="supervised",
    )
    app = ConsoleApplication(coord, operator="fixed-operator")
    task = coord.submit_task(
        lane_key="Approval",
        objective="Write synthetic artifact",
    )
    approval = coord.request_approval(task, "execute", "test approval")
    result = await app.dispatch("approve", {"approval_id": approval.approval_id})
    assert result["resolver"] == "fixed-operator"
    await coord.aclose()


def test_dashboard_console_controls_accessibility_and_escaping(tmp_path: Path) -> None:
    coord = coordinator(tmp_path / "workspace", tmp_path / "state")
    coord.submit_task(
        lane_key="Pilot",
        objective="<img src=x onerror=alert(1)>",
        idempotency_key="escape",
    )
    content = render_dashboard_html(coord.snapshot(), console_token="local-token")
    assert 'id="submit-task"' in content
    assert 'role="status"' in content
    assert 'aria-live="polite"' in content
    assert 'scope="col"' in content
    assert "<img src=x onerror=alert(1)>" not in content
    assert "&lt;img src=x onerror=alert(1)&gt;" in content
    coord.close()


@pytest.mark.asyncio
async def test_console_refuses_non_loopback_binding(tmp_path: Path) -> None:
    coord = coordinator(tmp_path / "workspace", tmp_path / "state")
    with pytest.raises(ValueError, match="loopback"):
        await run_console(coord, host="0.0.0.0", port=0)
    await coord.aclose()
