# Local Supervised Agent Orchestrator

This package runs bounded Cursor local-agent work through a durable,
workspace-scoped coordinator. SQLite state, task envelopes, approvals,
artifact claims, events, metrics, and lane-to-agent lineage live outside model
context. Each workspace uses a separate database derived from a normalized
workspace-path hash.

## Setup

Requires Python 3.14 and `cursor-sdk` 1.0.30.

```powershell
cd C:\Users\lpuentes001\.cursor\orchestrator
python -m pip install -e ".[dev]"
python -m pytest -v
```

The default state root is
`%USERPROFILE%\.cursor\orchestrator\state`. Override it with `--state-root`.

## Repository

Git root is this directory — the full suite, not `excel-library/` and not
`%USERPROFILE%\.cursor`. One repo, two lane worktrees, `main` here for
integration. Git allows a branch in only one worktree at a time.

| Checkout | Branch | Path |
|---|---|---|
| Integration | `main` | `C:\Users\lpuentes001\.cursor\orchestrator` |
| Framework | `lane/framework` | `%USERPROFILE%\.cursor\worktrees\orchestrator-framework` |
| Excel Library | `lane/excel-library` | `%USERPROFILE%\.cursor\worktrees\orchestrator-excel-library` |

Framework edits stay off `excel-library/`. Excel Library edits stay under
`excel-library/` and `excel-library-intake/`. Merge lane branches into `main`
from this checkout. No remote until one is named.

CI is `.github/workflows/ci.yml`: orchestrator tests on Python 3.14, excel-library
ruff/mypy/pytest on Python 3.12.

## Operating model

- A lane is durable; its physical local-agent handle is replaceable.
- Model, local runtime options, MCP configuration, sandbox settings, tools,
  disallowed tools, and API key are reapplied on every create or resume.
- The API key and runtime config are supplied at execution time and are not
  written to the lane registry.
- Runs serialize within a lane and may execute concurrently across lanes.
- Every run receives a deterministic JSON prompt containing the complete
  context envelope, task permissions and pointers, execution specification,
  and explicit supervised-stop instructions.
- Shared writes require approval before an artifact lock is acquired.
- Child tasks are coordinator-created, depth-one extraction or review jobs.
- Rotation counters are persisted in lane config and survive restarts.
- Recovery expires orphaned envelopes, releases stale claims, writes a daily
  SQLite backup, enforces retention, and exports the lane registry.
- On startup, only tasks actually left `running` by an interrupted owner are
  atomically returned to `queued`; their claims are released and the
  `restart_recovery` metric records the recovered task count. Tasks owned by
  the live workspace service lock are never recovered by status/submit
  processes.
- Messages are coordination between sessions by default and never become agent
  work on their own. Only mail sent with `--executable`, or promoted later with
  `inbox-promote`, is routed. Target validation still runs for every pending
  message, so an unknown or retired lane dead-letters either way, and mail
  written before this flag existed reads as coordination-only.
- Executable messages route to explicitly registered lanes using
  `message:<message-id>` idempotency. They progress through
  `pending → routed → delivered`, or dead-letter with an attributed reason.
  Use `inbox-ack` to close out coordination mail that has already been
  actioned, so it does not read as outstanding work to the next session.
- Agent responses may use the governed JSON contract
  `summary/status/evidence/proposed_messages`. Proposed messages are bounded,
  read-only, same-workspace, and limited to existing lanes; invalid JSON is
  retained only as a plain summary and cannot route work. A proposal is held
  as coordination mail and requires `inbox-promote` before it can execute, so
  an agent cannot schedule the next agent.

## Rollout modes

Use the modes in order:

1. `shadow` records proposed routes without launching workers.
2. `read-only` allows bounded read/extract/summarize/validate work and denies
   write-capable permissions.
3. `supervised` allows write-capable tasks only after explicit approval.

Privacy Mode Legacy means this orchestrator uses local SDK agents only. It
does not create Cloud Agents or Cursor Automations. It does not send external
messages or write external systems without explicit authorization. Hooks,
legacy inbox scripts, and client source files are not modified by the
orchestrator itself.

## Persistent service

`serve` is the normal long-running control loop. It defaults to the local SDK
runtime; use `--runtime fake` for testing or `--mode shadow` to propose routes
without workers. A workspace-qualified lock prevents duplicate services.
SQLite uses WAL mode and a five-second busy timeout so submit, status, approve,
and dashboard commands can run while the service is polling. The loop updates
a durable heartbeat, refreshes the dashboard, honors a stop file, and closes
agent/client handles on shutdown.

