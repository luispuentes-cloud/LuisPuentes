from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .rotation import RotationPolicy

CSS = """
:root {
  --bg: #e8edf3;
  --surface: #ffffff;
  --ink: #1b2430;
  --muted: #5b6775;
  --line: #d5dde6;
  --navy: #1e3a5f;
  --ok: #1f7a4d;
  --ok-bg: #e7f6ee;
  --warn: #b45309;
  --warn-bg: #fff4e5;
  --bad: #b42318;
  --bad-bg: #fdecec;
  --info: #334155;
  --info-bg: #eef2f6;
  --focus: #0f3d6e;
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--ink); }
body {
  font-family: "Segoe UI", system-ui, sans-serif;
  min-height: 100vh;
}
button, .btn {
  font: inherit;
  cursor: pointer;
}
code, .mono { font-family: ui-monospace, Consolas, monospace; }
.app-header {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
  padding: 12px 20px;
}
.brand { display: flex; flex-direction: column; min-width: 220px; }
.brand h1 { margin: 0; font-size: 18px; font-weight: 650; }
.brand .env {
  font-size: 11px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
}
.workspace-select {
  border: 1px solid var(--line);
  background: #f7f9fb;
  border-radius: 8px;
  padding: 8px 12px;
  min-width: 220px;
  color: var(--ink);
  position: relative;
}
.workspace-select summary { cursor: pointer; list-style: none; }
.workspace-list {
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 20;
  margin: 6px 0 0;
  padding: 6px;
  min-width: 320px;
  list-style: none;
  background: var(--surface, #fff);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, .12);
}
.workspace-list li {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  font-size: 12px;
  border-bottom: 1px solid var(--line);
}
.workspace-list li:last-child { border-bottom: 0; }
.ws-counts { margin-left: auto; color: var(--muted); font-size: 11px; }
.header-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-radius: 999px;
  padding: 6px 12px;
  background: var(--ok-bg);
  color: var(--ok);
  font-size: 13px;
  font-weight: 600;
}
.header-status.is-idle { background: var(--info-bg); color: var(--info); }
.header-status.is-down { background: var(--bad-bg); color: var(--bad); }
.dot {
  width: 8px; height: 8px; border-radius: 50%; background: currentColor;
}
.header-actions { margin-left: auto; display: flex; gap: 8px; }
.btn {
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 8px;
  padding: 8px 12px;
  color: var(--ink);
}
.page { padding: 16px 20px 28px; }
.exceptions {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.ex-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-left: 4px solid var(--info);
  border-radius: 10px;
  padding: 12px 14px;
  min-height: 108px;
}
.ex-card.high { border-left-color: var(--bad); background: #fff8f8; }
.ex-card.medium { border-left-color: var(--warn); background: #fffaf3; }
.ex-card.warning { border-left-color: #64748b; }
.ex-kicker {
  font-size: 11px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 4px;
}
.ex-card h2 { margin: 0 0 6px; font-size: 16px; }
.ex-card p { margin: 0; color: var(--muted); font-size: 13px; }
.ex-card .action { display: inline-block; margin-top: 10px; color: var(--focus); font-weight: 600; font-size: 13px; }
.metrics {
  display: flex;
  gap: 0;
  margin: 14px 0 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
}
.metric {
  flex: 1;
  padding: 10px 14px;
  border-right: 1px solid var(--line);
}
.metric:last-child { border-right: 0; }
.metric strong { display: block; font-size: 22px; }
.metric span { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.metric.is-alert strong { color: var(--bad); }
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 14px;
  align-items: start;
}
.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
}
.panel h2, .section-title {
  margin: 0;
  padding: 12px 14px;
  font-size: 12px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
  border-bottom: 1px solid var(--line);
}
table { width: 100%; border-collapse: collapse; }
th, td {
  text-align: left;
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
  vertical-align: middle;
}
th {
  font-size: 11px;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 650;
  background: #f8fafc;
}
tr.is-selected { outline: 2px solid var(--focus); outline-offset: -2px; }
tr[data-select-lane] { cursor: pointer; }
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 650;
  background: var(--info-bg);
}
.pill.active, .pill.ok { background: var(--ok-bg); color: var(--ok); }
.pill.approving, .pill.warn { background: var(--warn-bg); color: var(--warn); }
.pill.critical, .pill.bad { background: var(--bad-bg); color: var(--bad); }
.health { min-width: 120px; }
.health .meta { display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 4px; }
.bar { height: 6px; background: #e2e8f0; border-radius: 99px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: #64748b; }
.bar.ok > span { background: var(--ok); }
.bar.warn > span { background: var(--warn); }
.bar.bad > span { background: var(--bad); }
.action-btn {
  display: inline-block;
  border-radius: 8px;
  padding: 5px 9px;
  background: var(--navy);
  color: #fff;
  font-size: 12px;
  font-weight: 650;
}
.action-link { color: var(--focus); font-weight: 650; }
.inspector { position: sticky; top: 12px; }
.tabs { display: flex; border-bottom: 1px solid var(--line); }
.tabs span {
  padding: 10px 12px;
  font-size: 13px;
  color: var(--muted);
}
.tabs span.is-on {
  color: var(--ink);
  font-weight: 650;
  box-shadow: inset 0 -2px 0 var(--navy);
}
.inspector-body { padding: 12px 14px 16px; }
.inspector-body h3 {
  margin: 14px 0 6px;
  font-size: 11px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
}
.inspector-body h3:first-child { margin-top: 0; }
.obj { margin: 0; font-size: 13px; line-height: 1.45; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag {
  border-radius: 6px;
  padding: 3px 7px;
  font-size: 11px;
  font-weight: 650;
  background: var(--info-bg);
}
.timeline { list-style: none; margin: 0; padding: 0; }
.timeline li {
  position: relative;
  padding: 0 0 12px 16px;
  border-left: 2px solid var(--line);
  font-size: 13px;
}
.timeline li:last-child { border-left-color: transparent; }
.audit { margin-top: 16px; }
.footer {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  color: var(--muted);
  font-size: 12px;
}
.empty { color: var(--muted); padding: 16px; }
.operator {
  margin-bottom: 14px;
  padding: 14px;
}
.operator-grid {
  display: grid;
  grid-template-columns: minmax(360px, 2fr) minmax(260px, 1fr);
  gap: 16px;
}
.operator form { display: grid; gap: 8px; }
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
label { display: grid; gap: 4px; color: var(--muted); font-size: 12px; }
input, textarea, select {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 8px 9px;
  background: #fff;
  color: var(--ink);
  font: inherit;
}
textarea { min-height: 72px; resize: vertical; }
.check { display: flex; align-items: center; gap: 8px; }
.check input { width: auto; }
.operator-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.primary { background: var(--navy); color: #fff; border-color: var(--navy); }
.danger { color: var(--bad); border-color: #efb4b0; }
.status-box {
  min-height: 42px;
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 9px;
  background: #f8fafc;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.result {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 220px;
  overflow: auto;
  padding: 8px;
  border-radius: 7px;
  background: #f8fafc;
  font-size: 12px;
}
.inline-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.hint { margin: 0 0 8px; color: var(--muted); font-size: 12px; }
.small { padding: 4px 7px; font-size: 12px; }
.mode-note { margin: 0; color: var(--muted); font-size: 12px; }
button:focus-visible, input:focus-visible, textarea:focus-visible, select:focus-visible,
tr[data-select-lane]:focus-visible {
  outline: 3px solid #93c5fd;
  outline-offset: 2px;
}
@media (max-width: 1100px) {
  .exceptions { grid-template-columns: 1fr; }
  .layout { grid-template-columns: 1fr; }
  .metrics { flex-wrap: wrap; }
  .metric { min-width: 33%; border-bottom: 1px solid var(--line); }
  .operator-grid { grid-template-columns: 1fr; }
}
"""

