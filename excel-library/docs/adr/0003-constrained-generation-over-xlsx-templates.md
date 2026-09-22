# ADR-0003 — Constrained generation for the calculation engine, not `.xlsx` slot-filling

- **Status:** **Accepted 2026-09-22**, with the "templates address neither" clause struck and arguments 2, 3 and the two unadjudicated points below carried as explicitly open.
- **Date:** 2026-09-16 · **Amended:** 2026-09-21 · **Accepted:** 2026-09-22
- **Deciders:** Project Owner. Amendment scope directed 2026-09-21; accepted 2026-09-22.

> **What acceptance does and does not settle.** It settles the decision: the
> calculation engine generates from a closed block vocabulary, and no
> hand-maintained `.xlsx` is the source of shape. It does **not** ratify the
> whole rationale. Arguments 2 and 3 are scored Open in the challenge table
> below and stay open; the `GOAL.md` "structurally impossible" overstatement
> and the process finding about this ADR's authorship are recorded there
> unadjudicated and stay that way. Accepting a decision whose supporting
> arguments are partly unresolved is a deliberate choice, not an oversight —
> the alternative was to keep Phase 0 blocked on a Phase 1 question.
- **Scope:** the **calculation engine only**. The presentation layer is [ADR-0005](0005-presentation-layer-structural-mechanism.md), deliberately undecided.
- **Context:** Kickoff deliverable 3; GOAL.md "Open question — decide this first"

## Amendment summary — 2026-09-21

Four changes. The first is the substantive one; the rest follow from it.

1. **This ADR now decides one layer, not two.** It originally took a single
   vote for the calculation engine and the presentation layer at once. Those
   layers have different properties — one is formula-dominated and
   novel-shaped, the other is layout-dominated, recurring and
   screenshot-critical — and bundling them is what made the headline argument
   overreach. The presentation layer moves to ADR-0005 and is **not** decided
   there either; it is framed as an open question with a registered experiment.
2. **Argument 1 was wrong as stated and has been replaced**, on experimental
   evidence rather than on argument. See [EXPERIMENT_B.md](../EXPERIMENT_B.md).
3. **The Modano citation was wrong**, here and in `GOAL.md`. Corrected in both.
   The precedent turns out to support this ADR's decision, not the option it
   rejected, which means the original text was conceding a point it had won.
4. **A cross-column consistency rule is now in `BACKLOG.md`**, because the
   experiment showed the gap it fills is real and reachable by lint.

What this amendment does **not** do: it does not revisit arguments 2, 3 or 4.
An independent challenge scored two of those as failing or overreaching, and
that scoring is recorded under "Challenges not yet adjudicated" below rather
than acted on. The operator scoped this amendment to the split and the factual
corrections.

## Context

GOAL.md raises template slot-filling versus free generation as the question to
settle before Phase 1, and leans toward templates: fix workbook shape in
human-designed templates, with the spec supplying values and selecting which
declared blocks appear. The stated attraction is that bloat becomes structurally
impossible rather than merely detectable. The stated cost is that novel shapes
require a deliberate human template decision.

The decision is raised now because it changes Phase 0's design. Under a template
regime the linter must distinguish template-supplied structure from spec-supplied
content, and must carry waiver plumbing from day one.

**The question is really two questions, and this ADR answers one.** The
calculation engine is formula-dominated, novel-shaped per engagement, and the
place both reference failures do their damage to a number. The presentation
layer is layout-dominated, recurring across engagements, screenshot-critical,
and the home of the `Constraint` intake role — a client-mandated output format,
which is a layout requirement by definition. The arguments below are sound
about the first and were never tested against the second. Everything from here
is scoped to the calculation engine.

## Decision

**Generate the calculation engine from a closed block vocabulary. Do not adopt
hand-maintained `.xlsx` templates as the structural mechanism for calculation.**

Bloat-impossibility comes from the closed vocabulary plus the budgets. A new
block type is admissible only on a demonstration that it cannot be composed
from existing ones.

**The layout preset is retained as the mechanism for arranging generated
blocks, but it is no longer claimed to settle the presentation layer.** The
original text asserted that a declarative preset captures everything templates
win on layout. That claim is untested and now sits in ADR-0005, which is open.
Read this decision as: calculation is generated from a vocabulary, and how
generated blocks get arranged on a sheet is a preset for now, pending ADR-0005.

## Rationale

**The reference failures are formula-level *and* spatial, and the current rule
set addresses neither.** *(Replaces the original argument 1, which claimed the
failures were purely formula-level and semantic. That claim was tested and is
false — see [EXPERIMENT_B.md](../EXPERIMENT_B.md), pre-registered at `b357334`
and run the same day.)*

> **"Templates address neither" struck 2026-09-22 on acceptance.** The restored
> line claimed templates fail here too. Experiment B tested the *linter* against
> two hand-built workbooks; it never built a template and never showed one
> failing, so that half of the sentence asserted more than the evidence
> reaches. What survives is the tested half: both reference failures survive a
> lint-clean workbook. Whether a template would catch them is untested, and is
> the live question in ADR-0005 rather than a settled point here.

