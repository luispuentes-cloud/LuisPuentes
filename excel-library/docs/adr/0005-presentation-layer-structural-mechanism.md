# ADR-0005 — What governs the presentation layer's structure

- **Status:** Proposed — **open question, deliberately undecided.**
- **Date:** 2026-09-21
- **Deciders:** Project Owner (pending)
- **Supersedes in part:** [ADR-0003](0003-constrained-generation-over-xlsx-templates.md), whose original argument 4 asserted this answer without testing it.

## Why this ADR exists

ADR-0003 took one vote for two layers. On 2026-09-21 the operator split them,
and this is where the second half landed. ADR-0003 keeps the calculation
engine: generated from a closed block vocabulary, no raw formula passthrough,
no hand-maintained `.xlsx`. That part stands and this ADR does not reopen it.

This ADR is written **without a decision on purpose.** The failure mode being
avoided is the one ADR-0003 fell into: an agent scoping a phase also writing
the decision that governs the phase's scope, reaching the conclusion that
minimises its own workload, disclosing the conflict in a closing paragraph, and
proceeding. A disclosure is not a control. The controls here are an experiment
registered before it runs and an author who is not the beneficiary.

## The question

> When the generator produces a sheet whose job is to be *read* — by an
> executive, in a deck, as a screenshot, or in a format a client has mandated —
> what fixes its structure?

Not "what fixes the structure of a calculation sheet." That is settled.

## Why the two layers are not the same question

| | Calculation engine | Presentation layer |
|---|---|---|
| Dominated by | formulas and dependencies | layout and geometry |
| Shape across engagements | novel each time | recurring |
| Failure mode | a wrong or untraceable number | an unreadable or off-format page |
| Verified by | recalculation, assertions, lint | looking at it |
| Intake role it serves | Predecessor, Seed, Source | **Constraint** |
| Hand-authoring risk | raw formula passthrough — GOAL's highest-risk decision | none of that kind; a drawn layout carries no formulas |

The last row is the load-bearing one. ADR-0003's surviving argument against
hand-maintained templates is that a hand-editable artifact able to carry
formulas is raw formula passthrough relocated to the structural layer. That
argument has no force against an artifact that carries **no formulas** —
column widths, merges, fonts, print areas, a logo, a title block. Whatever is
decided here has to engage with that asymmetry rather than inherit a
conclusion reached against a different risk.

## What is already known

- **`GOAL.md`'s Phase 1 definition of done requires it.** "Renders a
  presentation sheet readable as a standalone screenshot" is an acceptance
  criterion, and it is the only one in the list that cannot be checked by a
  test. Something has to produce that sheet and something has to judge it.
- **The `Constraint` intake role has no mechanism.** ADR-0003 accepted this
  gap on the grounds that it is one role in an unbuilt phase. The amendment
  withdrew that reasoning: deferring the one definitionally layout-shaped role
  while asserting that presets answer layout was circular.
- **The preset schema has no budget.** Every other expressive surface in this
  project has one — blocks per sheet, sheets per workbook, formula shapes, AST
  depth, live drivers, block types. ADR-0003 relocated bloat risk onto the
  preset and left it uncapped. This is an M005 acceptance criterion and it
  binds whichever option wins.
- **`GOAL.md`'s "structurally impossible" claim is false as stated.**
  Slot-filling makes bloat *inherited*, not impossible: a bloated template
  bloats every model built from it, and nothing caps the number of templates.
  Any option here needs its own answer to proliferation.
- **Experiment B is not evidence for this question.** It tested whether the two
  reference failures survive a lint-clean workbook. They do, and the second one
  survives for spatial reasons — but it also turned out to be reachable by a
  cell-level lint rule reading number formats. Do not cite experiment B as
  support for templates. See [EXPERIMENT_B.md](../EXPERIMENT_B.md).

## Options, none preferred

**A — Declarative layout preset.** A versioned YAML sheet plan: block order,
column geometry, print and screenshot geometry. The emitter renders it. This is
ADR-0003's original argument 4, now demoted from assertion to candidate.
*Open against it:* untested on screenshot fidelity; the schema is uncapped; and
the authoring loop is edit-YAML, regenerate, look, repeat.

**B — Hand-drawn `.xlsx` template, formula-free by construction.** A drawn
layout the generator fills. *Open against it:* a hand-edited binary in the
build, not diffable, and a second source of record. The build-artifact rule is
the objection, and its force depends on whether "binary versus text" and
"hand-edited versus generated" are treated as one axis or two — ADR-0003
argued format and concluded about provenance.

**C — Compiled template.** Author geometry in Excel where it can be seen,
extract it to a YAML preset with a tool, commit the YAML as the source, discard
the binary. WYSIWYG authoring, spec in git, one runtime mechanism, and
`inspect/` is already the reading substrate the extractor needs. *Open against
it:* the extractor is new code with no owner, and round-tripping fidelity is
unproven.

**D — Defer.** Build Phase 1's calculation half behind a seam and leave
presentation geometry unresolved until a real engagement forces it. *Open
against it:* `GOAL.md`'s Phase 1 definition of done includes the screenshot
criterion, so deferring means Phase 1 cannot be declared complete as written.

## How to decide it

**Experiment A — the screenshot bake-off.** Registered against this ADR, four
hours, not yet run. Hand-build a presentation sheet in Excel, then reach the
same result through a YAML preset and a throwaway emitter. Count properties
that had to be specified and iterations to an acceptable result. Register the
decision rule before the numbers exist, as
[EXPERIMENT_B.md](../EXPERIMENT_B.md) did — that protocol worked and should be
the house pattern.

**Who writes the decision.** Not the lane that authored ADR-0003, per the
challenge's process finding and the reasoning at the top of this file.

## Consequences of leaving it open

Phase 1 cannot define the preset schema as a settled thing. Either this ADR
closes first, or Phase 1 builds calculation behind a seam and treats
presentation geometry as provisional. That sequencing is an operator call and
is recorded as an M005 dependency.

Phase 0 is unaffected. It reads workbooks and does not write them.
