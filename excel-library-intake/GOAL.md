# GOAL — Audit-Grade Excel Generation Library

## Mission

A Python library that turns a guided conversation into a **declarative spec**, and a spec into an **audit-grade Excel workbook** — where readability and correctness are enforced mechanically at every boundary rather than documented and hoped for.

Long-term ambition is general-purpose: anything worth generating in Excel. Early scope is deliberately narrow.

## Read this part first

**This document is prose, and prose standards drift.** That is the founding observation of the whole project, and it applies to this file. Nothing here constrains anything. The linter constrains things. The schema constrains things. The budgets constrain things.

If you find yourself following this document because it is persuasive, the project has already failed. Every rule that matters below should exist as a test that can be run. Where one doesn't yet, that is a gap to close, not a principle to remember.

## The problem this exists to solve

Excel models become unfollowable through individually reasonable decisions. Two reference failures, both from real work. The system must make both **inexpressible**, not discouraged:

1. A scenario driver living in an off-sheet named range, so a reader cannot answer "how was this number produced?" from the sheet in front of them.
2. Adjacent result columns produced by *different mechanics* while presented as parallel.

A third failure is specific to AI-assisted building and is the main risk to this project: models are extremely capable at Excel and will produce sophisticated, bloated, unauditable output unless structurally prevented. Instructions are not prevention.

## Build order — this is not negotiable

**Phase 0 — the linter, standalone.** No generator. No spec. No IR. A tool that reads an existing `.xlsx` and reports violations. Ships with a failing fixture per rule.

Why first: it is small, has an unambiguous definition of done, and can be pointed at real existing workbooks immediately to find out whether the rules catch the problems we actually have. That is validation rather than assumption. And once it exists, every later phase's acceptance test is "output passes lint" — a red build rather than a paragraph of advice.

**Phase 1 — spec → workbook, one preset, from a hand-written spec.** No interview yet.

**Phase 2 — the interview layer.** Conversation compiles to spec.

**Phase 3 — intake.** Handling workbooks handed over by others.

Do not begin a phase until the previous one's acceptance test passes in CI.

## Architecture

```
Layer 4  Elicitation      fixed question set -> deterministic derivation -> spec
Layer 3  Domain presets    declarative: axes + block sets (NOT classes)
Layer 2  Core services     lint/  recalc/  assertions/  diff/
Layer 1  Render            openpyxl emitter
Layer 0  Model IR          workbook graph: sheets, blocks, cells, formulas, styles, refs
  ^
Spec     YAML/JSON         source of truth, git-committed, human-readable
```

**Layers 0–2 must know nothing about value cases, benefits, baselines, benefit owners, or FTEs.** If a domain noun appears in core, that is a bug. This boundary is the only reason "everything Excel" stays reachable; every domain concept that leaks into core narrows the library permanently.

**The `.xlsx` is a build artifact.** Never hand-edited, never the source of truth. The spec is what lives in git and what gets diffed.

## Model types are data, not code

There is no `ValueCaseModel` class, and there never will be — that road ends in eleven sibling classes, twelve code paths, and domain logic bleeding into core.

Instead, differentiate along **orthogonal axes**:

| Axis | Values |
|---|---|
| Lifecycle | one-off / monitored |
| Comparison | none / scenario variants / variance vs baseline |
| Aggregation shape | build-up / walk / comparison / flat |
| Reconciliation | none / to another model / to system of record |
| Audience | builder only / internal review / external executive |

A **model type is a named preset**: a set of axis values plus a block list. A value case is a driver block + cost build-up + scenario set + benefit ledger + variance bridge + presentation layer. A cost model is most of that minus the ledger and bridge. Adding a model type means writing a YAML file, not a Python class.

**This relocates the bloat risk to the block vocabulary, so the vocabulary gets its own budget.** Hard cap on block types. A new block type is admissible only if it demonstrably cannot be composed from existing ones, and the ADR must show the attempt.

## Schema restrictions

**No raw formula passthrough. Ever.** The schema must not accept `formula: "=IF(...)"` as a free string. This is the highest-risk decision in the project: the moment that field exists, every guarantee collapses, because it will be reached for the first time a declared construct doesn't quite fit — by the agent, and by me at 6pm before a deadline.

Everything else here is negotiable. This isn't.

Consequences: formulas are composed from declared, typed constructs. Anything inexpressible is either a missing construct (add it deliberately, with an ADR) or a sign the model shouldn't be built that way. The schema is a grammar with bad states removed, not a description format.

## Budgets — judgement calls converted to build failures

"Too many sections" is unenforceable. These are:

| Budget | Default |
|---|---|
| Blocks per sheet | 5 |
| Sheets per workbook | 15 |
| Distinct formula shapes per workbook | 40 |
| Formula AST depth | 4 |
| Live drivers in the driver block | 6 |
| Block types in the vocabulary | 20 |