JS = """
(function () {
  var token = document.querySelector('meta[name="orchestrator-token"]');
  token = token ? token.content : "";
  var statusBox = document.getElementById("operator-status");
  var actionInFlight = false;

  function announce(message, isError) {
    if (!statusBox) return;
    statusBox.textContent = message;
    statusBox.style.color = isError ? "var(--bad)" : "var(--ink)";
  }

  async function action(name, payload) {
    if (!token) {
      announce("Open the localhost operator console to use controls.", true);
      return null;
    }
    actionInFlight = true;
    announce("Working…", false);
    try {
      var response = await fetch("/api/" + name, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Orchestrator-Token": token
        },
        body: JSON.stringify(payload || {})
      });
      var data = await response.json();
      if (!response.ok) throw new Error(data.error || "Request failed");
      announce(name.replaceAll("_", " ") + " completed.", false);
      return data.result;
    } catch (error) {
      announce(error.message || String(error), true);
      return null;
    } finally {
      actionInFlight = false;
    }
  }

  function selectLane(key) {
    document.querySelectorAll("[data-select-lane]").forEach(function (row) {
      row.classList.toggle("is-selected", row.getAttribute("data-select-lane") === key);
    });
    document.querySelectorAll(".inspector-panel").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-lane") !== key;
    });
    sessionStorage.setItem("orchestrator-selected-lane", key);
  }
  document.querySelectorAll("[data-select-lane]").forEach(function (row) {
    row.addEventListener("click", function () {
      selectLane(row.getAttribute("data-select-lane"));
    });
    row.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectLane(row.getAttribute("data-select-lane"));
      }
    });
  });

  var remembered = sessionStorage.getItem("orchestrator-selected-lane");
  if (remembered && document.querySelector('[data-select-lane="' + CSS.escape(remembered) + '"]')) {
    selectLane(remembered);
  }

  var submit = document.getElementById("submit-task");
  if (submit) {
    submit.addEventListener("submit", async function (event) {
      event.preventDefault();
      var form = new FormData(submit);
      var result = await action("submit", {
        lane: form.get("lane"),
        objective: form.get("objective"),
        artifact: form.get("artifact"),
        evidence: form.get("evidence"),
        idempotency_key: form.get("idempotency_key"),
        write_files: form.get("write_files") === "on"
      });
      if (result) {
        announce("Task " + result.task_id.slice(0, 8) + " queued in " + result.lane_key + ".", false);
        window.setTimeout(function () { location.reload(); }, 700);
      }
    });
  }

  document.addEventListener("click", async function (event) {
    var button = event.target.closest("[data-action]");
    if (!button) return;
    event.stopPropagation();
    var name = button.getAttribute("data-action");
    var payload = {};
    if (button.dataset.lane) payload.lane = button.dataset.lane;
    if (button.dataset.approvalId) payload.approval_id = button.dataset.approvalId;
    if (button.dataset.messageId) payload.message_id = button.dataset.messageId;
    if (name === "promote_message") {
      if (!window.confirm("Promote this message to executable agent work?")) return;
    }
    if (name === "rotate_lane") {
      var objective = window.prompt("Objective for the fresh agent:");
      if (!objective) return;
      payload.objective = objective;
    }
    if (name === "export") {
      var exported = await action(name, payload);
      if (exported) {
        var blob = new Blob([JSON.stringify(exported, null, 2)], {type: "application/json"});
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "orchestrator-audit.json";
        link.click();
        URL.revokeObjectURL(link.href);
      }
      return;
    }
    var result = await action(name, payload);
    if (result !== null && name !== "stop") {
      window.setTimeout(function () { location.reload(); }, 500);
    }
  });

  window.setInterval(function () {
    var tag = document.activeElement && document.activeElement.tagName;
    if (!actionInFlight && !["INPUT", "TEXTAREA", "SELECT"].includes(tag)) {
      location.reload();
    }
  }, 10000);
})();
"""


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age(value: Any, now: datetime | None = None) -> str:
    parsed = _parse_dt(value)
    if parsed is None:
        return "—"
    current = now or datetime.now(timezone.utc)
    seconds = max(0, int((current - parsed).total_seconds()))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _health_pct(score: Any) -> int:
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        numeric = 1.0
    if numeric <= 1:
        return max(0, min(100, round(numeric * 100)))
    return max(0, min(100, round(numeric)))