In shadow mode, the service reports `proposed_routes` once per unique queued
task and keeps `processed_tasks` at zero. The dashboard separates queued
shadow proposals from unreviewed queued work.

```powershell
$env:CURSOR_API_KEY = "cursor_..."
python -m orchestrator --workspace "C:\work\client" --mode supervised serve `
  --poll-interval 2 --max-tasks 5 --dashboard-refresh 10 `
  --dashboard-output "C:\work\client\orchestrator-dashboard.html"

python -m orchestrator --workspace "C:\work\client" service-status
python -m orchestrator --workspace "C:\work\client" stop-service
```

`--max-cycles` is available for bounded smoke tests. Ctrl+C requests graceful
shutdown and returns exit code 130.

## Local operator console

The operable pilot is a localhost-only browser console. It owns the same
`Coordinator` instance and event loop used for processing, so browser actions
cannot bypass lane locks, pause state, rotation counters, approvals, or the
workspace service lock.

Start safely in shadow mode:

```powershell
cd C:\Users\lpuentes001\.cursor\orchestrator
python -m orchestrator --workspace "C:\work\client" `
  --mode shadow --runtime fake console --port 8765
```

Open `http://127.0.0.1:8765/`. From the console an operator can submit a task,
process the queue, approve or reject requests, pause or resume lanes, propose
or perform rotation, export the current audit snapshot, inspect agent/run
results, and stop the console.

- Shadow mode records proposed routes and never launches a model.
- Read-only mode launches a local Cursor SDK agent and denies file-write tasks
  server-side. It requires `CURSOR_API_KEY` in the console process environment.
- Supervised mode remains gated until the read-only pilot passes.
- Pause prevents the lane's next queued task from starting; it does not cancel
  an in-flight run.
- The listener refuses non-loopback bindings. State-changing requests require
  a per-launch token and same-origin browser request.
- The console has no external scripts, fonts, trackers, analytics, or network
  runtime dependencies. Loopback requests stay on the local machine.

Read-only pilot:

```powershell
$env:CURSOR_API_KEY = "<set locally; do not paste into chat or files>"
python -m orchestrator --workspace "C:\work\throwaway" `
  --mode read-only --runtime sdk --model composer-2.5 console --port 8766
```

Use a non-client workspace first. Submit a bounded read-only task, process it,
and confirm the inspector shows a non-empty agent ID, run ID, terminal status,
and response. Stop the console after the check.

## Bootstrap and legacy migration

Bootstrap imports only top-level, undated `SESSION_HANDOVER_*.md` files. It
does not recurse into archive folders, and excludes Brain unless explicitly
included. Lane identity comes from the `**Lane:**` header when present;
otherwise filename underscores become spaces (`Pepsi_Ops` → `Pepsi Ops`).
If the same handover was previously imported under a stale alias, bootstrap
removes that alias only when it has no tasks and no current agent; otherwise
it reports a conflict and leaves both records unchanged.

Coordinator lane keys collapse leading, trailing, and repeated spaces. Explicit
underscores are kept.

```powershell
python -m orchestrator --workspace "C:\work\client" bootstrap
python -m orchestrator --workspace "C:\work\client" bootstrap --include-brain
```

Legacy inbox handling defaults to inventory only. It reads filenames and file
metadata, not message content:

```powershell
python -m orchestrator --workspace "C:\work\client" legacy-inbox
```

Import requires an explicit mapping. Source files are preserved, content is
not copied, workspace mismatches are rejected, and durable import IDs prevent
duplicates.

```json
{
  "Value_Case.md": {
    "workspace": "C:\\work\\client",
    "target": "value-case"
  }
}
```

```powershell
python -m orchestrator --workspace "C:\work\client" legacy-inbox `
  --mapping ".\legacy-routes.json"
```

## CLI examples

Submit a read-only task:

```powershell
python -m orchestrator --workspace "C:\work\client" --mode shadow submit `
  --lane "meeting-triage" --objective "Propose transcript routing" `
  --spec-id meeting_to_action --idempotency-key mtg-2026-09-02 `
  --evidence "C:\work\client\transcript.docx" --reply-to "request-42"
```

Inspect shadow routing without launching a model:

```powershell
python -m orchestrator --workspace "C:\work\client" --mode shadow `
  --runtime sdk process --max-tasks 10
```

