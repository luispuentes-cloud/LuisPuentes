from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .bootstrap import bootstrap_handovers
from .coordinator import Coordinator
from .dashboard import render_dashboard
from .legacy import audit_or_import_legacy_inbox
from .models import Permissions
from .runtime import CursorSDKRuntime, FakeRuntime
from .service import (
    request_service_stop,
    serve,
    service_status,
)
from .state import list_known_workspaces, workspace_hash
from .webapp import run_console


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestrator", description="Local supervised agent orchestrator")
    parser.add_argument("--workspace", required=True, help="Workspace root path")
    parser.add_argument("--state-root", default=None, help="Override SQLite state root")
    parser.add_argument("--runtime", choices=["fake", "sdk"], default=None)
    parser.add_argument(
        "--mode",
        choices=["shadow", "read-only", "supervised"],
        default="supervised",
    )
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument("--api-key-env", default="CURSOR_API_KEY")
    parser.add_argument("--config", help="JSON runtime configuration file")
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit", help="Submit a task")
    submit.add_argument("--lane", required=True)
    submit.add_argument("--objective", required=True)
    submit.add_argument("--spec-id")
    submit.add_argument("--idempotency-key")
    submit.add_argument("--reply-to")
    submit.add_argument("--evidence", action="append", default=[])
    submit.add_argument("--ttl-seconds", type=int)
    submit.add_argument("--artifact", action="append", default=[])
    submit.add_argument("--write", action="store_true")

    status = sub.add_parser("status", help="Task status")
    status.add_argument("--task-id", required=True)

    approve = sub.add_parser("approve", help="Approve a pending action")
    approve.add_argument("--approval-id", required=True)
    approve.add_argument("--resolver", default="user")

    reject = sub.add_parser("reject", help="Reject a pending action")
    reject.add_argument("--approval-id", required=True)
    reject.add_argument("--resolver", default="user")

    pause = sub.add_parser("pause", help="Pause lane or task")
    pause.add_argument("--lane")
    pause.add_argument("--task-id")

    resume = sub.add_parser("resume", help="Resume lane or task")
    resume.add_argument("--lane")
    resume.add_argument("--task-id")

    rotate = sub.add_parser("rotate", help="Rotate lane to fresh agent")
    rotate.add_argument("--lane", required=True)
    rotate.add_argument("--objective", required=True)
    rotate.add_argument("--spec-id")

    recover = sub.add_parser("recover", help="Expire orphans, back up, or restore")
    recover.add_argument("--restore", help="Workspace backup path or 'latest'")
    recover.add_argument("--retention-days", type=int, default=14)

    process = sub.add_parser("process", help="Process queued tasks")
    process.add_argument("--max-tasks", type=int, default=10)

    dashboard = sub.add_parser("dashboard", help="Generate HTML dashboard")
    dashboard.add_argument("--output", required=True)

    inbox = sub.add_parser("inbox-send", help="Send workspace-scoped inbox message")
    inbox.add_argument("--target", required=True)
    inbox.add_argument("--objective", required=True)
    inbox.add_argument("--ttl-seconds", type=int, default=86400)
    inbox.add_argument(
        "--executable",
        action="store_true",
        help="Allow this message to become agent work; default is coordination only",
    )

    inbox_ack = sub.add_parser("inbox-ack", help="Mark coordination mail as actioned")
    inbox_ack.add_argument("--message-id", required=True)
    inbox_ack.add_argument("--actor", default="user")
    inbox_ack.add_argument("--note")

    inbox_promote = sub.add_parser(
        "inbox-promote", help="Allow a held message to become agent work"
    )
    inbox_promote.add_argument("--message-id", required=True)
    inbox_promote.add_argument("--actor", default="user")

    delegate = sub.add_parser("delegate", help="Create a bounded child task")
    delegate.add_argument("--parent-task-id", required=True)
    delegate.add_argument("--task-type", choices=["extraction", "review"], required=True)
    delegate.add_argument("--objective", required=True)
    delegate.add_argument("--lane")

    registry = sub.add_parser("registry-export", help="Export lane registry JSON")
    registry.add_argument("--output")

    serve_parser = sub.add_parser("serve", help="Run persistent polling service")
    serve_parser.add_argument("--poll-interval", type=float, default=2.0)
    serve_parser.add_argument("--max-tasks", type=int, default=10)
    serve_parser.add_argument("--dashboard-refresh", type=float, default=10.0)
    serve_parser.add_argument("--dashboard-output")
    serve_parser.add_argument("--stop-file")
    serve_parser.add_argument("--max-cycles", type=int)

    console = sub.add_parser("console", help="Run localhost operator console")
    console.add_argument("--host", default="127.0.0.1")
    console.add_argument("--port", type=int, default=8765)
    console.add_argument("--max-tasks", type=int, default=10)

    stop = sub.add_parser("stop-service", help="Request service shutdown")
    stop.add_argument("--stop-file")

    sub.add_parser("service-status", help="Inspect service heartbeat")

    sub.add_parser(
        "workspaces", help="List every workspace with a control store"
    )

    bootstrap = sub.add_parser("bootstrap", help="Import top-level session handovers")
    bootstrap.add_argument("--include-brain", action="store_true")

    legacy = sub.add_parser("legacy-inbox", help="Audit or explicitly map legacy inbox")
    legacy.add_argument(
        "--inbox-root",
        default=str(Path.home() / ".cursor" / "_inbox"),
    )
    legacy.add_argument("--mapping", help="Explicit legacy route mapping JSON")

    return parser