def _health_band(pct: int) -> tuple[str, str]:
    if pct <= int(RotationPolicy.min_health * 100):
        return "CRITICAL", "bad"
    if pct < 75:
        return "DEGRADING", "warn"
    if pct >= 90:
        return "STABLE", "ok"
    return "NOMINAL", "ok"


def _workspace_label(workspace: str) -> str:
    return Path(str(workspace)).name or str(workspace)


def _tasks_for_lane(tasks: list[dict[str, Any]], lane_key: str) -> list[dict[str, Any]]:
    return [task for task in tasks if task.get("lane_key") == lane_key]


def _lane_work_label(lane_tasks: list[dict[str, Any]]) -> str:
    running = [t for t in lane_tasks if t.get("status") == "running"]
    queued = [t for t in lane_tasks if t.get("status") == "queued"]
    approving = [t for t in lane_tasks if t.get("status") == "awaiting_approval"]
    if running:
        perms = running[0].get("permissions") or {}
        kind = "READ-ONLY RUN" if not perms.get("write_files") else "WRITE RUN"
        return f"{len(running)} {kind}"
    if approving:
        return f"{len(approving)} AWAITING APPROVAL"
    if queued:
        return f"{len(queued)} QUEUED"
    return "—"


def _lane_view_state(lane: dict[str, Any], lane_tasks: list[dict[str, Any]]) -> tuple[str, str]:
    status = str(lane.get("status") or "idle")
    pct = _health_pct(lane.get("context_health_score"))
    if status == "paused":
        return "Paused", "warn"
    if status == "rotating" or pct <= int(RotationPolicy.min_health * 100):
        return "Critical", "bad"
    if any(t.get("status") == "awaiting_approval" for t in lane_tasks):
        return "Approving", "warn"
    if any(t.get("status") in {"failed", "dead_letter"} for t in lane_tasks):
        return "Failed", "bad"
    if status == "active" or any(t.get("status") == "running" for t in lane_tasks):
        return "Active", "ok"
    if status == "retired":
        return "Retired", "warn"
    return "Idle", "info"


