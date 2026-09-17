# Superdesign brief — Local Agent Orchestrator dashboard

## Data boundary

Use this brief as the complete design context. Do not request or upload source
code, workspace files, screenshots, client names, client data, task text,
filesystem paths, credentials, or logs. Every name and number below is
synthetic.

The generated artifact is a visual design proposal only. It will not connect
to a database, call an API, execute an agent, or become part of the runtime.

Delivery method: export a self-contained HTML mock plus 2–4 desktop
screenshots (full screen, exception-focused, approval inspector, offline).
The operator will hand those screenshots to a separate local build. Do not
ask to connect Cursor, Superdesign CLI, a repo, or any live system.

## Prompt to paste into Superdesign

Design a desktop operational control-room dashboard for a supervised local
multi-agent orchestrator. The user is a consulting engagement lead who needs
to understand the system in under 30 seconds, intervene in exceptions, and
prove who authorized every material action.

The dashboard is not a chatbot and should not resemble a consumer AI product.
It is an auditable operations console: calm, dense, precise, and
exception-first. Use a neutral enterprise design system with restrained navy,
slate, white, and limited semantic green/amber/red. Do not use a corporate
logo, trademark, client name, gradients, glassmorphism, decorative AI imagery,
or oversized marketing cards.

Create one responsive desktop screen at 1440 × 1000 with these regions:

1. **Global header**
   - Product title: "Local Agent Orchestrator"
   - Environment badge: "Local / Supervised"
   - Workspace selector showing synthetic value "Northwind Operations"
   - Service heartbeat: healthy, last update 12 seconds ago
   - Primary action: "Submit task"
   - Secondary actions: pause service, export audit

2. **Exception strip**
   - Three compact, high-priority items requiring attention:
     - 2 approvals awaiting owner
     - 1 artifact lock conflict
     - 1 lane approaching rotation threshold
   - Each item has severity, age, owner, and one clear action
   - This strip should visually dominate counts that do not require action

3. **Operational summary**
   - 8 active lanes
   - 3 queued tasks
   - 2 active runs
   - 2 pending approvals
   - 1 failed/dead-letter item
   - Show compact metrics, not large vanity cards

4. **Lane control table**
   - Columns: lane, state, current agent, context health, queued/active work,
     artifact claim, last activity, next action
   - Synthetic lanes: Operations, Value Case, UAT Training, Change Orders,
     Demo Build, Automation Research
   - Context health is a labeled meter with thresholds, never color alone
   - One row is "rotation recommended"; one is paused; one is awaiting approval
   - Expandable row reveals prior agent lineage and handover timestamp

5. **Work queue**
   - Filter chips: all, queued, running, awaiting approval, failed
   - Each task shows ID, lane, objective summary, age, permissions, evidence
     count, current agent/run, and status
   - Sensitive permissions use explicit labels: read-only, file write,
     external write, cross-lane merge
   - Approval action must show what will happen, which artifact is affected,
     why approval is required, and approve/reject buttons

6. **Right-side inspector**
   - Opens when a lane/task is selected
   - Tabs: Context envelope, Evidence, Agent lineage, Event trail
   - Context envelope shows objective, canonical source pointers, policies,
     allowed actions, blocked actions, and rotation reason
   - Event trail uses who / what / when / why and distinguishes startup failure
     from run failure

7. **System health footer**
   - Coordinator service state, database backup age, dead-letter count,
     last recovery test, SDK bridge state
   - Include a small note: "Durable state lives outside agent context"

Interaction requirements:

- Make approval and conflict resolution possible without navigating away.
- Use tooltips or helper text for "context health", "artifact claim", and
  "rotation", but keep the default screen concise.
- Keyboard focus, contrast, status text, and table semantics must meet WCAG
  2.2 AA. Do not communicate status by color alone.
- Keep exact timestamps available, while defaulting to human-readable age.
- Support narrow desktop widths without hiding approval state or lane health.
- Include empty, loading, offline, and failed-service states in the component
  design notes, but render the primary screen in a healthy state with the
  exceptions listed above.
- Return self-contained HTML and CSS with no external fonts, trackers,
  analytics, network calls, or runtime dependencies. Icons must be inline SVG
  or CSS and carry accessible labels where needed.

Use this synthetic data in the rendered proposal:

- Lane "Operations": active, agent ag-31F2, health 82%, one active read-only run
- Lane "Value Case": awaiting approval, health 68%, file write to model.xlsx
- Lane "UAT Training": idle, health 94%, no queued work
- Lane "Change Orders": paused, health 77%, two queued tasks
- Lane "Demo Build": rotation recommended, health 41%, prior agents 2
- Lane "Automation Research": failed, startup error, retryable
- Approval A-104: update approved cells in model.xlsx; requested 8 minutes ago
- Approval A-105: send a draft status message externally; requested 3 minutes ago
- Lock conflict: model.xlsx claimed by Value Case; Operations attempted a write

Provide:

1. The complete dashboard design as self-contained HTML.
2. A concise design rationale focused on hierarchy, exception handling,
   auditability, accessibility, and information density.
3. A component inventory and semantic token list.
4. No backend code and no integration instructions.

## Adopted visual baseline

2026-09-02 screenshot stored at
`dashboards/superdesign-baseline.png`. Superdesign was not installed or
wired. The local renderer in `orchestrator/dashboard.py` uses that mock as
layout/hierarchy only and binds live coordinator snapshot data.

## Acceptance gate before implementation

The returned design will be accepted only after:

- all external asset, script, font, analytics, and network references are
  removed; same-machine requests to the console's `127.0.0.1` origin are
  permitted and are not external network integration;
- synthetic content is replaced locally from the orchestrator snapshot;
- output is reviewed for license/provenance, accessibility, security, and
  brand suitability;
- the local renderer remains the only component that reads coordinator state;
- the dashboard still works when the machine is offline;
- automated escaping tests prove task text cannot inject HTML or JavaScript.

The operable console preserves this boundary: it uses a standard-library
loopback server, a per-launch request token, same-origin POST checks, and a
single coordinator event loop. It refuses non-loopback bindings and does not
send dashboard data to Superdesign or any other web service.

