# Operable Orchestrator Pilot

Date: 2026-09-02

## Outcome

The operator-first control plane is functional. A local browser can submit and
process tasks, approve or reject actions, pause or resume lanes, request
rotation, inspect results, export the audit snapshot, and stop the console.
The console does not decide what work should happen; a planner agent remains a
separate post-pilot decision.

## Shadow pilot

Workspace: `PEPSI VMO`

Runtime and mode: `FakeRuntime`, `shadow`

Verified through the localhost HTTP surface:

- submitted task `d854e015-b140-4832-9655-d065b4599bf9`;
- processing recorded a shadow proposal;
- no agent ID or run ID was created;
- pause changed `Operable Pilot` to `paused`;
- resume returned the lane to `idle`;
- rotation returned `proposed: true`;
- audit export returned the workspace task collection;
- no model executed and no client file was read or written.

## Read-only SDK pilot

Disposable workspace:
`%TEMP%\cursor-orchestrator-pilot`

README.md SHA-256 remained
`58A21F0F6D7505FB22A315CEC3C1E5221353864E3087A38D2E7DEB86535CBE92`
before and after every attempt.

| Task | Result |
|---|---|
| `a98e2a2d-...` | startup fail: missing API key (before key was set) |
| `0860a6f0-...` | first live attempt crashed on `LocalAgentOptions` JSON serialization; later recovered as startup `Network request failed` |
| `c66d510f-...` | after the serialization fix: `Agent.create` reached the Cursor bridge and failed `Network request failed`; no agent ID, no run ID |

Fixes landed in the same session:

- missing API key is a process-start error, not an ambiguous running task;
- SDK `local` options are plain JSON, not `LocalAgentOptions` objects;
- unexpected create/run exceptions mark the task `failed` / `startup` instead of leaving it `running`.

### Root cause of `Network request failed` — resolved 2026-09-02

PwC perimeter security terminates and re-signs TLS. The cursor-sdk bridge is a
Node subprocess, and Node ignores the Windows certificate store, so every
bridge call to Cursor failed `SELF_SIGNED_CERT_IN_CHAIN`. PowerShell reached
`api.cursor.com` normally, which is why the network looked healthy and the
diagnosis initially went the wrong way.

Certificate presented for `api.cursor.com` is issued by
`CN=PwCIssuing-3P-usgpappuv004.pwcglb.com`, `OU=Network Information Security`.

Resolution:

- `tools/export_corp_ca.ps1` exports the PwC roots/intermediates from the
  Windows store to `~/.cursor/corp-ca.pem` (19 certs, local read only).
- `runtime.py::_ensure_bridge_ca_trust()` sets `NODE_EXTRA_CA_CERTS` before
  `launch_bridge` so the Node child inherits the trust bundle.
- `tools/node_tls_check.js` probes Node-side TLS independently.

**End-to-end headless run confirmed (2026-09-02 19:18)** via
`tools/sdk_smoke.py` in a disposable temp workspace:

```
ok  NODE_EXTRA_CA_CERTS -> C:\Users\lpuentes001\.cursor\corp-ca.pem
ok  launch_bridge (local cursor-sdk-bridge is up)
ok  agent created id=agent-564c3be4-2f67-4ad4-b650-dc5b4d131d41
ok  send accepted run_id=run-93c55b78-c652-43e9-8cff-353d5ee97eba
ok  wait status=finished result='3'
RESULT: PASS
```

The result is correct: the probe file contained three lines. Non-empty agent ID
and run ID, terminal status `finished`.

The PEM is a snapshot. Re-run the export script if PwC rotates the CA.

Supervised writes remained disabled until the same non-empty agent ID and run
ID were produced **through the read-only console**, not just the standalone
harness. That console gate passed 2026-09-08 19:30Z on lane `Framework Gate 2`
(task `e7f619b6-...`, agent `agent-41ab6349-...`, run `run-dd92d273-...`), and
was re-proven deterministically on 2026-09-09 — see below. Supervised write is
now unblocked but has never been attempted. The bounded first write is scoped
as `tools/write_gate_check.py`: one file, exact expected contents, approval
gate exercised, and every other file in the workspace fingerprinted before and
after. It needs a console restarted with `--mode supervised` to run.

## Verification