def _permission_tags(task: dict[str, Any] | None) -> list[str]:
    if not task:
        return ["NO ACTIVE TASK"]
    perms = task.get("permissions") or {}
    tags: list[str] = []
    if perms.get("read") and not perms.get("write_files"):
        tags.append("STRICT READ-ONLY FS")
    if perms.get("write_files"):
        tags.append("FILE WRITE")
    if perms.get("external_write"):
        tags.append("EXTERNAL WRITE")
    if perms.get("cross_lane_merge"):
        tags.append("CROSS-LANE MERGE")
    if perms.get("write_files") or perms.get("external_write") or perms.get("destructive"):
        tags.append("APPROVAL REQUIRED")
    tags.append("LOGGING: TRACE")
    return tags


def _safe_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str).replace("<", "\\u003c").replace(">", "\\u003e")


def _workspace_menu(
    workspaces: list[dict[str, Any]] | None,
    active: str,
) -> str:
    """Header menu listing every known workspace, active one marked.

    The console still runs one workspace per process — this is visibility
    across clients, not a live switch, so isolation stays structural.
    """
    if not workspaces:
        return (
            f'<div class="workspace-select" title="{_esc(active)}">'
            f"{_esc(_workspace_label(active))}</div>"
        )
    items = []
    for entry in workspaces:
        path = str(entry.get("workspace") or entry.get("workspace_hash") or "?")
        is_active = os.path.normcase(path) == os.path.normcase(str(active))
        waiting = (
            int(entry.get("queued") or 0)
            + int(entry.get("awaiting_approval") or 0)
            + int(entry.get("pending_messages") or 0)
        )
        marks = []
        if is_active:
            marks.append('<span class="pill ok">active</span>')
        elif entry.get("live"):
            marks.append('<span class="pill">console up</span>')
        if entry.get("awaiting_approval"):
            marks.append(
                f'<span class="pill warn">{int(entry["awaiting_approval"])} to approve</span>'
            )
        if entry.get("error"):
            marks.append('<span class="pill bad">unreadable</span>')
        items.append(
            f'<li><span class="mono">{_esc(_workspace_label(path))}</span>'
            f'{"".join(marks)}'
            f'<span class="ws-counts">{int(entry.get("lanes") or 0)} lanes · '
            f"{waiting} waiting</span></li>"
        )
    return f"""<details class="workspace-select">
      <summary title="{_esc(active)}">{_esc(_workspace_label(active))}</summary>
      <ul class="workspace-list">{"".join(items)}</ul>
    </details>"""


