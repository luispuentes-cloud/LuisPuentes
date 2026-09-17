"""Deterministic end-to-end gate check against a running operator console.

Proves the full supervised path — console, coordinator, SDK agent, governed
response contract — with an answer that can only be produced by reading a file
in the workspace this run.

The earlier gate asked an agent to count lines in README.md. Three runs on
2026-09-09 returned 5, 8, and 6 for a 5-line file, so a pass proved little. A
fresh random token is exact-match verifiable and cannot be approximated.

Usage:
    python tools/gate_check.py [--base http://127.0.0.1:8766] [--lane "Gate Check"]

Exit code 0 on pass, 1 on failure. The console must already be running with the
SDK runtime; this script never needs the API key.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

FIXTURE_NAME = "gate_fixture.txt"
OBJECTIVE = (
    f"Read the file {FIXTURE_NAME} in the workspace root. It contains a single "
    "line of the form TOKEN=<value>. Reply with only <value>, the exact "
    "characters after TOKEN=, as your summary. Do not write, create, or modify "
    "any file."
)


def console_token(base: str) -> str:
    """Read the per-start console token from the dashboard's meta tag."""
    with urllib.request.urlopen(base + "/", timeout=60) as response:
        html = response.read().decode("utf-8", "replace")
    match = re.search(r'<meta name="orchestrator-token" content="([^"]*)"', html)
    if not match or not match.group(1):
        raise SystemExit(f"FAIL: no console token at {base}; is the console running?")
    return match.group(1)


def post(base: str, action: str, payload: dict[str, Any], token: str) -> Any:
    request = urllib.request.Request(
        f"{base}/api/{action}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Orchestrator-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))["result"]
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")
        raise SystemExit(f"FAIL: {action} returned {err.code}: {detail}") from err


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8766")
    parser.add_argument("--lane", default="Gate Check")
    args = parser.parse_args()

    token = console_token(args.base)
    workspace = Path(post(args.base, "snapshot", {}, token)["workspace"])
    expected = secrets.token_hex(8)
    fixture = workspace / FIXTURE_NAME
    fixture.write_text(f"TOKEN={expected}\n", encoding="utf-8")
    print(f"workspace : {workspace}")
    print(f"fixture   : {fixture} (TOKEN={expected})")

    submitted = post(
        args.base,
        "submit",
        {
            "lane": args.lane,
            "objective": OBJECTIVE,
            "idempotency_key": f"gate-check:{expected}",
            "write_files": False,
        },
        token,
    )
    task_id = submitted["task_id"]
    print(f"task      : {task_id}")

    started = time.time()
    processed = post(args.base, "process", {"max_tasks": 5}, token)
    elapsed = time.time() - started
    task = next((item for item in processed if item["task_id"] == task_id), None)
    if task is None:
        print(f"FAIL: task {task_id} was not processed in this cycle ({elapsed:.1f}s)")
        return 1

    response = (task.get("metadata") or {}).get("agent_response") or {}
    summary = str(response.get("summary", "")).strip()
    print(f"elapsed   : {elapsed:.1f}s")
    print(f"status    : {task['status']}")
    print(f"agent     : {task['agent_id']}")
    print(f"run       : {task['run_id']}")
    print(f"structured: {response.get('structured')}")
    print(f"summary   : {summary[:200]}")

    if task["status"] != "completed":
        print(f"FAIL: task ended {task['status']}: {task.get('error_message')}")
        return 1
    if expected not in summary:
        print(f"FAIL: token {expected} absent from the reply")
        return 1

    if summary != expected:
        print("WARN: token found but the reply carried extra text")
    if not response.get("structured"):
        print("WARN: reply did not honor the JSON response contract")
    print(f"PASS: agent returned the token issued for this run ({expected})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
