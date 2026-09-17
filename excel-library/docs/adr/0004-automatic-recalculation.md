# ADR-0004 — Automatic recalculation on a temp copy, in Phase 0

- **Status:** Accepted
- **Date:** 2026-09-16
- **Deciders:** Project Owner (ruled 16:41)
- **Context:** Challenge Q1; GOAL.md Recalculation; owner instruction to remove the user where possible

## Context

Three Phase 0 rules (`XL004`, `XL005`, `XL103`) need cached values. openpyxl
does not evaluate formulas. The first design deferred recalculation to Phase 1
and planned two committed binary fixtures so those rules could be tested at all.
A workbook with no cached values would skip those rules and exit 2.

The owner ruled that the tool opens Excel itself and never asks the user. That
reverses two earlier recommendations: `formulas` returns to Phase 0 (Linux CI
has no Excel), and committed binary fixtures are no longer needed because a
generated fixture can be recalculated.

Verified on this machine, 2026-09-16:

- pywin32 installed; Excel COM responds at version 16.0. `Visible` defaults to
  True.
- LibreOffice is not on PATH.
- `formulas` 1.3.4 installs on Python 3.14.4 with native `cp314` wheels
  (numpy 2.5.3, scipy 1.18.1, schedula 1.6.15) and evaluates the fixture
  vocabulary: `SUM`, an off-sheet named-range driver, `IF` zero-guard, `ROUND`,
  and a check cell resolving to 0.0. Write-back to a directory works.
- Result keys uppercase the sheet name (`Calc` → `CALC`); mapping must be
  case-insensitive. `tqdm` writes a progress bar to stderr and must be
  suppressed.

## Decision

**Recalculation is a Phase 0 pipeline stage. The CLI never asks the user. It
always works on a temp copy of the input. Backends are tried in order until one
succeeds.**

### Backend chain

| Order | Backend | Role |
|---|---|---|
| 1 | `formulas` | Default. Pure Python. The only path that can run in Linux CI with no Excel and no LibreOffice. |
| 2 | LibreOffice headless | Fallback. `calculateAll()` UNO, not `--convert-to` alone. Spot-check YEARFRAC and day-count outputs, which are known to diverge. |
| 3 | Excel COM | Last resort, Windows-only. `Visible=False` and `DisplayAlerts=False` are mandatory; the probe found `Visible` defaults to True. |

Avoid `pycel`: unmaintained since 2021, unpatched critical RCE (CVE-2024-53924).

### Temp copy, never the input

Copy the target to a temp file, recalculate the copy, load the copy, discard it.
This is the same rule as intake ("never write to the input") and it also
sidesteps the lock-fallback trap: an already-open workbook silently spawning a
second file of record.

### Exit 2 after this ruling

Exit 2 stays in the contract. It becomes rare: it fires when **every** backend
fails, not whenever a freshly generated file has no cached values. The CLI
recalculates first; a skip of a value-dependent rule after a successful recalc
is a bug.

### Two `formulas` quirks the backend must handle

1. Solution keys uppercase the sheet name. Mapping solutions back to sheets is
   case-insensitive.
2. A `tqdm` progress bar writes to stderr. Suppress it so the CLI's own
   diagnostics remain the only stderr traffic.

### Fixtures

All fixtures are generated at test time and recalculated. There are no committed
`.xlsx` binaries in Phase 0.

## Rationale

Asking the user to open Excel is a human step the owner ruled out. Putting
recalc in Phase 1 would leave the three value-dependent rules untestable in CI
and would keep exit 2 as the common path rather than the failure path. `formulas`
is the only backend that can satisfy "runs in CI on Linux" from the Phase 0
definition of done. Excel COM remains last because it is platform-gated and
must never become a core dependency, but it is the most faithful evaluator when
it is available.

The temp-copy rule is not optional ceremony. Recalculating in place would both
mutate the caller's file and, on Windows, interact badly with Excel's file
locking.

## Consequences

Phase 0 has two runtime dependencies: openpyxl and `formulas`. `recalc/` exists
in Phase 0, behind a `RecalcBackend` protocol, so later backends plug in without
touching rules. Tests that need cached values call recalc; tests that need the
skip path inject a failing backend rather than relying on an un-recalculated
file as the only way to reach exit 2.

LibreOffice is specified and currently absent on this machine. That is a
deployment gap, not a design gap.

## Alternatives considered

**Ask the user to open the file in Excel.** Rejected by the owner.

**Keep two committed binary fixtures and skip recalc until Phase 1.** Rejected.
Binaries cannot be reviewed in a pull request, and CI on Linux could not
evaluate the three value-dependent rules.

**Excel COM first on Windows.** Rejected. Core must recalculate on Linux CI.
COM is last, not first, even on this machine.

## Revisit when

`formulas` cannot evaluate a construct a required rule depends on, or
LibreOffice / Excel COM diverge on a check we actually ship. The named-range
driver case is already known to work under `formulas` 1.3.4.