def render_dashboard_html(
    snapshot: dict[str, Any],
    *,
    console_token: str | None = None,
    workspaces: list[dict[str, Any]] | None = None,
) -> str:
    lanes = list(snapshot.get("lanes") or [])
    tasks = list(snapshot.get("tasks") or [])
    approvals = [a for a in snapshot.get("approvals") or [] if a.get("status") == "pending"]
    claims = list(snapshot.get("claims") or [])
    events = list(snapshot.get("events") or [])
    messages = list(snapshot.get("messages") or [])
    metrics = list(snapshot.get("metrics") or [])
    heartbeat = dict(snapshot.get("heartbeat") or {})
    shadow_proposals = [
        task
        for task in tasks
        if task.get("status") == "queued" and task.get("metadata", {}).get("shadow_proposed_at")
    ]
    queued = [task for task in tasks if task.get("status") == "queued" and task not in shadow_proposals]
    active = [task for task in tasks if task.get("status") == "running"]
    failures = [
        task for task in tasks if task.get("status") in {"failed", "dead_letter", "expired"}
    ]
    dead_letters = failures + [m for m in messages if m.get("status") == "dead_letter"]
    rotation_lanes = [
        lane
        for lane in lanes
        if _health_pct(lane.get("context_health_score")) <= int(RotationPolicy.min_health * 100)
        or lane.get("status") == "rotating"
        or int((lane.get("config") or {}).get("rotation", {}).get("run_count") or 0)
        >= RotationPolicy.max_runs
    ]

    workspace = str(snapshot.get("workspace") or "")
    mode = str(snapshot.get("mode") or "supervised")
    hb_state = str(heartbeat.get("state") or "")
    if hb_state == "running":
        service_label = f"Service Healthy · {_age(heartbeat.get('updated_at'))}"
        service_class = ""
    elif hb_state:
        service_label = f"Service {hb_state} · {_age(heartbeat.get('updated_at'))}"
        service_class = "is-idle"
    else:
        service_label = "Service idle · no heartbeat"
        service_class = "is-idle"

    exception_cards: list[str] = []
    if approvals:
        preview = approvals[0]
        exception_cards.append(
            f"""<article class="ex-card high"><div class="ex-kicker">High severity</div>
            <h2>Approvals Awaiting ({len(approvals)})</h2>
            <p>{_esc(preview.get('action') or 'Owner authorization required')} — {_esc(preview.get('reason') or '')}</p>
            <span class="action">Review Queue</span></article>"""
        )
    if claims:
        claim = claims[0]
        exception_cards.append(
            f"""<article class="ex-card medium"><div class="ex-kicker">Medium severity</div>
            <h2>Artifact Lock Conflict</h2>
            <p><span class="mono">{_esc(Path(str(claim.get('artifact_path') or '')).name)}</span>
            claimed by {_esc(claim.get('lane_key'))}. Age {_esc(_age(claim.get('acquired_at')))}.</p>
            <span class="action">Resolve Conflict</span></article>"""
        )
    if rotation_lanes:
        lane = rotation_lanes[0]
        pct = _health_pct(lane.get("context_health_score"))
        exception_cards.append(
            f"""<article class="ex-card warning"><div class="ex-kicker">Warning</div>
            <h2>Lane Rotation Limit</h2>
            <p>{_esc(lane.get('lane_key'))} context health is {pct}% and requires agent rotation.</p>
            <span class="action">Rotate Agent</span></article>"""
        )
    if not exception_cards:
        exception_cards.append(
            """<article class="ex-card"><div class="ex-kicker">Exceptions</div>
            <h2>No exceptions requiring attention</h2>
            <p>Approvals, locks, and rotation thresholds are clear.</p></article>"""
        )
    while len(exception_cards) < 3:
        exception_cards.append(
            """<article class="ex-card"><div class="ex-kicker">Clear</div>
            <h2>No additional alerts</h2>
            <p>Counts below do not require operator action.</p></article>"""
        )

    selected = next(
        (
            lane.get("lane_key")
            for lane in lanes
            if any(t.get("lane_key") == lane.get("lane_key") and t.get("status") == "awaiting_approval" for t in tasks)
            or any(c.get("lane_key") == lane.get("lane_key") for c in claims)
            or lane in rotation_lanes
        ),
        lanes[0]["lane_key"] if lanes else "",
    )

    lane_rows = []
    inspector_panels = []
    for lane in lanes:
        key = str(lane.get("lane_key") or "")
        lane_tasks = _tasks_for_lane(tasks, key)
        state_label, state_mod = _lane_view_state(lane, lane_tasks)
        pct = _health_pct(lane.get("context_health_score"))
        band, band_mod = _health_band(pct)
        rotating = lane in rotation_lanes
        agent = lane.get("current_agent_id") or ("ROTATION REQ." if rotating else "—")
        claim = next((c for c in claims if c.get("lane_key") == key), None)
        claim_name = Path(str(claim.get("artifact_path"))).name if claim else "—"
        if rotating:
            action = (
                f'<button class="action-btn" type="button" data-action="rotate_lane" '
                f'data-lane="{_esc(key)}">Rotate Now</button>'
            )
        elif any(t.get("status") == "awaiting_approval" for t in lane_tasks):
            action = '<span class="action-link">Review Task</span>'
        elif lane.get("status") == "paused":
            action = (
                f'<button class="btn small" type="button" data-action="resume_lane" '
                f'data-lane="{_esc(key)}">Resume</button>'
            )
        else:
            action = (
                f'<button class="btn small" type="button" data-action="pause_lane" '
                f'data-lane="{_esc(key)}">Pause</button>'
            )
        selected_class = " is-selected" if key == selected else ""
        lane_rows.append(
            f"""<tr class="{selected_class.strip()}" data-select-lane="{_esc(key)}" tabindex="0">
            <td>{_esc(key)}</td>
            <td><span class="pill {state_mod}">{_esc(state_label)}</span></td>
            <td class="mono">{_esc(agent)}</td>
            <td class="health"><div class="meta"><span>{_esc(band)}</span><span>{pct}%</span></div>
            <div class="bar {band_mod}"><span style="width:{pct}%"></span></div></td>
            <td>{_esc(_lane_work_label(lane_tasks))}</td>
            <td class="mono">{_esc(claim_name)}</td>
            <td>{_esc(_age(lane.get('last_activity')))}</td>
            <td>{action}</td></tr>"""
        )
        latest = next((t for t in lane_tasks if t.get("status") in {"running", "awaiting_approval", "queued"}), None)
        if not latest and lane_tasks:
            latest = sorted(lane_tasks, key=lambda t: t.get("updated_at") or "", reverse=True)[0]
        sources = []
        if latest:
            for artifact in latest.get("artifacts") or []:
                sources.append(f"<li class='mono'>{_esc(Path(str(artifact)).name)}</li>")
        if lane.get("handover_path"):
            sources.append(f"<li class='mono'>{_esc(Path(str(lane['handover_path'])).name)}</li>")
        tags = "".join(f"<span class='tag'>{_esc(tag)}</span>" for tag in _permission_tags(latest))
        lane_entity_ids = {key} | {str(t.get("task_id")) for t in lane_tasks}
        lane_events = [
            e for e in events if str(e.get("entity_id") or "") in lane_entity_ids
        ]
        timeline = "".join(
            f"<li><strong>{_esc(e.get('event_type'))}</strong><div class='mono'>{_esc(e.get('entity_id') or '—')} · {_esc(_age(e.get('created_at')))}</div></li>"
            for e in lane_events[:6]
        ) or "<li>No events for this lane</li>"
        prior = ", ".join(lane.get("prior_agent_ids") or []) or "—"
        latest_metadata = (latest or {}).get("metadata") or {}
        response = latest_metadata.get("agent_response") or {}
        result_summary = response.get("summary") or (latest or {}).get("error_message") or "No result yet"
        result_status = response.get("status") or (latest or {}).get("status") or "idle"
        origin_label = "dispatched" if latest_metadata.get("source_message_id") else "operator"
        if not response:
            reply_label, reply_mod = "no reply yet", ""
        elif response.get("structured"):
            reply_label, reply_mod = "governed reply", "ok"
        else:
            # Prose instead of the response contract. It still reads like a
            # confident answer, so the panel has to say nothing validated it.
            reply_label, reply_mod = "unverified reply", "bad"
        evidence_items = "".join(
            f"<li class='mono'>{_esc(str(pointer))}</li>"
            for pointer in (
                response.get("evidence") or (latest or {}).get("evidence") or []
            )
        ) or "<li>None cited</li>"
        run_identity = " · ".join(
            value
            for value in [
                str((latest or {}).get("agent_id") or ""),
                str((latest or {}).get("run_id") or ""),
            ]
            if value
        ) or "—"
        inspector_panels.append(
            f"""<div class="inspector-panel" data-lane="{_esc(key)}" {"hidden" if key != selected else ""}>
            <div class="tabs"><span class="is-on">Context</span><span>Evidence</span><span>Logs</span></div>
            <div class="inspector-body">
              <p class="obj">Lane: {_esc(key)}</p>
              <h3>Objective</h3>
              <p class="obj">{_esc((latest or {}).get("objective") or "No active objective")}</p>
              <h3>Result · {_esc(result_status)}</h3>
              <p class="mono">{_esc(run_identity)}</p>
              <div class="result">{_esc(result_summary)}</div>
              <div class="tags"><span class="pill">{_esc(origin_label)}</span><span class="pill {reply_mod}">{_esc(reply_label)}</span></div>
              <h3>Evidence Cited</h3>
              <ul>{evidence_items}</ul>
              <h3>Canonical Sources</h3>
              <ul>{"".join(sources) or "<li>None listed</li>"}</ul>
              <h3>Policies &amp; Permissions</h3>
              <div class="tags">{tags}</div>
              <h3>Prior Agents</h3>
              <p class="mono">{_esc(prior)}</p>
              <h3>Action History</h3>
              <ol class="timeline">{timeline}</ol>
            </div></div>"""
        )

    task_row_list = []
    for t in tasks:
        status_label = "queued (shadow proposal)" if t in shadow_proposals else t["status"]
        origin_pill = (
            "<span class='pill'>dispatched</span> "
            if (t.get("metadata") or {}).get("source_message_id")
            else ""
        )
        task_row_list.append(
            f"<tr><td class='mono'>{_esc(t['task_id'][:8])}</td><td>{_esc(t['lane_key'])}</td>"
            f"<td>{_esc(status_label)}</td>"
            f"<td>{origin_pill}{_esc(t['objective'])}</td>"
            f"<td>{_esc(t.get('agent_id') or '-')}</td></tr>"
        )
    task_rows = "".join(task_row_list)
    approval_rows = "".join(
        f"<tr><td class='mono'>{_esc(a['approval_id'][:8])}</td><td>{_esc(a['lane_key'])}</td>"
        f"<td>{_esc(a['action'])}</td><td>{_esc(a['reason'])}</td>"
        f"<td><div class='inline-actions'>"
        f"<button class='btn small primary' type='button' data-action='approve' "
        f"data-approval-id='{_esc(a['approval_id'])}'>Approve</button>"
        f"<button class='btn small danger' type='button' data-action='reject' "
        f"data-approval-id='{_esc(a['approval_id'])}'>Reject</button>"
        f"</div></td></tr>"
        for a in approvals
    )
    claim_rows = "".join(
        f"<tr><td class='mono'>{_esc(c['artifact_path'])}</td><td>{_esc(c['lane_key'])}</td>"
        f"<td>{'yes' if c.get('write_capable') else 'no'}</td></tr>"
        for c in claims
    )
    event_rows = "".join(
        f"<tr><td>{_esc(e['created_at'])}</td><td>{_esc(e['event_type'])}</td>"
        f"<td class='mono'>{_esc(e.get('entity_id') or '-')}</td></tr>"
        for e in events[:30]
    )
    message_row_list = []
    for m in messages:
        executable = bool((m.get("metadata") or {}).get("executable"))
        kind = (
            '<span class="pill warn">executable</span>'
            if executable
            else '<span class="pill">coordination</span>'
        )
        actions = ""
        if m["status"] == "pending" and console_token:
            if not executable:
                actions += (
                    "<button class='btn small' type='button' "
                    "data-action='promote_message' "
                    f"data-message-id='{_esc(m['message_id'])}'>Promote</button>"
                )
            actions += (
                "<button class='btn small' type='button' "
                "data-action='acknowledge_message' "
                f"data-message-id='{_esc(m['message_id'])}'>Actioned</button>"
            )
        message_row_list.append(
            f"<tr><td class='mono'>{_esc(m['message_id'][:8])}</td>"
            f"<td>{_esc(m['target'])}</td>"
            f"<td>{kind}</td>"
            f"<td>{_esc(m['status'])}</td><td>{_esc(m['objective'])}</td>"
            f"<td><div class='inline-actions'>{actions}</div></td></tr>"
        )
    message_rows = "".join(message_row_list)
    metric_rows = "".join(
        f"<tr><td>{_esc(m['name'])}</td><td>{_esc(m['value'])}</td>"
        f"<td class='mono'>{_esc(json.dumps(m.get('labels', {}), sort_keys=True))}</td>"
        f"<td>{_esc(m['recorded_at'])}</td></tr>"
        for m in metrics[-50:]
    )
    failure_rows = "".join(
        f"<tr><td class='mono'>{_esc(t['task_id'][:8])}</td><td>{_esc(t['lane_key'])}</td>"
        f"<td>{_esc(t['status'])}</td><td>{_esc(t.get('failure_kind') or '-')}</td>"
        f"<td>{_esc(t.get('error_message') or '-')}</td></tr>"
        for t in failures
    )

    backups = snapshot.get("backups") or []
    backup_note = Path(str(backups[-1])).name if backups else "none"
    active_lanes = [lane for lane in lanes if lane.get("status") != "retired"]
    lane_options = "".join(
        f'<option value="{_esc(lane.get("lane_key"))}"></option>' for lane in lanes
    )
    controls_disabled = "" if console_token else " disabled"
    console_note = (
        "Controls are live. Changes are local and auditable."
        if console_token
        else "Static snapshot. Start the localhost console to operate."
    )

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="orchestrator-token" content="{_esc(console_token or '')}" />
  <title>Local Agent Orchestrator</title>
  <style>{CSS}</style>
