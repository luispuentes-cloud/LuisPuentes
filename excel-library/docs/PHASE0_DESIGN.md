# Phase 0 Design — Standalone Linter

**Status:** design folded with owner rulings of 2026-09-16. Phase 0
implementation and hardening are in `src/xllib/` and `tests/`. ADRs 0001, 0002
and 0004 are Accepted; ADR-0003 remains Proposed until Phase 1 generation exists.
**Covers:** kickoff deliverables 1, 4, 5. Deliverable 2 and 3 are in
`PHASE0_CHALLENGE.md`; deliverable 7 in `PHASE0_FIXTURES.md`.

---

## 1. Mission and the layer boundary, restated

### Mission

A workbook is compiled from a declarative spec, and the properties that make it
auditable are expressed as executable checks rather than documented conventions.
The spec is the source; the `.xlsx` is an artifact. Where a property cannot be
checked, it is not a property of this system — it is an aspiration, and saying so
out loud is part of the job.

### Where my restatement differs from GOAL.md

Three differences. Per the kickoff, these are the useful output.

**(a) "Correctness" is not in scope and should not be claimed.** GOAL says
readability and correctness are enforced mechanically at every boundary. The
library can enforce *structural legibility* and *declared invariants*. It cannot
enforce that the denominator is the right denominator, that the benefit lines are
the right benefit lines, or that a scenario means what its label says. Those are
model-correctness questions and no linter reaches them.

This matters beyond wording. A tool that reports "PASS" on a workbook whose
arithmetic is legible and wrong will be read as certification. Phase 0 should
therefore never emit the word "pass" unqualified — it reports which rules were
evaluated, which were violated, and which could not be evaluated. GOAL's own
principle that a tool cannot certify its own blind spot applies to this tool.

**(b) The layer test should be "would this package make sense standing alone",
not "does a domain noun appear".** GOAL says a domain noun in core is a bug. The
noun test is cheap and evadable: rename `benefit_line` to `metric_line` and the
same semantics are smuggled in with a clean grep. The stronger test is whether
`src/xllib/inspect/` and `src/xllib/lint/` could be published as a general
spreadsheet-inspection package, with no consulting context, and still be
coherent.

Corollary that is worth stating because it looks like a violation and is not:
core may know about *shapes* — a range with a period axis, a walk, a check cell —
but never about what the numbers mean. "Period axis" is a spreadsheet shape.
"Benefit realisation month" is a domain concept. Rule XL006 sits on the right
side of that line only because it checks alignment of a declared axis, not the
meaning of the periods.

**(c) The boundary should be a test, not a paragraph.** GOAL's founding
observation is that prose drifts. That applies to the layer boundary itself.
`tests/test_boundary.py` asserts that no term from a maintained domain-noun list
appears under the core packages, and fails CI when it does. The noun test is weak
as a *definition* and fine as a *ratchet*; it catches the lazy violation while the
review catches the smuggled one.

### The boundary in one line

`inspect/` and `lint/` know about cells, formulas, ranges, styles and references.
`presets/*.yaml` know about value cases. Nothing in between knows both.

---

## 2. Repo structure (Phase 0 only)