- Full automated suite: 64 tests passed (2026-09-09).
- Console binds only to loopback.
- Invalid request tokens and cross-origin POSTs are rejected.
- Read-only mode rejects write-capable submissions server-side.
- Duplicate submissions with one idempotency key resolve to one task.
- Browser actions marshal onto the coordinator event loop.
- Untrusted task text is escaped in HTML and embedded JSON.
- Lane event histories do not inherit unrelated lane events.

## Lane recovery and a deterministic gate — 2026-09-09

### Startup-failure recovery, proven live

A lane whose agent fails to start now counts consecutive failures on the lane
record and rotates to a fresh agent on the second. Verified through the console
against a scratch lane pointed at an unresumable agent:

| Task | Consecutive failures | Lane behavior | Result |
|---|---|---|---|
| `42da052c-...` | 1 | no rotation, agent unchanged | failed / startup |
| `d58c214b-...` | 2 | rotated, `reason: startup_failure` | completed on `agent-b61eda0a-...` |

The count lives in `lane.config["rotation"]["startup_failure_count"]`, so it
survives a console restart, and any successful agent acquisition clears it.

Caveat on fidelity: the fixture agent ID was unresumable (`Agent ... not found`,
non-retryable, immediate), not the 60s `ReadTimeout` seen on 2026-09-08. Both
reach the policy as a `StartupError` out of `agents.resume` and the code does
not branch on the message, but the timeout variant is unproven live.

### Two findings that reframe the wedged-lane problem

- **Age-based rotation already covers most of it.** `Framework Gate` healed on
  its first task this morning with `reason: active_age` — `active_since` was
  ~19h old against a 4h `max_active_seconds`. The rotation branch runs before
  the resume branch, so the new policy only covers wedges inside that 4h window,
  which is exactly where the 2026-09-08 failures fell.
- **The wedged agent was busy, not unresumable.** After the bridge restart,
  `resume_agent` on `agent-5f606586-...` succeeded; it failed at `send` with
  `already has active run`, and the existing busy-agent retry rotated and
  completed the task. The 60s resume timeout did not reproduce.

### The old gate question was not verifiable

`README.md` in the pilot workspace is 5 lines. Three console runs on 2026-09-09
answered `5`, `8`, and `6`, and one reply ignored the JSON response contract.
A pass on that question proved little.

`tools/gate_check.py` replaces it: it writes a fresh random token into
`gate_fixture.txt` in the workspace, submits a read-only task asking for that
exact value, and asserts the governed reply returns it. Exit code 0 or 1, no
API key needed, console must be running.

Three consecutive runs, exact match and `structured: true` every time:

| Task | Elapsed | Agent | Reply |
|---|---|---|---|
| `4cdc332d-...` | 26.7s | `agent-fea76b4e-...` | exact token |
| `5f0a55fb-...` | 9.6s | `agent-fea76b4e-...` (resumed) | exact token |
| `bdb4c045-...` | 7.1s | `agent-fea76b4e-...` (resumed) | exact token |

Runs 2 and 3 reused the agent through `agents.resume`, so the normal resume
path is confirmed healthy on the same evidence.

### Supervised write, proven live

First agent write ever performed by this system, through the console in
`supervised` mode via `tools/write_gate_check.py`:

| Task | Gate | Result | Blast radius |
|---|---|---|---|
| `df63d1d1-...` | held `awaiting_approval`, `execute`: shared artifact write requires supervised approval | completed on `agent-77f4fb1f-...`, wrote `TOKEN=710dd18...` exactly | no other file touched |
| `d23f9234-...` | same gate, same approval path | completed on the resumed agent, wrote `TOKEN=f73485a...` exactly | no other file touched |

Both runs stopped for approval before writing, wrote only `gate_write.txt`, and
matched the expected contents exactly. Approval was granted through the console
API, not bypassed in code.

Caveat: the pilot workspace holds only 2 other files, so the blast-radius check
is mechanically correct but a thin sample. Re-run it in a workspace with more
files before trusting the write path anywhere real.

## Inbox executability guard — 2026-09-14

### The foot-gun

The `PEPSI VMO` workspace uses the inbox heavily for session-to-session
coordination — messages like "rotate now, your successor picks this up" and
"you are a FRESH lane, not a continuation." Those are instructions to a human
session, not agent work.

But `process()` calls `route_pending_messages()` before it collects the queue,
so every pending message became a queued task and executed in the same cycle.
Any `process` or `serve` run with the SDK runtime against that workspace would
have handed session coordination notes to a headless agent. No agent execution
has ever run in that workspace — every lane shows `current_agent_id: None` —
so nothing was actually executed, but the mechanism was armed.