def _runtime_config(args: argparse.Namespace) -> dict[str, object]:
    if not args.config:
        return {"model": args.model}
    payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Runtime config must be a JSON object")
    payload.setdefault("model", args.model)
    return payload


async def _coordinator(args: argparse.Namespace) -> Coordinator:
    state_root = Path(args.state_root) if args.state_root else None
    selected_sdk = (
        args.command in {"serve", "console"}
        and args.runtime != "fake"
        and args.mode != "shadow"
    ) or (
        args.command in {"process", "rotate"}
        and args.runtime == "sdk"
        and args.mode != "shadow"
    )
    if selected_sdk:
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{args.api_key_env} is required for local Cursor SDK execution. "
                "Set it in the launching terminal; do not store it in a file."
            )
        runtime = await CursorSDKRuntime.connect(
            args.workspace,
            api_key=api_key,
            config_overrides=_runtime_config(args),
        )
    else:
        runtime = FakeRuntime()
    return Coordinator(
        args.workspace,
        runtime,
        state_root=state_root,
        mode=args.mode,
    )


async def _async_main(args: argparse.Namespace) -> int:
    coord = await _coordinator(args)
    try:
        if args.command == "submit":
            perms = Permissions(write_files=args.write)
            task = coord.submit_task(
                lane_key=args.lane,
                objective=args.objective,
                spec_id=args.spec_id,
                idempotency_key=args.idempotency_key,
                reply_to=args.reply_to,
                ttl_seconds=args.ttl_seconds,
                artifacts=args.artifact,
                evidence=args.evidence,
                permissions=perms,
            )
            print(json.dumps(task.to_dict(), indent=2))
            return 0
        if args.command == "status":
            task = coord.get_status(args.task_id)
            if not task:
                print("not found", file=sys.stderr)
                return 1
            print(json.dumps(task.to_dict(), indent=2))
            return 0
        if args.command == "approve":
            approval = coord.approve(args.approval_id, resolver=args.resolver)
            print(json.dumps(approval.to_dict(), indent=2))
            return 0
        if args.command == "reject":
            approval = coord.reject(args.approval_id, resolver=args.resolver)
            print(json.dumps(approval.to_dict(), indent=2))
            return 0
        if args.command == "pause":
            if args.lane:
                coord.pause_lane(args.lane)
            elif args.task_id:
                coord.pause_task(args.task_id)
            else:
                print("provide --lane or --task-id", file=sys.stderr)
                return 1
            print("paused")
            return 0
        if args.command == "resume":
            if args.lane:
                coord.resume_lane(args.lane)
            elif args.task_id:
                coord.resume_task(args.task_id)
            else:
                print("provide --lane or --task-id", file=sys.stderr)
                return 1
            print("resumed")
            return 0
        if args.command == "rotate":
            lane = coord.store.ensure_lane(args.lane)
            lane.model = args.model
            coord.store.upsert_lane(lane)
            result = await coord.rotate_lane(args.lane, objective=args.objective, spec_id=args.spec_id)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "recover":
            restore = None
            if args.restore:
                if args.restore == "latest":
                    backups = coord.store.list_backups()
                    if not backups:
                        raise FileNotFoundError("No workspace backup is available")
                    restore = backups[0]
                else:
                    restore = Path(args.restore)
            result = coord.recover(
                restore_backup=restore,
                retention_days=args.retention_days,
            )
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "process":
            for task in coord.store.list_tasks():
                lane = coord.store.ensure_lane(task.lane_key)
                lane.model = args.model
                coord.store.upsert_lane(lane)
            tasks = await coord.process(max_tasks=args.max_tasks)
            print(json.dumps([t.to_dict() for t in tasks], indent=2))
            return 0
        if args.command == "dashboard":
            path = render_dashboard(coord.snapshot(), Path(args.output))
            print(str(path))
            return 0
        if args.command == "inbox-send":
            message = coord.inbox_send(
                target=args.target,
                objective=args.objective,
                ttl_seconds=args.ttl_seconds,
                executable=args.executable,
            )
            print(json.dumps(message.to_dict(), indent=2))
            return 0
        if args.command == "inbox-promote":
            message = coord.promote_message(args.message_id, actor=args.actor)
            print(json.dumps(message.to_dict(), indent=2))
            return 0
        if args.command == "inbox-ack":
            message = coord.acknowledge_message(
                args.message_id,
                actor=args.actor,
                note=args.note,
            )
            print(json.dumps(message.to_dict(), indent=2))
            return 0
        if args.command == "delegate":
            task = coord.delegate_task(
                args.parent_task_id,
                task_type=args.task_type,
                objective=args.objective,
                lane_key=args.lane,
            )
            print(json.dumps(task.to_dict(), indent=2))
            return 0
        if args.command == "registry-export":
            path = coord.store.export_lane_registry(
                Path(args.output) if args.output else None
            )
            print(str(path))
            return 0
        if args.command == "serve":
            for task in coord.store.list_tasks():
                lane = coord.store.ensure_lane(task.lane_key)
                lane.model = args.model
                coord.store.upsert_lane(lane)
            dashboard_output = (
                Path(args.dashboard_output)
                if args.dashboard_output
                else coord.store.state_root
                / "dashboards"
                / f"{workspace_hash(coord.workspace)}.html"
            )
            result = await serve(
                coord,
                poll_interval=args.poll_interval,
                max_tasks=args.max_tasks,
                dashboard_refresh=args.dashboard_refresh,
                dashboard_output=dashboard_output,
                stop_file=Path(args.stop_file) if args.stop_file else None,
                max_cycles=args.max_cycles,
            )
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "console":
            for task in coord.store.list_tasks():
                lane = coord.store.ensure_lane(task.lane_key)
                lane.model = args.model
                coord.store.upsert_lane(lane)
            url = f"http://{args.host}:{args.port}/"
            print(f"Operator console: {url}", flush=True)
            result = await run_console(
                coord,
                host=args.host,
                port=args.port,
                max_tasks=args.max_tasks,
            )
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "stop-service":
            path = request_service_stop(
                coord.workspace,
                coord.store.state_root,
                Path(args.stop_file) if args.stop_file else None,
            )
            print(str(path))
            return 0
        if args.command == "service-status":
            print(json.dumps(service_status(coord), indent=2))
            return 0
        if args.command == "workspaces":
            print(
                json.dumps(
                    list_known_workspaces(coord.store.state_root),
                    indent=2,
                )
            )
            return 0
        if args.command == "bootstrap":
            result = bootstrap_handovers(
                coord.store,
                Path(args.workspace),
                include_brain=args.include_brain,
            )
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "legacy-inbox":
            result = audit_or_import_legacy_inbox(
                coord,
                Path(args.inbox_root),
                mapping_path=Path(args.mapping) if args.mapping else None,
            )
            print(json.dumps(result, indent=2))
            return 0
        print("unknown command", file=sys.stderr)
        return 1
    finally:
        await coord.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        return 130
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