</head>
<body>
  <header class="app-header">
    <div class="brand">
      <h1>Local Agent Orchestrator</h1>
      <div class="env">Local / {_esc(mode)}</div>
    </div>
    {_workspace_menu(workspaces, workspace)}
    <div class="header-status {service_class}"><span class="dot" aria-hidden="true"></span>{_esc(service_label)}</div>
    <div class="header-actions">
      <button class="btn" type="button" data-action="export"{controls_disabled}>Export Audit Log</button>
      <button class="btn danger" type="button" data-action="stop"{controls_disabled}>Stop Console</button>
    </div>
  </header>
  <main class="page">
    <section class="panel operator" aria-labelledby="operator-heading">
      <h2 id="operator-heading">Operator Controls</h2>
      <div class="operator-grid">
        <form id="submit-task">
          <div class="form-grid">
            <label>Lane
              <input name="lane" list="lane-list" maxlength="200" required{controls_disabled} />
              <datalist id="lane-list">{lane_options}</datalist>
            </label>
            <label>Idempotency key
              <input name="idempotency_key" maxlength="300" required value="pilot-{len(tasks) + 1}"{controls_disabled} />
            </label>
          </div>
          <label>Objective
            <textarea name="objective" maxlength="20000" required{controls_disabled}></textarea>
          </label>
          <div class="form-grid">
            <label>Evidence pointer
              <input name="evidence" maxlength="2048"{controls_disabled} />
            </label>
            <label>Artifact
              <input name="artifact" maxlength="2048"{controls_disabled} />
            </label>
          </div>
          <div class="operator-actions">
            <label class="check"><input type="checkbox" name="write_files"{controls_disabled} /> File write</label>
            <button class="btn primary" type="submit"{controls_disabled}>Submit Task</button>
            <button class="btn" type="button" data-action="process"{controls_disabled}>Process Queue</button>
            <button class="btn" type="button" onclick="location.reload()">Refresh</button>
          </div>
        </form>
        <div>
          <p class="mode-note">Mode: <strong>{_esc(mode)}</strong>. {_esc(console_note)}</p>
          <h3>Operator status</h3>
          <div id="operator-status" class="status-box" role="status" aria-live="polite">Ready.</div>
          <p class="mode-note">Pause takes effect before the lane's next queued task; it does not cancel an in-flight run.</p>
        </div>
      </div>
    </section>
    <section class="exceptions" aria-label="Exceptions">{"".join(exception_cards[:3])}</section>
    <section class="metrics" aria-label="System state">
      <div class="metric"><strong>{len(active_lanes)}</strong><span>Active lanes</span></div>
      <div class="metric"><strong>{len(queued)}</strong><span>Queued work</span></div>
      <div class="metric"><strong>{len(shadow_proposals)}</strong><span>Queued shadow proposals</span></div>
      <div class="metric"><strong>{len(active)}</strong><span>Active runs</span></div>
      <div class="metric"><strong>{len(approvals)}</strong><span>Pending approvals</span></div>
      <div class="metric{" is-alert" if dead_letters else ""}"><strong>{len(dead_letters)}</strong><span>Dead-letter</span></div>
    </section>
    <div class="layout">
      <section class="panel">
        <h2>Lane Control Grid</h2>
        <table>
          <thead><tr>
            <th>Lane</th><th>State</th><th>Current Agent</th><th>Context Health</th>
            <th>Work</th><th>Artifact Claim</th><th>Last Activity</th><th>Actions</th>
          </tr></thead>
          <tbody>{"".join(lane_rows) or '<tr><td colspan="8" class="empty">No lanes</td></tr>'}</tbody>
        </table>
      </section>
      <aside class="panel inspector" aria-label="Inspector">
        <h2>Inspector</h2>
        {"".join(inspector_panels) or '<p class="empty">No lane selected</p>'}
      </aside>
    </div>
    <section class="panel audit">
      <h2>Pending Approvals</h2>
      <table><thead><tr><th scope="col">ID</th><th scope="col">Lane</th><th scope="col">Action</th><th scope="col">Reason</th><th scope="col">Decision</th></tr></thead>
      <tbody>{approval_rows or '<tr><td colspan="5">None</td></tr>'}</tbody></table>
    </section>
    <section class="panel audit">
      <h2>Work Queue</h2>
      <table><thead><tr><th>ID</th><th>Lane</th><th>Status</th><th>Objective</th><th>Agent</th></tr></thead>
      <tbody>{task_rows or '<tr><td colspan="5">No tasks</td></tr>'}</tbody></table>
    </section>
    <section class="panel audit">
      <h2>Artifact Claims</h2>
      <table><thead><tr><th>Artifact</th><th>Lane</th><th>Write</th></tr></thead>
      <tbody>{claim_rows or '<tr><td colspan="3">None</td></tr>'}</tbody></table>
    </section>
    <section class="panel audit">
      <h2>Failures and Dead Letters</h2>
      <table><thead><tr><th>ID</th><th>Lane</th><th>Status</th><th>Kind</th><th>Error</th></tr></thead>
      <tbody>{failure_rows or '<tr><td colspan="5">None</td></tr>'}</tbody></table>
    </section>
    <section class="panel audit">
      <h2>Messages and Dead Letters</h2>
      <p class="hint">Coordination mail never executes. Promote only work that meets the dispatch contract.</p>
      <table><thead><tr><th>ID</th><th>Target</th><th>Kind</th><th>Status</th><th>Objective</th><th>Action</th></tr></thead>
      <tbody>{message_rows or '<tr><td colspan="6">None</td></tr>'}</tbody></table>
    </section>
    <section class="panel audit">
      <h2>Metrics</h2>
      <table><thead><tr><th>Name</th><th>Value</th><th>Labels</th><th>Recorded</th></tr></thead>
      <tbody>{metric_rows or '<tr><td colspan="4">None</td></tr>'}</tbody></table>
    </section>
    <section class="panel audit">
      <h2>Recent Events</h2>
      <table><thead><tr><th>Time</th><th>Type</th><th>Entity</th></tr></thead>
      <tbody>{event_rows or '<tr><td colspan="3">None</td></tr>'}</tbody></table>
    </section>
    <footer class="footer">
      <span>Coordinator: {_esc(hb_state or "idle")}</span>
      <span>Backup: {_esc(backup_note)}</span>
      <span>Dead-letter count: {len(dead_letters)}</span>
      <span>Mode: {_esc(mode)}</span>
      <span>Durable state lives outside agent context</span>
    </footer>
  </main>
  <script>window.__ORCH_SNAPSHOT__ = {_safe_json(snapshot)};</script>
  <script>{JS}</script>
</body>
</html>
"""
    return content


def render_dashboard(snapshot: dict[str, Any], output_path: Path) -> Path:
    content = render_dashboard_html(snapshot)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path