Separately confirmed **not** a risk: the two `Shadow Pilot` tasks queued since
2026-09-02 both carry a lapsed 3600s TTL, and `process()` expires orphans
before collecting queued work, so they expire rather than run.

### The guard

Messages are coordination by default and cannot become agent work on their own:

- `MessageEnvelope.executable` reads `metadata["executable"]`. Absent means no,
  so mail written before the flag existed is coordination-only. The flag lives
  in metadata rather than a new column, so no schema migration was required.
- `route_pending_messages` still validates the target lane for every pending
  message — an unknown or retired lane dead-letters either way — but only
  routes messages that are explicitly executable.
- `inbox-send --executable` opts in at send time; `inbox-promote` is the
  deliberate step that lets a held message run later.
- Agent proposals are held rather than routed, closing the path where an agent
  schedules the next agent.
- `inbox-ack` closes out mail already actioned in-lane so it stops reading as
  outstanding work to the next session.

Verified against the live `PEPSI VMO` store: of the pending messages, zero
carry the flag, so zero would execute. Suite: 67 passed. All three CLI verbs
smoke-tested end to end against a scratch workspace.

## `serve` and `bootstrap`, first live runs — 2026-09-14

Run against **this orchestrator workspace** — a real workspace with real files
and no engagement content — using `--runtime fake`, so no API key was needed.
Until now every live proof had driven `process` by hand through the console,
leaving the README's "normal long-running control loop" unexercised.

**`bootstrap`** imported 2 lanes (`Framework`, `Orchestrator`) from the
top-level undated handovers, skipped 7 dated archives as `dated_archive`,
reported no conflicts, and exported the registry. Correct on the first run.

**`serve`, bounded** (`--max-cycles 3`): ended `completed`, processed the 1
queued task, wrote a heartbeat carrying pid, cycle count and lock/stop paths,
rendered a 28 KB dashboard, and released the lock on exit.

**`serve`, graceful stop**: with the loop running, `service-status` showed
`state: running` and `lock_exists: true` with cycles incrementing.
`stop-service` wrote the stop file; the service exited, released the lock, and
cleaned up the stop file.

### Defect found and fixed by running it

The stop path recorded a terminal heartbeat of `stopping`, so `service-status`
described a service that had already exited as still shutting down — and did so
indefinitely, since nothing writes again after shutdown. In-loop heartbeats are
hardcoded `running`, so `stopping` never described a live service at all. It is
now `stopped`, matching the vocabulary the operator console already used.
Re-verified live: `running` -> `stopped`, lock released, process exited.

Still unproven: `serve` under the **SDK** runtime, which needs the API key in
the service process, and `bootstrap` against an engagement workspace.

## Dispatch proven end to end on a live agent — 2026-09-16

First run of the full chain with the **SDK** runtime, and the first live SDK run
of `serve` (every earlier live run used the fake runtime or hand-driven
`process`).

Chain: a Brain sent executable mail -> `serve` routed it into a task ->
the coordinator created an agent -> the agent executed and replied through the
governed contract -> `tools/dispatch_status.py` read it back.

| Field | Value |
|---|---|
| Task | `13556b76-f692-447d-b5fa-3ed739425df7` |
| Lane | `Orchestrator` |
| Agent / run | `agent-bc6e9ac6-...` / `run-6ea1db9c-...` |
| Reply | `structured: true`, `status: completed` |
| Evidence | `README.md`, the exact pointer supplied at dispatch |

The objective asked which `python -m orchestrator` subcommands appear in
`README.md`. The answer listed all 22 and stated `Total: 22`, matching the
ground truth derived independently from `cli.py` before the run — including the
three added the same day (`inbox-ack`, `inbox-promote`, `workspaces`).

### Dispatched mail expires

The first attempt produced nothing. The message had been dispatched on
2026-09-14 at 19:59Z with the default 24h TTL and had lapsed to `expired`
before the service started ~49h later; `process()` expires orphans before
collecting queued work. The service was healthy throughout (625 cycles,
`processed_tasks: 0`). **Dispatch assumes a service is running, or will be
within the TTL.** A queued task is not a durable to-do list.

## Planner decision gate

The console is an operator surface, not the main agent. After the read-only SDK
gate passes, decide whether to add a planner lane that accepts one objective,
selects execution lanes, submits bounded tasks, and stops for approval at
material decisions. Do not add it until headless execution is proven useful
enough to justify another reasoning layer.
