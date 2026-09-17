"""Report what dispatched work did, for reading back into a conversation.

A Brain session runs this after dispatching so the operator never has to go
looking in the console for a result.

Usage:
    python tools/dispatch_status.py "<workspace>" [--limit 10] [--pending]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.state import workspace_db_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--pending",
        action="store_true",
        help="Also list mail waiting to be dispatched or promoted",
    )
    args = parser.parse_args()

    workspace = str(Path(args.workspace).resolve())
    db = workspace_db_path(workspace)
    if not db.exists():
        print(f"No control store for {workspace}")
        return 1
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    print(f"workspace: {workspace}")
    rows = list(
        conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
            (args.limit,),
        )
    )
    dispatched = [
        row for row in rows if json.loads(row["metadata"]).get("source_message_id")
    ]
    if not dispatched:
        print("\nNo dispatched tasks yet.")
    for row in dispatched:
        metadata = json.loads(row["metadata"])
        response = metadata.get("agent_response") or {}
        print(f"\n--- {row['lane_key']} | {row['status']} | {row['created_at']}")
        print(f"    objective : {row['objective'][:140]}")
        print(f"    agent/run : {row['agent_id']} / {row['run_id']}")
        if row["error_message"]:
            print(f"    error     : {row['error_message'][:160]}")
        if response:
            structured = response.get("structured")
            print(f"    structured: {structured}")
            if not structured:
                print("    WARNING   : reply ignored the response contract; treat as unverified")
            print(f"    status    : {response.get('status', '(none)')}")
            print(f"    summary   : {str(response.get('summary', ''))[:600]}")
            evidence = response.get("evidence") or json.loads(row["evidence"])
            print(f"    evidence  : {evidence}")

    if args.pending:
        print("\n-- mail not yet executed --")
        for row in conn.execute(
            "SELECT sender, target, objective, metadata FROM messages"
            " WHERE status = 'pending' ORDER BY created_at"
        ):
            executable = bool(json.loads(row["metadata"]).get("executable"))
            kind = "DISPATCHED" if executable else "coordination"
            print(f"  [{kind}] {row['sender']} -> {row['target']}: {row['objective'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