AST depth 4 is the mechanical version of FAST's rule of thumb. All configurable per project, all failing the build when exceeded, none silently raisable by the agent.

## Lint rules

Eight, at `ERROR` severity. Derived from cross-standard agreement between FAST, ICAEW and IBCS:

1. Every driver/input is a **visible, labelled cell in a declared input block**. No off-sheet named range may act as a scenario driver.
2. **No numeric literals in formulas**, except a narrow allowlist (`0`, `1`, `-1`, `100`, `12`).
3. **One formula shape per row**, across the row's declared span.
4. **No text in numeric or currency columns.** Error and not-applicable states go in a separate status column or use real Excel error handling — never a string in a summed column.
5. Every sheet **declares its block structure** and respects the block budget.
6. Every workbook has at least one **check block**; checks evaluate to 0 or TRUE.
7. **Redundant cell-type signalling** — font colour *and* fill *and* an on-sheet legend. Meaning never carried by colour alone.
8. **Consistent time axis** — the same period occupies the same column index on every sheet.

**Start with exactly these eight.** No rule is added until every existing rule has caught a real bug. An over-large rule set is the documented way linters get routed around.

`WARN` exists but does not block. Waivers: see Intake.

## Elicitation layer

Users on my team will not know depth, block counts, or formula shapes, and should never be asked. **They answer questions about purpose, audience, lifecycle and data; the system derives the technical constraints.**

The question set is **fixed, versioned and finite**, and the answer-to-constraint mapping is **a deterministic table in code, not a judgement call.** The model conducts the interview; it does not design the interview and does not decide what answers imply. Otherwise drift simply moves up a layer — same answers, different specs, depending on the day.

### The question set (v1)

| # | Question | Derives |
|---|---|---|
| 1 | In one sentence, what decision does this support? | aggregation shape |
| 2 | Who defends this number if challenged without the file open? | presentation layer + methodology note mandatory if anyone but the builder |
| 3 | What will someone want to change live, in the room? *(name them)* | driver block contents; challenge above 6 |
| 4 | Do your scenarios change the same assumptions to different values, or do they actually calculate differently? | scenario architecture |
| 5 | Will anyone compare this to actuals later, or is it hand-over-and-move-on? | ledgers, change log, ingestion |
| 6 | Does this need to tie to another model or a system of record? | reconciliation block + check block |
| 7 | What period granularity and horizon? | time axis |
| 8 | Is this going into a deck? | presentation sizing, screenshot constraints |

**Question 4 is the most valuable question in the set.** It is reference failure #2, asked in language a non-technical user can answer. "Different values" produces one shared driver block with scenario columns. "Calculate differently" produces separate labelled blocks, and rendering them as adjacent parallel columns is *forbidden*.

### Interview behaviour

- **Push back, don't just record.** Fourteen named live levers is not a driver block, it is a second model. Negotiate before building.
- **Confirm in plain language before generating:** "Six sheets, three scenarios differing only by input values, four live drivers, monthly over three years, no actuals tracking." Cheapest possible gate.
- **Persist answers in the spec as provenance**, so when someone wants a seventh sheet in November the file records what it was scoped to do.
- **Let experts skip.** Naming a preset or handing over a prior spec bypasses the interview. Do not interrogate people who already know.

## Intake — when a workbook is handed over

**Role comes before inspection.** The same file is a predecessor, a data source, or a format constraint depending entirely on the ask. Infer the role from how the request was phrased; ask one question only when genuinely ambiguous. Never present a menu.

A handed-over file is usually a gift with missing context, not a suspect. It tells you what someone did; it never tells you why.

| Role | What it is | Extracted | Lint | Interview |
|---|---|---|---|---|
| **Predecessor** | Same model, next version | Full structure + values | **Gates** — we own the output | Intent questions only |
| **Seed** | A fragment to be promoted into its own model | Subgraph + what was aggregated | Reports | Boundary questions |
| **Source** | Supplies data or values | Data contract only | Reports | Two questions (below) |
| **Constraint** | Mandated output format | Layout, not logic | **Waived, recorded** | Minimal |
| **Subject** | "Look at this and tell me how it affects X" | Nothing persisted | Reports | None — **produce an answer, not a model** |

### Predecessor specifics

Flow: classify, extract, **lint the input**, then propose. Lead with violations, because that delivers value before asking for anything and the violations generate the questions. "Three scenario drivers are in off-sheet named ranges, the summary tab has seven blocks, and a text string in a currency column is breaking two downstream sums — which of these were deliberate?"

One question only inspection can set up: if adjacent columns have different formula shapes, the file has already answered question 4. Ask *"these three columns use different mechanics but are presented as parallel — deliberate, or drift?"*

**Import is lossy by default and declared.** "I can express 81% of this. Here are the fourteen things I can't — for each: drop, or load-bearing?" That conversation *is* the de-bloating mechanism. A lossless importer is an anti-feature.

