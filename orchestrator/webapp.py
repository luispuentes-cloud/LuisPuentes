from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .coordinator import Coordinator
from .dashboard import render_dashboard_html
from .models import Permissions, utcnow_iso
from .service import WorkspaceServiceLock
from .state import list_known_workspaces


MAX_BODY_BYTES = 128_000
MAX_TEXT_LENGTH = 20_000


class ConsoleError(ValueError):
    pass


class ConsoleApplication:
    """Local-only browser control surface for one coordinator event loop."""

    def __init__(
        self,
        coordinator: Coordinator,
        *,
        operator: str | None = None,
        max_tasks: int = 10,
    ) -> None:
        self.coordinator = coordinator
        self.operator = operator or os.environ.get("USERNAME") or "local-operator"
        self.max_tasks = max_tasks
        self.token = secrets.token_urlsafe(32)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop_event: asyncio.Event | None = None
        self._process_lock = asyncio.Lock()

    def bind_loop(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()

    def submit_to_loop(self, action: str, payload: dict[str, Any]) -> Any:
        if self.loop is None:
            raise RuntimeError("Console event loop is not running")
        future = asyncio.run_coroutine_threadsafe(
            self.dispatch(action, payload),
            self.loop,
        )
        return future.result(timeout=120)

    @staticmethod
    def _text(
        payload: dict[str, Any],
        key: str,
        *,
        required: bool = False,
        limit: int = MAX_TEXT_LENGTH,
    ) -> str:
        value = payload.get(key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ConsoleError(f"{key} must be text")
        value = value.strip()
        if required and not value:
            raise ConsoleError(f"{key} is required")
        if len(value) > limit:
            raise ConsoleError(f"{key} exceeds {limit} characters")
        return value

    @staticmethod
    def _bool(payload: dict[str, Any], key: str) -> bool:
        value = payload.get(key, False)
        if not isinstance(value, bool):
            raise ConsoleError(f"{key} must be true or false")
        return value

    async def dispatch(self, action: str, payload: dict[str, Any]) -> Any:
        if action == "snapshot":
            return self.coordinator.snapshot()
        if action == "submit":
            write_files = self._bool(payload, "write_files")
            if self.coordinator.mode == "read-only" and write_files:
                raise PermissionError("Read-only mode denies write-capable submissions")
            lane = self._text(payload, "lane", required=True, limit=200)
            objective = self._text(payload, "objective", required=True)
            artifact = self._text(payload, "artifact", limit=2048)
            evidence = self._text(payload, "evidence", limit=2048)
            idempotency_key = self._text(
                payload, "idempotency_key", required=True, limit=300
            )
            task = self.coordinator.submit_task(
                lane_key=lane,
                objective=objective,
                permissions=Permissions(write_files=write_files),
                artifacts=[artifact] if artifact else [],
                evidence=[evidence] if evidence else [],
                idempotency_key=idempotency_key,
                ttl_seconds=3600,
            )
            return task.to_dict()
        if action == "process":
            requested = payload.get("max_tasks", self.max_tasks)
            if not isinstance(requested, int) or not 1 <= requested <= 50:
                raise ConsoleError("max_tasks must be an integer from 1 to 50")
            async with self._process_lock:
                tasks = await self.coordinator.process(max_tasks=requested)
            return [task.to_dict() for task in tasks]
        if action in {"approve", "reject"}:
            approval_id = self._text(
                payload, "approval_id", required=True, limit=100
            )
            method = (
                self.coordinator.approve
                if action == "approve"
                else self.coordinator.reject
            )
            return method(approval_id, resolver=self.operator).to_dict()
        if action in {"pause_lane", "resume_lane"}:
            lane = self._text(payload, "lane", required=True, limit=200)
            if action == "pause_lane":
                self.coordinator.pause_lane(lane)
            else:
                self.coordinator.resume_lane(lane)
            return {"lane": lane, "status": "paused" if action == "pause_lane" else "idle"}
        if action in {"promote_message", "acknowledge_message"}:
            message_id = self._text(
                payload, "message_id", required=True, limit=100
            )
            if action == "promote_message":
                return self.coordinator.promote_message(
                    message_id, actor=self.operator
                ).to_dict()
            return self.coordinator.acknowledge_message(
                message_id, actor=self.operator
            ).to_dict()
        if action == "rotate_lane":
            lane = self._text(payload, "lane", required=True, limit=200)
            objective = self._text(payload, "objective", required=True)
            return await self.coordinator.rotate_lane(lane, objective=objective)
        if action == "recover":
            return self.coordinator.recover(retention_days=14)
        if action == "export":
            return self.coordinator.snapshot()
        if action == "stop":
            if self.stop_event is None:
                raise RuntimeError("Console stop event is unavailable")
            self.stop_event.set()
            return {"state": "stopping"}
        raise ConsoleError(f"Unsupported action: {action}")


def _handler_factory(app: ConsoleApplication) -> type[BaseHTTPRequestHandler]:
    class ConsoleHandler(BaseHTTPRequestHandler):
        server_version = "LocalOrchestratorConsole/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _json(self, status: HTTPStatus, payload: Any) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _html(self, content: str) -> None:
            body = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                try:
                    snapshot = app.submit_to_loop("snapshot", {})
                    self._html(
                        render_dashboard_html(
                            snapshot,
                            console_token=app.token,
                            workspaces=list_known_workspaces(
                                app.coordinator.store.state_root
                            ),
                        )
                    )
                except Exception as err:
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(err)})
                return
            if parsed.path == "/api/health":
                self._json(HTTPStatus.OK, {"state": "running", "mode": app.coordinator.mode})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if self.headers.get("X-Orchestrator-Token") != app.token:
                self._json(HTTPStatus.FORBIDDEN, {"error": "invalid console token"})
                return
            origin = self.headers.get("Origin")
            expected = f"http://{self.headers.get('Host')}"
            if origin and origin != expected:
                self._json(HTTPStatus.FORBIDDEN, {"error": "cross-origin request denied"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid content length"})
                return
            if length > MAX_BODY_BYTES:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request too large"})
                return
            try:
                raw = self.rfile.read(length)
                payload = json.loads(raw or b"{}")
                if not isinstance(payload, dict):
                    raise ConsoleError("JSON body must be an object")
                action = urlparse(self.path).path.removeprefix("/api/")
                result = app.submit_to_loop(action, payload)
                self._json(HTTPStatus.OK, {"ok": True, "result": result})
            except PermissionError as err:
                self._json(HTTPStatus.FORBIDDEN, {"error": str(err)})
            except (ConsoleError, KeyError, json.JSONDecodeError) as err:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(err)})
            except Exception as err:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(err)})

    return ConsoleHandler