```
excel-library/
  pyproject.toml              # uv-managed. Runtime deps: openpyxl + formulas
  README.md                   # what it is; how to run; how to read a finding
  BACKLOG.md                  # deferred non-goals, each with a pickup trigger
  xllib.toml                  # default config, committed
  docs/
    adr/                      # 0001–0004
    PHASE0_DESIGN.md          # this file
    PHASE0_CHALLENGE.md       # where GOAL.md is wrong or unbuildable as written
    PHASE0_FIXTURES.md        # fixture spec, one per rule
    rules/                    # one page per rule, written as each rule lands
  src/xllib/
    __init__.py
    inspect/                  # read-side substrate. Knows nothing about linting.
      model.py                # Workbook / Sheet / Cell / DefinedName dataclasses
      load.py                 # dual openpyxl load: formulas + cached values
      tokens.py               # tokenizer walk: nesting depth, arg index, literals
      refs.py                 # reference graph; cross-sheet and external edges
      spans.py                # documented heuristics: runs, columns, header rows
      capability.py           # what this loaded workbook can actually support
    recalc/                   # Phase 0. RecalcBackend protocol + three backends
      api.py                  # recalc(path) -> temp copy with cached values
      backends/
        formulas.py           # default; Linux CI path
        libreoffice.py        # fallback; UNO calculateAll()
        excel_com.py          # last; Visible=False, DisplayAlerts=False
    lint/                     # the only Layer 2 service in Phase 0 besides recalc
      api.py                  # lint(workbook, config) -> Report
      rule.py                 # Rule, Finding, Severity, Status, Confidence
      registry.py             # explicit registration and discovery
      config.py               # layered config, thresholds, waivers
      report.py               # JSON and text renderers
      rules/__init__.py       # explicit registry; all ten RULE constants here
    cli.py                    # xllib lint PATH [--json] [--measure] [--config]
  tests/
    fixtures/
      build_fixtures.py       # generates fixture workbooks at test time
    test_rules.py             # violating + clean fixture per rule
    test_inspect_load.py
    test_inspect_tokens.py
    test_inspect_refs.py
    test_inspect_spans.py
    test_recalc.py
    test_recalc_core.py       # live formulas + Excel COM (COM skipped off Windows)
    test_lint_framework.py    # including JSON findings byte-stability
    test_machinery.py
    test_complete_sets.py
    test_cli.py
    test_boundary.py          # domain nouns absent from core packages
  .github/workflows/ci.yml    # ubuntu-latest; ruff, mypy, pytest. formulas, no Excel.
                              # Assumes excel-library/ is the git root.
```

### Where later phases attach without a rewrite

| Phase | Adds | Touches Phase 0? |
|---|---|---|
| 1 — spec to workbook | `spec/` (schema), `ir/` (generation IR), `render/` (emitter), explicit sheet manifest | No. `ir` gains `to_inspection()` so Phase 1's acceptance test calls the existing `lint.api.lint()` unmodified. Tabs are declared and confirmed before anything is generated (Q3). |
| 1 — generation-time checks | `chk_*` names emitted with every Checks block | No. The convention Phase 0 lints is produced by construction. |
| 2 — elicitation | `elicit/` (fixed question set, deterministic answer-to-constraint table, pre-build sheet-list confirmation) | No. |
| 3 — intake | `intake/`, which consumes `inspect/` directly | No. This is the reason `inspect/` is a sibling of `lint/` rather than a private module inside it. |
| 3 — domain presets | `presets/*.yaml` at repo root | No, and by construction cannot. |

The load-bearing decision is separating `inspect/` from `lint/` on day one. It
costs one package boundary now and is what lets intake, generation-time checking,
and the CLI share one reader later.

---

## 3. Rule interface

### Declaration

A rule is a frozen dataclass instance exposing a callable, not a subclass. There
is no rule base class and no inheritance.

```python
@dataclass(frozen=True, slots=True)
class Rule:
    id: str                            # "XL004", stable forever
    slug: str                          # "text-in-numeric-cell"
    title: str
    default_severity: Severity         # ERROR | WARN
    confidence: Confidence             # CERTAIN | HEURISTIC
    requires: frozenset[Capability]    # CACHED_VALUES, NUMBER_FORMATS, ...
    thresholds: Mapping[str, int]      # declared defaults, overridable by config
    check: Callable[[Workbook, RuleContext], Iterable[Finding]]
    doc: str                           # docs/rules/XL004.md
```

`confidence` is declared on the rule, not derived at runtime, and is my addition
to GOAL. Three of the ten Phase 0 rules depend on inferred spans, columns or
header rows. A finding must state on its face whether it is a fact about the file
or an inference about intent, because the first unexplained false positive is what
discredits the tool and gets it routed around.