Process with the SDK in read-only mode:

```powershell
$env:CURSOR_API_KEY = "cursor_..."
python -m orchestrator --workspace "C:\work\client" --mode read-only `
  --runtime sdk --model composer-2.5 process --max-tasks 3
```

Submit a supervised write:

```powershell
python -m orchestrator --workspace "C:\work\client" --mode supervised submit `
  --lane "value-case" --objective "Update approved workbook cells" `
  --artifact "C:\work\client\model.xlsx" --write `
  --idempotency-key workbook-update-17
```

Approve and process it:

```powershell
python -m orchestrator --workspace "C:\work\client" approve `
  --approval-id "APPROVAL_ID"
python -m orchestrator --workspace "C:\work\client" --runtime sdk `
  --mode supervised process
```

Reject instead, inspect one task, and pause or resume a lane:

```powershell
python -m orchestrator --workspace "C:\work\client" reject `
  --approval-id "APPROVAL_ID"
python -m orchestrator --workspace "C:\work\client" status --task-id "TASK_ID"
python -m orchestrator --workspace "C:\work\client" pause --lane "value-case"
python -m orchestrator --workspace "C:\work\client" resume --lane "value-case"
```

Use a runtime configuration file:

```json
{
  "mcp_servers": {},
  "sandbox": {"enabled": true},
  "setting_sources": [],
  "tools": ["ReadFile"],
  "disallowed_tools": []
}
```

```powershell
python -m orchestrator --workspace "C:\work\client" --runtime sdk `
  --config ".\runtime-config.json" process
```

Create a bounded review child task:

```powershell
python -m orchestrator --workspace "C:\work\client" delegate `
  --parent-task-id "TASK_ID" --task-type review `
  --objective "Independently review extracted directives"
```

Send coordination mail, promote a held message to executable work, and close
out mail that has already been actioned in-lane:

```powershell
python -m orchestrator --workspace "C:\work\client" inbox-send `
  --target "value-case" --objective "Rates confirmed; pointer in the decision log"
python -m orchestrator --workspace "C:\work\client" inbox-send `
  --target "value-case" --objective "Report the Y1 total from the model" --executable
python -m orchestrator --workspace "C:\work\client" inbox-promote `
  --message-id "MESSAGE_ID"
python -m orchestrator --workspace "C:\work\client" inbox-ack `
  --message-id "MESSAGE_ID" --actor "value-case"
```

List every workspace that has a control store, with lane and work counts:

```powershell
python -m orchestrator --workspace "C:\work\client" workspaces
```

Rotate a lane, recover state, export the registry, and render the dashboard:

```powershell
python -m orchestrator --workspace "C:\work\client" --runtime sdk rotate `
  --lane "meeting-triage" --objective "Continue from fresh context"
python -m orchestrator --workspace "C:\work\client" recover --retention-days 14
python -m orchestrator --workspace "C:\work\client" recover --restore latest
python -m orchestrator --workspace "C:\work\client" registry-export
python -m orchestrator --workspace "C:\work\client" dashboard `
  --output ".\orchestrator-dashboard.html"
```

## Automatic rotation

The coordinator evaluates task boundaries, run count, active age, context
health, serialized envelope size, repeated corrections, and execution-spec
workstream shifts. Triggered rotation writes a handover, preserves prior agent
lineage, creates a fresh agent, resets counters, and records a rotation metric.

## Safety

- Never place client facts in unscoped global artifacts.
- Never bypass approval for file writes, external writes, cross-lane merges,
  or destructive work.
- Tests use `FakeRuntime` or mocked SDK objects and never invoke a model.

## Reuse and third-party design boundary

Prefer extending proven libraries, tools, patterns, and standards over building
new infrastructure from scratch. Reuse is conditional on a documented gate:
provenance and license, PwC approval where required, privacy/data flow, client
isolation, information security, accessibility, generated-code review, and
offline/runtime dependency analysis. An existing component does not bypass
these controls.

Superdesign is used only as an optional, out-of-band visual ideation tool. It
is not authenticated, installed, or integrated into this runtime, and it never
receives coordinator source code or client data. The synthetic prompt in
[`SUPERDESIGN_DASHBOARD_BRIEF.md`](SUPERDESIGN_DASHBOARD_BRIEF.md) may be run
manually; returned HTML is treated as untrusted design input and must pass the
acceptance gate in that brief before replacing the local dashboard renderer.