Two workbooks were hand-built in Excel and linted. One put a driver block on a
`Drivers` tab feeding a `Summary` headline by plain cell reference, with no
defined name anywhere. The other rendered two differently-calculated blocks as
adjacent parallel columns whose formulas normalise to an identical shape. Both
linted clean at exit 0 with all ten rules evaluated, and both reproduce the
reader's harm in full: the `Summary` sheet is a label and `$6,630` with no way
to discover that a driver exists, and the parallel table reads "Hours saved:
1,200" against "Hours saved: 8.5%" under headers inviting comparison. A control
fixture with genuinely different formula shapes was caught by XL003, so the
silence is specific rather than general.

So the original argument was wrong in both halves. The failures do not need a
named range, and they do survive the closed vocabulary, because the harm in the
second one lives in column adjacency and header parallelism — which is the
sense in which `GOAL.md`'s Question 4 states it, as a prohibition on
*rendering* blocks as adjacent parallel columns. The cross-standard summary in
`RESEARCH_Excel_Prior_Art.md` words the same invariant the same way: "one
formula per row, copied consistently across the time axis — no different
mechanics in adjacent columns."

**This does not rescue templates, and the amendment must not be read as saying
it does.** The experiment also found that the missed fixture is reachable at
cell level: its right-hand column carries `0.0%` on a row labelled "Hours
saved" and `$#,##0` on a row labelled "Blended rate", and `Cell.number_format`
is already loaded for every cell. A rule comparing formats and label
applicability across the columns of a row would catch it, and that is lint, not
a template. The corrected position is therefore narrower than either the
original argument or the challenge to it:

> The reference failures have a spatial component that the current rule set
> does not read. It does not follow that only a layout mechanism can read it.

What the closed vocabulary with no raw formula passthrough still does, and what
nothing has contradicted, is make the *formula-level* half inexpressible at
authorship rather than detectable afterwards. That remains the load-bearing
reason to prefer it for calculation.

**On the Modano citation — corrected, and the correction runs against the
original text's own framing.** `GOAL.md` and the first version of this ADR both
described template slot-filling as "the Modano insight." That is a misreading.
This repository's own research file records Modano as "a *modularity* approach
— models assembled from pre-built linked modules with integrity checks," and
separately frames the live disagreement as "Modano's module-assembly ideal
versus FAST's flat-transparency ideal." Module assembly from a vocabulary of
composable, integrity-checked units is what this ADR chose. The precedent
supports the decision rather than the rejected alternative, so the original
text was conceding a point it had already won. The same file classifies
`xltpl`, the closest open-source template engine, as "template-*fill*, not
model-*compilation*" — the distinction this ADR turns on.

**A hand-maintained `.xlsx` template contradicts the build-artifact rule.** GOAL is
explicit that the workbook is never hand-edited and never the source of truth. A
template in `.xlsx` form is a hand-edited binary that structure depends on — a
second source of record, outside the diffable pipeline, and exactly the thing the
spec-in-git decision was meant to eliminate.

**The throughput ceiling fails in the worst direction.** When a novel shape needs a
new template and the deadline is tomorrow, the outcome is not that the modeller
waits. It is that they hand-build outside the tool, which forfeits every guarantee
simultaneously. A closed vocabulary that cannot express something forces a
deliberate, reviewable vocabulary addition; a missing template just forces an exit.

**~~What templates genuinely win is layout, and a declarative preset captures
that.~~ Moved to ADR-0005, undecided.** This was the presentation-layer
argument, and it asserted the answer to the question this ADR has now been
narrowed out of. Sheet ordering, consistent geometry and surviving a screenshot
are layout properties; whether a declarative preset captures them as well as a
drawn template does is exactly what has not been tested. Experiment A, the
screenshot bake-off, is registered against ADR-0005 for that purpose.

## Consequences

Phase 0 needs no template concept: no distinction between supplied and generated
structure, no waiver plumbing on day one. The linter stays a file-in,
findings-out tool. **Unchanged by the amendment** — the presentation-layer
question reopening does not reach back into Phase 0, because Phase 0 reads
workbooks and does not write them.

Phase 1 must define the layout preset schema alongside the spec schema, and owns
column geometry and print setup as first-class declared properties rather than
emitter incidentals. The block vocabulary and its hard cap become the sole
structural constraint for calculation, which concentrates risk there — hence the
cap, and hence the requirement that a new block type demonstrate it cannot be
composed from existing ones.

**Phase 1 now has a sequencing dependency it did not have before.** If ADR-0005
lands on anything other than "presets, as currently conceived," the preset
schema Phase 1 was going to define changes shape. Either ADR-0005 closes before
the preset schema is built, or Phase 1 builds the calculation half first and
leaves presentation geometry behind a seam. That is an operator call, recorded
in M005 rather than resolved here.