`requires` is the other structural element. A rule declares the capabilities it
needs; the runner computes what the loaded workbook actually supplies; a rule
whose needs are unmet returns `Status.SKIPPED` with a reason and never silently
passes. A workbook written by openpyxl and never opened in Excel has no cached
values, so every value-dependent rule must skip rather than report clean.

### Registration

An explicit registry. `lint/rules/__init__.py` imports each rule module and
collects its `RULE` constant into an ordered tuple. Discovery is by iterating that
tuple.

Deliberately *not* entry-point plugin discovery: an installed third-party package
could change the rule set, which makes a report non-reproducible and breaks the
byte-stability test the report needs. Revisit only if rules ever ship separately.

### Configuration

Layered, lowest precedence first: built-in rule defaults, then `xllib.toml` in the
repo, then CLI flags. Per rule: `severity`, `thresholds`, and `waivers`.

Two constraints that exist to stop config becoming the route-around:

- A rule at `ERROR` by default may be raised or left alone. Setting it to `off`
  or `warn` requires a matching waiver entry. Severity is not a free dial.
- A waiver must carry `rule`, `scope`, `reason`, `approver`, `expires`. CI fails
  on any waiver with an empty `approver` or a past `expires`. Per GOAL, the agent
  never grants a waiver; requiring a named human approver in a committed file is
  the mechanical form of that rule.

### Reporting

```python
@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    status: Status                  # VIOLATION | SKIPPED | INFO
    severity: Severity
    confidence: Confidence
    message: str                    # one line, names the locus, no trailing period
    locus: Locus                    # sheet + ref/range/column/defined-name, or workbook
    evidence: Mapping[str, str]     # rule-specific, JSON-safe: formula, inferred run, ...
    remediation: str                # what to do, not why it is wrong
    waiver: Waiver | None
```

`evidence` carries the inferred span for heuristic rules. A false positive on
XL003 is only diagnosable if the report states which run it inferred.

#### Machine-readable output (`--json`)

```json
{
  "schema_version": "1.0",
  "tool": { "name": "xllib", "version": "0.1.0" },
  "target": {
    "path": "...", "sha256": "...", "loaded_at": "2026-09-16T18:55:00Z",
    "capabilities": ["FORMULA_TOKENS", "NUMBER_FORMATS", "REF_GRAPH"],
    "missing_capabilities": ["CACHED_VALUES"]
  },
  "config": { "sources": ["builtin", "xllib.toml"], "thresholds": {} },
  "summary": {
    "error": 3, "warn": 5, "skipped": 2,
    "rules_total": 10, "rules_evaluated": 8, "exit_code": 1
  },
  "rules": [ { "id": "XL004", "status": "VIOLATION", "findings": 2 } ],
  "findings": [ { "rule_id": "XL004", "...": "..." } ]
}
```

Findings are sorted by `(rule_id, sheet_index, row, column)` with stable key
order, and no timestamp appears inside `findings` — only in `target`. Two runs
against the same file therefore produce a byte-identical `findings` block, which
is what makes golden-master testing of the linter itself possible.

#### Human-readable output (default)

Grouped by sheet, then rule. One line per finding:

```
Calc!D7      XL002  numeric literal 0.85 in formula; declare it as an input
Calc!D4:G4 ~ XL003  2 formula shapes in inferred run D4:G4
Summary      XL102  no check convention found in this workbook

  8 of 10 rules evaluated   3 error   5 warn
  2 rules skipped: every recalc backend failed
  ~ marks a heuristic finding: verify the inferred range before acting
  exit 2
```

#### Exit code contract

| Code | Meaning |
|---|---|
| 0 | Every applicable rule evaluated; no ERROR findings; nothing skipped |
| 1 | At least one ERROR finding |
| 2 | No ERROR findings, but one or more rules could not be evaluated |
| 3 | Usage error, unreadable file, or load failure |

