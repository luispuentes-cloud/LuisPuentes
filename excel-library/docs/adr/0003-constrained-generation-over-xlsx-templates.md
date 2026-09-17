# ADR-0003 — Constrained generation with layout presets, not `.xlsx` slot-filling

- **Status:** Proposed
- **Date:** 2026-09-16
- **Deciders:** Project Owner (pending)
- **Context:** Kickoff deliverable 3; GOAL.md "Open question — decide this first"

## Context

GOAL.md raises template slot-filling versus free generation as the question to
settle before Phase 1, and leans toward templates: fix workbook shape in
human-designed templates, with the spec supplying values and selecting which
declared blocks appear. The stated attraction is that bloat becomes structurally
impossible rather than merely detectable — the Modano insight. The stated cost is
that novel shapes require a deliberate human template decision.

The decision is raised now because it changes Phase 0's design. Under a template
regime the linter must distinguish template-supplied structure from spec-supplied
content, and must carry waiver plumbing from day one.

## Decision

**Generate workbooks from a closed block vocabulary, governed by declarative
layout presets. Do not adopt hand-maintained `.xlsx` templates as the structural
mechanism.**

A layout preset is a versioned YAML sheet plan: block order, column geometry, and
print and screenshot geometry. The emitter renders it. Bloat-impossibility comes
from the closed vocabulary plus the budgets; layout quality and screenshot
fidelity come from the preset.

## Rationale

**Both reference failures are formula-level and semantic, and templates address
neither.** A scenario driver hidden in an off-sheet named range fits into a
template slot perfectly well. Two adjacent columns computed by different mechanics
fit into two adjacent template columns perfectly well. A template constrains where
things go; it is silent on what they are. The mechanism that makes those two
failures inexpressible is the closed construct vocabulary with no raw formula
passthrough, which GOAL has already committed to. Adding templates would be a
second constraint system aimed at a problem that was not reported.

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

**What templates genuinely win is layout, and a declarative preset captures that.**
Sheet ordering, consistent geometry, and surviving a screenshot are all layout
properties. They do not require a binary to hold them.

## Consequences

Phase 0 needs no template concept: no distinction between supplied and generated
structure, no waiver plumbing on day one. The linter stays a file-in,
findings-out tool.

Phase 1 must define the layout preset schema alongside the spec schema, and owns
column geometry and print setup as first-class declared properties rather than
emitter incidentals. The block vocabulary and its hard cap become the sole
structural constraint, which concentrates risk there — hence the cap, and hence
the requirement that a new block type demonstrate it cannot be composed from
existing ones.

The `Constraint` intake role in Phase 3 — a client-mandated output format — still
needs a mechanism, and this decision does not provide one. That is accepted: it is
one role in an unbuilt phase, and per the challenge document the whole five-role
taxonomy should be deferred until real intakes name themselves.

## A caution on this recommendation

This conclusion also happens to be the one that keeps Phase 0 smallest, which
aligns suspiciously well with the arguer's convenience. The substantive argument
stands on its own — templates do not touch either reference failure — but the
alignment is worth knowing when weighing it.

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

## Revisit when

Either trigger fires:

1. A client mandates a specific output format that must be reproduced exactly.
2. A layout preset cannot express a required shape for the third time.
