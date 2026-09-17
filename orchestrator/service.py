from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from .coordinator import Coordinator
from .dashboard import render_dashboard
from .models import utcnow_iso
from .state import is_process_alive, workspace_hash


class ServiceAlreadyRunningError(RuntimeError):
    pass


class WorkspaceServiceLock:
    def __init__(self, workspace: str, state_root: Path) -> None:
        directory = state_root / "services"
        directory.mkdir(parents=True, exist_ok=True)
        namespace = workspace_hash(workspace)
        self.path = directory / f"{namespace}.lock"
        self.default_stop_path = directory / f"{namespace}.stop"
        self.token = uuid4().hex
        self.acquired = False

    def acquire(self) -> None:
        payload = {
            "pid": os.getpid(),
            "token": self.token,
            "started_at": utcnow_iso(),
        }
        while True:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True)
                self.acquired = True
                return
            except FileExistsError:
                try:
                    existing = json.loads(self.path.read_text(encoding="utf-8"))
                    pid = int(existing.get("pid", 0))
                except (OSError, ValueError, json.JSONDecodeError):
                    pid = 0
                if is_process_alive(pid):
                    raise ServiceAlreadyRunningError(
                        f"Workspace service already running with PID {pid}"
                    )
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    continue

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            existing = json.loads(self.path.read_text(encoding="utf-8"))
            if existing.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            pass
        self.acquired = False


async def serve(
    coordinator: Coordinator,
    *,
    poll_interval: float = 2.0,
    max_tasks: int = 10,
    dashboard_refresh: float = 10.0,
    dashboard_output: Path | None = None,
    stop_file: Path | None = None,
    max_cycles: int | None = None,
) -> dict[str, object]:
    lock = WorkspaceServiceLock(coordinator.workspace, coordinator.store.state_root)
    lock.acquire()
    coordinator.set_service_owner(lock.token)
    resolved_stop = stop_file or lock.default_stop_path
    resolved_stop.parent.mkdir(parents=True, exist_ok=True)
    resolved_stop.unlink(missing_ok=True)
    cycles = 0
    processed = 0
    proposed = 0
    last_dashboard = 0.0
    state = "running"
    try:
        while True:
            if resolved_stop.exists():
                # Terminal, not transitional: the heartbeat written in the
                # finally block is the last one an operator will ever see, so
                # it has to say the service is down, not going down.
                state = "stopped"
                break
            coordinator.store.set_service_heartbeat(
                {
                    "state": "running",
                    "pid": os.getpid(),
                    "cycles": cycles,
                    "processed_tasks": processed,
                    "proposed_routes": proposed,
                    "updated_at": utcnow_iso(),
                    "lock_path": str(lock.path),
                    "stop_file": str(resolved_stop),
                }
            )
            tasks = await coordinator.process(max_tasks=max_tasks)
            processed += coordinator.last_cycle_stats["processed_tasks"]
            proposed += coordinator.last_cycle_stats["proposed_routes"]
            cycles += 1
            now = time.monotonic()
            if dashboard_output and (
                dashboard_refresh <= 0
                or now - last_dashboard >= dashboard_refresh
            ):
                render_dashboard(coordinator.snapshot(), dashboard_output)
                last_dashboard = now
            if max_cycles is not None and cycles >= max_cycles:
                state = "completed"
                break
            await asyncio.sleep(max(0.01, poll_interval))
    except asyncio.CancelledError:
        state = "cancelled"
        raise
    finally:
        coordinator.store.set_service_heartbeat(
            {
                "state": state,
                "pid": os.getpid(),
                "cycles": cycles,
                "processed_tasks": processed,
                "proposed_routes": proposed,
                "updated_at": utcnow_iso(),
                "lock_path": str(lock.path),
                "stop_file": str(resolved_stop),
            }
        )
        lock.release()
        if state in {"stopped", "completed"}:
            resolved_stop.unlink(missing_ok=True)
    return {
        "state": state,
        "cycles": cycles,
        "processed_tasks": processed,
        "proposed_routes": proposed,
    }


def request_service_stop(
    workspace: str,
    state_root: Path,
    stop_file: Path | None = None,
) -> Path:
    lock = WorkspaceServiceLock(workspace, state_root)
    path = stop_file or lock.default_stop_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(utcnow_iso(), encoding="utf-8")
    return path


def service_status(coordinator: Coordinator) -> dict[str, object]:
    lock = WorkspaceServiceLock(
        coordinator.workspace,
        coordinator.store.state_root,
    )
    heartbeat = coordinator.store.get_service_heartbeat() or {}
    return {
        "workspace_hash": workspace_hash(coordinator.workspace),
        "lock_exists": lock.path.exists(),
        "stop_requested": lock.default_stop_path.exists(),
        "heartbeat": heartbeat,
    }
