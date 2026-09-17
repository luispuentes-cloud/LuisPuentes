# Local Supervised Agent Orchestrator — Project Context

Last reviewed: 2026-09-17
Owner: Luis Puentes

## Outcome

Run bounded Cursor local-agent work through a durable, workspace-scoped
coordinator. The operator console is the control surface. A planner / main
agent is a later decision, not part of the current pilot.

This workspace is personal Framework infrastructure. It is not a client
engagement. Do not load client `PROJECT_CONTEXT.md` files, people, numbers, or
source artifacts unless the operator explicitly names that engagement and the
task is fully specified with evidence pointers.

## Workstream lanes

| Lane | Scope | Git |
|---|---|---|
| **Framework** | Orchestrator, consulting OS, skills, hooks, TLS/SDK runtime, console | branch `lane/framework` in `%USERPROFILE%\.cursor\worktrees\orchestrator-framework` |
| **Excel Library** | `excel-library/` linter and later generator | branch `lane/excel-library` in `%USERPROFILE%\.cursor\worktrees\orchestrator-excel-library` |

The git root is this folder (the full suite). `main` stays in this checkout as
the integration branch. Each lane uses its own worktree so the two agents do
not share an index. Inbox and coordinator SQLite are hashed by the opened
folder path, so a lane should open its worktree as the Cursor workspace.

Resume Framework from its worktree. Do not keep an active Framework handover
inside a client workspace.

## Canonical sources

| Domain | Path |
|---|---|
| Package and operating model | `README.md` |
| Pilot evidence | `OPERABLE_PILOT.md` |
| Coordinator / runtime / console | `orchestrator/` |
| Isolated SDK smoke | `tools/sdk_smoke.py` |
| End-to-end console gate | `tools/gate_check.py` |
| Supervised write gate | `tools/write_gate_check.py` |
| Node TLS probe | `tools/node_tls_check.js` |
| Corporate CA export | `tools/export_corp_ca.ps1` |
| Trust bundle | `%USERPROFILE%\.cursor\corp-ca.pem` |
| State | `%USERPROFILE%\.cursor\orchestrator\state` |

## Integrations and permissions

- Runtime: `cursor-sdk` 1.0.30, local agents only. No Cloud Agents, no Cursor
  Automations.
- Auth: `CURSOR_API_KEY` in the same PowerShell process that launches the
  console or smoke test. Do not `setx`. Do not write the key to chat or files.
- Network: the SDK bridge is Node and ignores the Windows certificate store.
  This PC inspects TLS. `runtime.py::_ensure_bridge_ca_trust()` sets
  `NODE_EXTRA_CA_CERTS` to `~\.cursor\corp-ca.pem` before `launch_bridge`.
- Console binds `127.0.0.1` only.

## How to start

```powershell
cd C:\Users\lpuentes001\.cursor\orchestrator
python -m pytest -q
```

Shadow (no model):

```powershell
python -m orchestrator --workspace "<path>" --mode shadow --runtime fake console --port 8765
```

Read-only SDK (requires the API key in that process):

```powershell
$env:CURSOR_API_KEY = "<set locally>"
python -m orchestrator --workspace "$env:TEMP\cursor-orchestrator-pilot" --mode read-only --runtime sdk --model composer-2.5 console --port 8766
```

## Who's who

| Person | Role |
|---|---|
| Luis Puentes | Operator and Framework owner |