**Earn the right to discard structure by proving the numbers.** Rebuild from the extracted spec, recalculate, diff against the original's cached values. Ties mean the extraction is faithful and the old structure can go with confidence. A mismatch is either an extraction bug or an error in the original — both worth finding. Golden-master testing pointed at migration; never requires trusting the import.

### Seed specifics

Promoting a tab into a full model is extraction plus *expansion*, not import. Questions: where is the boundary of the thing being promoted, what was aggregated that now needs detail, and does the parent still consume the result — which creates an interface contract back to the original.

### Source specifics

Two questions the file cannot answer, both expensive to get wrong:

1. **Authoritative or indicative?** Do we reconcile *to* it, or merely reference it?
2. **Read at build time, or read once to derive constants?** Build-time means a live external dependency that must be pinned, hashed and version-checked. Read-once means values baked into the spec with provenance — almost always what is actually wanted. Defaulting to a build-time dependency by accident is how a pipeline breaks when someone reorganises a shared drive.

### Universal intake rules

- **Never write to the input.** Always emit a new artifact; retain the original as the reconciliation reference.
- **Record provenance in the spec:** source filename, hash, import date, blocks mapped, blocks dropped and on whose decision. In four months someone will ask why the new model doesn't match the old one.
- **Waivers are first-class.** A mandated format will violate lint rules. A waiver records rule, scope, reason and approver, and appears in the spec. Waivers are never granted by the agent unprompted.

## Recalculation

openpyxl does not evaluate formulas, so recalculation is a pipeline stage behind a backend protocol. Preference order:

1. **`formulas`** (pure Python, actively maintained) — default. Core must recalculate on Linux CI with no Excel and no LibreOffice.
2. **LibreOffice headless** — fallback. Use a `calculateAll()` UNO call, *not* `--convert-to` alone. Spot-check YEARFRAC and day-count-dependent outputs, which are known to diverge.
3. **Excel COM** — last resort, opt-in, platform-gated, never a core dependency.

Avoid `pycel`: unmaintained since 2021, unpatched critical RCE (CVE-2024-53924).

## Testing — three kinds, never conflated

- **Assertions** — expected outputs declared in the spec, checked post-recalculation.
- **Invariants** — properties that must always hold (margins in 0–100%, no negative headcount, no `#REF!`).
- **Golden master** — immutable content asserted **bit-identical**; mutable content checked against invariants only. Conflating these gives a test that always fails or one that never catches anything.

## Working with the agent — process constraints

These exist because instructions about restraint don't hold:

- **Never let the agent write a constraint and the code satisfying it in the same session.** It will write a test that passes.
- **Cap diff size per increment.** Reject anything oversized unread. 2,000 lines cannot be audited and pretending otherwise is how bloat lands.
- **Run a deletion pass after each feature works**, whose only job is removing code, with the test suite as guardrail. Models are poor at restraint while building and good at deletion when that is the sole task.
- Every lint rule ships with a failing fixture. A rule without one does not exist.
- ADRs in `docs/adr/` for architectural decisions.
- If a domain concept needs to reach into core, **stop and ask**.

## Open question — decide this first

**Template slot-filling versus free generation.** Fix workbook shape in human-designed templates, with the spec supplying values and selecting which declared blocks appear — nothing else expressible. This is the Modano insight, and it makes bloat structurally impossible rather than merely detectable. Cost: novel model shapes need a new template, a human decision made deliberately rather than an agent decision made at 2am.

Given models here are 10–15 tabs with recurring structure, and given the `Constraint` intake role needs templates anyway, I lean toward templates. Not settled. Decide with evidence before Phase 1.

## Non-goals, which belong in `BACKLOG.md`

Formula parser or evaluator (use `formulas`) · wrapping the full openpyxl API · reading arbitrary workbooks losslessly · charts beyond preset minimums · `LET`/`LAMBDA`/dynamic arrays/Power Query (deliberate: they improve write-comfort, not auditability) · GUI or web app · non-Excel targets · commercial tool integration (OAK, PerfectXL, xltrail — access unknown) · database/BI graduation for long-lived monitored cases · AI-generated specs that bypass the interview.

## Definition of done

**Phase 0:** the linter runs on an arbitrary `.xlsx`, reports all eight rules, passes a failing fixture per rule, and runs in CI on Linux.

**Phase 1:** a hand-written value-case spec with a baseline, two scenarios and three periods compiles to `.xlsx`, recalculates headless in CI with no Excel, passes declared assertions and checks, **passes Phase 0 lint clean**, renders a presentation sheet readable as a standalone screenshot, and produces a readable diff against a modified spec. Every budget breach and every lint violation fails the build with a named error.

**Phase 2:** the eight questions produce a valid spec, and identical answers produce byte-identical specs.

**Phase 3:** each intake role behaves as its row above specifies; a predecessor rebuild reconciles to the original's cached values.

## Stack (confirm before building)

Python 3.12+ · openpyxl · pydantic · `formulas` · pytest · ruff · mypy strict · uv.