Exit 2 is the enforcement mechanism for "not evaluable is not the same as clean".
After ADR-0004 it is rare: the CLI recalculates a temp copy first, so missing
cached values are not the common path. It fires when every recalc backend fails.
CI treats it as failure. There is no "please open this in Excel" prompt.

### `--measure` mode

Emits the metrics block only, with no pass or fail: section-count estimates,
distinct formula shapes, max nesting depth, function calls per cell, sheet and
defined-name counts. This exists so budget thresholds can be set against a
measured distribution from real workbooks instead of chosen. See the budgets
section of `PHASE0_CHALLENGE.md`.

---

## 4. Phase 0 rule catalogue

Ten rules, every one traceable to one of GOAL's eight. Nothing invented; two
downgraded, one narrowed, two split. The reasoning is in `PHASE0_CHALLENGE.md`.

| ID | Slug | Sev | Conf | From | Requires |
|---|---|---|---|---|---|
| XL001 | unlabelled-named-constant | ERROR | CERTAIN | 1 (narrowed) | REF_GRAPH |
| XL002 | numeric-literal-in-formula | ERROR | CERTAIN | 2 | FORMULA_TOKENS |
| XL003 | mixed-formula-shape-in-run | ERROR | HEURISTIC | 3 | FORMULA_TOKENS |
| XL004 | text-in-numeric-cell | ERROR | CERTAIN | 4 (local) | CACHED_VALUES, NUMBER_FORMATS |
| XL005 | text-in-aggregated-range | ERROR | CERTAIN | 4 (graph) | CACHED_VALUES, REF_GRAPH |
| XL006 | inconsistent-period-axis | ERROR | HEURISTIC | 8 | — |
| XL101 | estimated-section-count | WARN | HEURISTIC | 5 (downgraded) | — |
| XL102 | no-check-convention-found | WARN | CERTAIN | 6 (existence; `chk_*`) | — |
| XL103 | check-not-passing | WARN | CERTAIN | 6 (evaluation) | CACHED_VALUES |
| XL104 | input-styling-not-redundant | WARN | HEURISTIC | 7 (downgraded) | REF_GRAPH |

Six at ERROR, not eight. The cut is forced by what a `.xlsx` can actually answer,
not by preference.

XL102 looks for defined names whose local name starts with `chk_`. That
convention is settled (Q2). Phase 1 emits a Checks block that registers each
check under that prefix, so the convention holds by construction.

---

## 5. Recalculation in Phase 0

The CLI never asks the user to open Excel. On `xllib lint PATH` it copies the
file, recalculates the copy, loads the copy, lints, and discards the copy. See
[ADR-0004](adr/0004-automatic-recalculation.md).

Backend order: `formulas` (CI default), LibreOffice headless, Excel COM last.
`formulas` 1.3.4 is verified on Python 3.14.4, including the off-sheet named
range `FTE_TARGET`. Solution keys must be matched case-insensitively; `tqdm`
on stderr must be suppressed.

`pydantic` stays out of Phase 0.

---

## 6. Sheet policy

All sheets count against the workbook budget, including hidden and very-hidden
ones. The cap is **10**, not GOAL's 15 (Q3). Hidden and very-hidden sheets are
linted; their state is reported on every finding that lands on them, and they
are counted (Q4).

Phase 1 adds an explicit sheet manifest. Phase 2 confirms that list before
anything is generated. Unwanted tabs are never built.

---

## 7. Repo location and prior art

This library lives in the orchestrator workspace at `excel-library/` (Q5).
Client projects call it. Project-specific variations are added only on
demonstrated need, never on want.

`xldump.py` is left alone (Q6). Other skills reference its path and the
Framework lane has it fenced. This library supersedes it functionally; add a
one-line pointer in `xldump.py` once Phase 0 ships. Do not fork. Do not delete.
