# excel-library

A library for generating and checking consulting workbooks, where the properties
that make a workbook auditable are enforced as executable checks rather than
documented conventions.

**Current state: Phase 0 linter is implemented and gated in CI.** Inspection,
automatic recalculation, ten rules, the CLI, and reports run here. pytest
**155 passed, 1 skipped**; Ruff and strict mypy are clean. Live Excel COM
recalc is verified on this machine, and Linux CI runs green on 3.12 and 3.14.

**Phase 0 is still not shipped**, but no longer for the reason this file used
to give. The old text said "nothing is under version control, so the Linux CI
workflow has never run"; both halves are now false. Nothing in the code blocks
it either — the three independent review briefs are collected and their
findings closed. What remains is three operator decisions: GOAL rule 1 is
implemented only as the XL001 proxy and the clean baseline still violates the
full rule; rule strictness is adjustable through `allowed_literals`,
`positional_exemptions` and `[budgets]` with no waiver; and ADR-0003's amended
text has not been accepted.

ADRs 0001, 0002 and 0004 are Accepted. **ADR-0003 was amended on 2026-09-21**
and narrowed to the calculation engine; the presentation layer moved to
**ADR-0005**, which is deliberately undecided. **ADR-0006** (whether an
unhandled cached error belongs in a rule 4 rule) and **ADR-0007** (whether
config discovery anchors on the working directory or the workbook) opened on
2026-09-22. All four are Proposed.

## What it does now

`xllib lint PATH` copies the workbook, recalculates the copy, loads it, and
reports which rules were evaluated, which were violated, and which could not
be evaluated. It never writes to the input file. It never says "pass".

## What it will not do

Certify that a model is correct. It can enforce structural legibility and
declared invariants. It cannot tell you the denominator is the right
denominator.

## Install and run

Python 3.12+. From this directory:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
ruff check .
mypy
```

Lint a workbook:

```powershell
xllib lint path\to\book.xlsx
xllib lint path\to\book.xlsx --json
xllib lint path\to\book.xlsx --measure
```

`--measure` emits metrics only (no pass or fail). Budget calibration still
needs an approved real-workbook corpus; synthetic fixtures are not that corpus.

## Reading a finding

```
Calc!D7      XL002  numeric literal 0.85 in formula; declare it as an input
Calc!D4:G4 ~ XL003  2 formula shapes in inferred run D4:G4
```

A `~` marks a heuristic finding — an inference about intent rather than a fact
about the file. Verify the inferred range before acting on it.

Exit codes: `0` clean, `1` error findings, `2` nothing failed but something
could not be evaluated, `3` usage or load failure. Exit 2 fires when every
recalc backend fails, not when a file merely lacks cached values.

## Documents

| Document | Contents |
|---|---|
| `docs/PHASE0_DESIGN.md` | Mission, layer boundary, repo structure, rule interface, rule catalogue |
| `docs/PHASE0_CHALLENGE.md` | Where GOAL.md is wrong, weaker than assumed, or unbuildable as written |
| `docs/PHASE0_FIXTURES.md` | One fixture per rule; built, not merely described |
| `docs/EXPERIMENT_B.md` | Pre-registered test of whether the two reference failures survive a lint-clean workbook. They do. Evidence behind the ADR-0003 amendment |
| `BACKLOG.md` | Deferred work, each with a pickup trigger |
| `docs/adr/` | 0001, 0002, 0004 Accepted; 0003 amended, 0005, 0006 and 0007 open, all Proposed |
| `docs/rules/` | One page per Phase 0 rule |
| `experiments/` | Scripts needing desktop Excel. Never collected by pytest and never run in CI |

The upstream product brief and the prior-art research that informed it are in
`../excel-library-intake/`.

## Version control

This package lives in the orchestrator **monorepo**. Git root is
`%USERPROFILE%\.cursor\orchestrator`, not this folder. Linux CI is
`.github/workflows/ci.yml` at that root (`excel-library` job, working
directory this folder, Python 3.12 and 3.14, `formulas`, no Excel).

Excel Library work happens on branch `lane/excel-library` in the worktree
`%USERPROFILE%\.cursor\worktrees\orchestrator-excel-library`. Do not edit
Framework paths from that worktree. Merge into `main` from the main checkout.

**The remote exists and is public.** Every commit is published. Do not add
client names, personal data, or absolute paths containing a username to any
tracked file — the two absolute paths this section used to carry were the
reason that sentence is now here.

## Build order

Phase 0 is the linter, standalone, with no generator and no spec. Phase 1
compiles a hand-written spec to a workbook. Phase 2 adds the interview.
Phase 3 adds intake. No phase begins before the previous one's acceptance
test passes in CI.

`xldump.py` is left alone until Phase 0 ships (Q6).