async def run_console(
    coordinator: Coordinator,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    max_tasks: int = 10,
) -> dict[str, Any]:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Operator console may bind only to loopback")
    app = ConsoleApplication(coordinator, max_tasks=max_tasks)
    app.bind_loop()
    lock = WorkspaceServiceLock(coordinator.workspace, coordinator.store.state_root)
    lock.acquire()
    coordinator.set_service_owner(lock.token)
    server = ThreadingHTTPServer((host, port), _handler_factory(app))
    thread = threading.Thread(
        target=server.serve_forever,
        name="orchestrator-console",
        daemon=True,
    )
    thread.start()
    coordinator.store.set_service_heartbeat(
        {
            "state": "running",
            "kind": "operator-console",
            "pid": os.getpid(),
            "updated_at": utcnow_iso(),
            "url": f"http://{host}:{server.server_port}/",
        }
    )
    try:
        assert app.stop_event is not None
        while not app.stop_event.is_set():
            try:
                await asyncio.wait_for(app.stop_event.wait(), timeout=5)
            except TimeoutError:
                coordinator.store.set_service_heartbeat(
                    {
                        "state": "running",
                        "kind": "operator-console",
                        "pid": os.getpid(),
                        "updated_at": utcnow_iso(),
                        "url": f"http://{host}:{server.server_port}/",
                    }
                )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        coordinator.store.set_service_heartbeat(
            {
                "state": "stopped",
                "kind": "operator-console",
                "pid": os.getpid(),
                "updated_at": utcnow_iso(),
            }
        )
        lock.release()
    return {"state": "stopped", "url": f"http://{host}:{server.server_port}/"}