The `Constraint` intake role in Phase 3 — a client-mandated output format — still
needs a mechanism. The original text accepted that gap on the grounds that it is
one role in an unbuilt phase. **The amendment does not accept it on those
grounds**, because the role is definitionally layout-shaped and the layout
question is now explicitly open: deferring the role while asserting that presets
answer it was the circularity the split removes. It is now an input to ADR-0005.

## A caution on this recommendation

This conclusion also happens to be the one that keeps Phase 0 smallest, which
aligns suspiciously well with the arguer's convenience. The substantive argument
stands on its own, but the alignment is worth knowing when weighing it.

**The caution was warranted, and the amendment is evidence of it.** The argument
it defended — "templates do not touch either reference failure" — is the one
that turned out to be false. A caution that names a bias and then proceeds is
not a control; it is a disclosure. The control is the experiment, and it should
have been run before the ADR was written rather than five days after.

The same conflict applies to this amendment: it was drafted by the lane that
authored the original. The mitigations actually in place are that the decision
rule was pre-registered in a separate commit before any fixture existed, that
the experiment carried a positive control, that the renders are committed so
the reader-harm judgement can be checked rather than taken on trust, and that
the finding which cuts *against* the amendment's direction — number format
being an unread cell-level signal — is recorded as prominently as the one that
supports it.

## Alternatives considered

**`.xlsx` slot-filling (GOAL's lean).** Rejected for the reasons above. The
strongest version of it remains attractive for a fixed, recurring deliverable, and
that is the case to watch for.

**Free generation with post-hoc linting only.** Rejected. This is the current
situation, and its failure is the reason the project exists: detection after the
fact does not prevent the shape, and nothing fails at the moment of authorship.

**Both, with templates optional.** Rejected for now as two structural mechanisms
with overlapping responsibility and no rule for which wins. Worth revisiting only
after the preset approach has been tried.

**The compiled-template path — not considered originally, and not the same as
"both."** Author geometry in Excel where it can be seen, extract it to a YAML
preset with a tool, commit the YAML as the source of truth, discard the binary.
This is one runtime mechanism, not two, so the objection to "both" does not
reach it; the artifact in the build is generated text, so the build-artifact
rule is satisfied; and `inspect/` is already the reading substrate the
extractor would need. It is carried to ADR-0005 as a live option for the
presentation layer. It is **not** an option for calculation, because a
hand-drawn artifact able to carry formulas is raw formula passthrough relocated
to the structural layer.

## Revisit when

Either trigger fires:

1. A client mandates a specific output format that must be reproduced exactly.
2. A layout preset cannot express a required shape for the third time.

## Challenges not yet adjudicated

An independent challenge on 2026-09-21, commissioned specifically to argue the
rejected case because this ADR conceded its conclusion suited its author,
scored the remaining arguments as below. The operator scoped the 2026-09-21
amendment to the split and the factual corrections, so these are **recorded and
open**, not acted on. They are listed so that a later reader does not mistake
silence for endorsement.

| Argument | Challenge's score | Status |
|---|---|---|
| 1 — failures are formula-level only | Fails as stated | **Amended 2026-09-21** on experimental evidence |
| 2 — a hand-maintained template contradicts the build-artifact rule | Survives, but only against *formula-bearing* templates; diffability is the weak half and a template could be committed, linted and dumped to canonical text | Open |
| 3 — the throughput ceiling fails in the worst direction | Fails. Under this project's own governance the asymmetry runs backwards: adding a block type needs a non-composability demonstration, an ADR, a cap of 20 and a session boundary, while drawing a template needs one person and one afternoon | Open |
| 4 — a declarative preset captures what templates win | Survives with an expensive qualification: the preset schema is the one expressive surface in this project with no budget | Moved to ADR-0005; the budget is an M005 criterion |

Two further points from the challenge, neither adjudicated:

- **`GOAL.md`'s "structurally impossible" claim is false as stated.**
  Slot-filling makes bloat *inherited*, not impossible — a bloated template
  bloats every model built from it — and nothing caps the number of templates,
  so proliferation becomes the new bloat vector.
- **Process.** This ADR's rationale is near-verbatim section 5 of
  `PHASE0_CHALLENGE.md`, by the same author, and `Deciders` read "Project Owner
  (pending)" for five days. The agent that scoped Phase 0 also wrote the
  decision governing Phase 0's scope. The amendment does not fix that; it
  documents it.

## Amendment history

| Date | Change | Evidence |
|---|---|---|
| 2026-09-16 | Original. Status Proposed. | — |
| 2026-09-21 | Scope narrowed to the calculation engine; argument 1 replaced; argument 4 moved to ADR-0005; Modano citation corrected; compiled-template alternative added; outstanding challenges recorded. | [EXPERIMENT_B.md](../EXPERIMENT_B.md); pre-registration `b357334`, result `ed8bf09`; operator directives 2026-09-21 |
