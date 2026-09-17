# ADR-0001 — A read-only inspection IR for Phase 0, and no formula AST

**Status:** Accepted — implemented in `src/xllib/inspect/` (2026-09-16).
- **Date:** 2026-09-16
- **Deciders:** implemented against the Phase 0 design; owner rulings Q1–Q6 did not reverse this ADR
- **Context:** Kickoff deliverable 6; GOAL.md Phase 0 and the "no formula parser" non-goal

## Context

GOAL.md scopes Phase 0 as a standalone linter with "no generator, no spec, no IR",
while its architecture places a Model IR at Layer 0. Taken literally these
conflict: a linter must represent the workbook it is inspecting in some form. The
question is whether that representation is the Layer 0 generation IR arriving
early, or a different thing.

A second question sits underneath it. Several rules and two budgets need to look
inside formulas. GOAL lists "formula parser or evaluator" as a non-goal and directs
recalculation to the `formulas` library. It does not say how formulas are to be
*inspected*.

## Decision

**Define an independent read-only inspection IR in `src/xllib/inspect/`, distinct
from the future generation IR, and inspect formulas with a stateful walk over
openpyxl's tokenizer rather than building an AST.**

Six types, plain dataclasses with `slots=True`: `Workbook`, `Sheet`, `Cell`,
`DefinedName`, `RefGraph`, `TokenWalk`.

The generation IR arrives in Phase 1 and gains a `to_inspection()` projection, so
Phase 1's acceptance test calls the Phase 0 linter unchanged.

## Rationale

The two IRs have opposite requirements. The generation IR is a closed vocabulary
that must be incapable of representing an illegal state — that property is what
makes "no raw formula passthrough" meaningful. The inspection IR must represent
whatever a real file contains, including everything the generator would refuse to
emit. One type cannot hold both properties. Forcing it either weakens the
generation guarantee or makes intake impossible in Phase 3.

On formulas, the no-AST decision rests on a verified probe rather than an
assumption. On Python 3.14.4 with openpyxl 3.1.5,
`openpyxl.formula.tokenizer.Tokenizer` reduces

```
=IF(SUM($I$4:$I$15)=0,"N/A - no FTE load",K4*FTE_TARGET/SUM($I$4:$I$15))
```

to 17 typed tokens. Numeric literals surface as `OPERAND/NUMBER`, text literals as
`OPERAND/TEXT`, and function boundaries as `FUNC/OPEN` and `FUNC/CLOSE`. A single
stateful pass therefore yields everything Phase 0 needs: literal detection with
argument-index exemptions, nesting depth, function-call count, and R1C1 shape
normalisation. Building an AST would add a parser the non-goals rule out, to
obtain information already available.

## Consequences

**Accepted costs.**

The tokenizer does not distinguish a defined name from a cell reference — in the
formula above, `FTE_TARGET` carries the same `OPERAND/RANGE` subtype as `K4`.
Name resolution against the defined-names table is therefore ours to implement,
and it is load-bearing for XL001.

Rules needing genuine formula *structure* rather than token sequence — a
blanket-`IFERROR` detector is the clearest example — are not cleanly expressible
under this decision. That is one reason such rules are in `BACKLOG.md` rather than
Phase 0, and this ADR is the thing to revisit if two or more of them become
necessary.

Two openpyxl loads are required per workbook, since formulas and cached values are
mutually exclusive per load. `load.py` owns that and exposes one interface.

**Gained.**

Phase 0 has two runtime dependencies: openpyxl (inspection) and `formulas`
(recalculation, ADR-0004). `pydantic` stays deferred to Phase 1. `inspect/` is
reusable by Phase 3 intake and by generation-time checking without modification.

## Alternatives considered

**Bring the Layer 0 generation IR forward into Phase 0.** Rejected: it couples the
linter to a vocabulary that does not exist yet, and it is how the closed-vocabulary
guarantee gets diluted before it is ever enforced.

**Take a `formulas` dependency for parsing.** Rejected. Inspection uses the
tokenizer walk. `formulas` is in Phase 0 for *evaluation* (ADR-0004), which is a
different job; its 3.14 wheels and the named-range driver case were verified
2026-09-16.

**Regex over formula strings.** Rejected. It cannot distinguish a literal inside a
string constant from a bare literal, and it has no concept of argument position,
which the XL002 exemption table requires.

## Revisit when

Two or more structurally-dependent rules become necessary, or a required rule
cannot be expressed over the token stream.
