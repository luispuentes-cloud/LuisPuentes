# Experiment B — do the two reference failures have a spatial component?

- **Status:** Run 2026-09-21. Result recorded below against the rule registered before it.
- **Registered:** 2026-09-21 at commit `b357334`, before the builder script was written.
- **Decides:** one input to the ADR-0003 amendment. Not the amendment itself.
- **Outcome:** ADR-0003's argument 1 is unsound as stated — but the experiment
  does not license the conclusion that templates are the remedy. See
  [Three things found that were not registered](#three-things-found-that-were-not-registered).

## Why this exists

ADR-0003 rejects hand-maintained `.xlsx` templates. Its first and headline
argument is:

> Both reference failures are formula-level and semantic, and templates address
> neither.

An independent challenge commissioned on 2026-09-21 scored that argument as
**failing as stated**, on the grounds that `GOAL.md`'s Question 4 words
reference failure (b) as a *rendering* prohibition — rendering differently-
calculated blocks "as adjacent parallel columns is forbidden" — and that
adjacent, columns and presented-as-parallel are layout words, not formula
words. It made the same claim about failure (a): that a driver block on a
`Drivers` tab feeding a `Summary` headline reproduces the reader's harm with
no named range anywhere.

The operator ruled on 2026-09-21 that ADR-0003 will be **amended, not reversed
and not accepted unchanged**, and that this claim gets tested against the built
linter before the amendment is written rather than taken on the challenge's
reading. This document is that test, registered before it runs.

The reason for pre-registration is specific and not ceremonial. The agent
writing this document is the same agent that will write the amendment, and the
challenge it is testing was commissioned to argue against a decision this lane
authored. An expectation recorded after the fact is worthless here.

## What the linter can and cannot see (established before the run)

Read from source, not assumed. These are the mechanics the experiment turns on:

- `_xl001` fires only on a **defined name** whose target is a numeric constant
  with no adjacent label. It never compares the constant's sheet to the
  referencing formula's sheet. A plain `Drivers!$B$3` reference is invisible
  to it because there is no defined name involved at all.
- `_xl003` compares `normalize_formula_shape` across a **contiguous horizontal
  run of formula cells in one row**. The normaliser rewrites A1 references to
  relative row/column offsets, so `=B4*B5` at `B6` and `=C4*C5` at `C6`
  normalise to the identical string `R[-2]C[0]*R[-1]C[0]`.
- Nothing in the rule set reads a cell's **number format** as a signal that two
  adjacent cells are different kinds of quantity, and nothing reads column
  adjacency or header parallelism at all.

So the mechanism by which each fixture would escape is known in advance. What
is **not** known in advance, and what the experiment is for, is whether a
fixture built this way is otherwise a legitimate, lint-clean workbook, and
whether a reader is genuinely harmed by it.

## Fixtures

All three are authored through Excel COM, not openpyxl. That is required, not
stylistic: `CACHED_VALUES` is all-or-nothing, so a workbook with any
uncalculated formula skips XL004, XL005 and XL103 workbook-wide, and a clean
result from a skipped rule would be worthless. Excel COM also makes the
fixtures what a person would actually produce, which is the point.

### B1 — off-sheet driver, no named range (test)

A driver block on `Drivers`, a headline on `Summary` computed from it by plain
cell reference. No defined name of any kind in the workbook.

This is GOAL reference failure (a) — "a scenario driver living in an off-sheet
named range, so a reader cannot answer *how was this number produced?* from the
sheet in front of them" — with the named range removed and the reader harm left
intact.

**Deliberate deviation, declared here rather than discovered later:** the
operator's restatement says "no named range anywhere," and the fixture honours
that literally. The consequence is that XL102 (at least one `chk_*` check) must
fire, because a `chk_*` name *is* a defined name. That finding is **incidental**
— it reports the absence of a check block, which is GOAL rule 6, and has
nothing to do with either reference failure. It is recorded, not counted.

### B2a — adjacent columns, different formula shapes (control)

Two result columns rendered side by side under parallel headers, where the two
formulas have genuinely different shapes: `=B4*B5` against `=C4*C5*C6`.

**This is a positive control and its expectation is registered: XL003 fires.**
Without it, a clean result on B2b proves nothing, because a linter that reports
nothing on everything would produce the same output. If XL003 does *not* fire
here, the finding is about the linter's weakness and the experiment stops until
that is understood.

### B2b — adjacent columns, same shape, different mechanics (test)

The discriminating fixture. Two result columns rendered side by side under
parallel headers, with **identical normalised formula shapes**, where the
inputs are different kinds of quantity:

- Column B is bottom-up: 1,200 hours saved x $45 blended rate.
- Column C is top-down: 8.5% of a $640,000 baseline spend.

The row labels are those of the left-hand column, which is what a modeller
actually produces when two different calculations get forced into one parallel
table. A reader reading across row 4 sees "Hours saved: 1,200" and "Hours
saved: 8.5%".

This is GOAL reference failure (b) — "adjacent result columns produced by
different mechanics while presented as parallel."

## What "clean" means here

Defined now, so it cannot be defined around a result later.

A fixture **passes clean** when the linter produces **no finding that names the
reference failure that fixture embodies**. Exit code is recorded but is not the
test: XL101, XL102, XL103 and XL104 are WARN and do not change the exit code,
so exit 0 on its own would be a weak claim.

A fixture is **invalid and must be rebuilt** if it produces any finding caused
by construction sloppiness — a stray numeric literal, an unstyled input cell, a
number format applied over a text header, a text value in an aggregated range.
Such a finding would let a reader argue the linter "caught something" when what
it caught was the fixture's own defect. Expected incidental findings are listed
per fixture above and in the results table; anything else invalidates the run.

## Decision rule

Registered before the run. All four outcomes, not only the confirming one.

| Outcome | Reading |
|---|---|
| B2a fires XL003, and B1 and B2b both pass clean while the reader harm is reproduced | **ADR-0003's argument 1 is wrong as stated.** Both failures survive a lint-clean workbook, and failure (b) survives specifically because the harm lives in adjacency and header parallelism, which no rule reads. The amendment says so and drops the claim. |
| B1 or B2b produces a finding that names its reference failure | **Argument 1 survives for that failure.** The harm is detectable at formula level and templates are not needed to reach it. The amendment narrows accordingly rather than dropping the claim. |
| B2a does **not** fire XL003 | The control has failed. No conclusion is drawn about either test fixture, because the linter's silence is then uninformative. This becomes a linter defect to investigate first. |
| A fixture passes clean but, on inspection, a reader **can** answer "how was this number produced?" from `Summary` | **The challenge's reading is wrong** and argument 1 survives. The fixture was not a faithful reproduction of the failure. |

The last row is the one that matters most and the easiest to skip. The
experiment is not "does the linter stay silent" — a linter can be silent about
something harmless. It is "does the linter stay silent **while a reader is
genuinely harmed**." Both halves get checked, and the reader-harm half is a
judgement made by looking at the rendered sheet, not by reading the source.

## Reproducing it

```powershell
py -3 excel-library\experiments\experiment_b_reference_failures.py --out %TEMP%\xllib_experiment_b
py -3 -m xllib lint <fixture>.xlsx --json
```

The builder lives in `experiments/`, not `tests/`, because it requires Excel
COM and can never run in Linux CI. It is committed rather than left in `%TEMP%`
because it is the evidence behind an ADR amendment and has to be re-runnable by
someone who did not write it. The `.xlsx` outputs are **not** committed: they
are build artifacts, the repository is public, and `GOAL.md` is explicit that a
workbook is never a source of truth.

## Results

Run 2026-09-21, Excel COM authoring against desktop Excel, linted with the
committed project config in force (`builtin` + `excel-library/xllib.toml`).

| Fixture | Exit | Errors | Warns | Findings | Names its reference failure? |
|---|---|---|---|---|---|
| B1 — off-sheet driver, no named range | 0 | 0 | 1 | XL006 INFO, XL102 WARN | **No** |
| B2a — different shapes (control) | 1 | 1 | 1 | **XL003 on `Benefits!B7:C7`**, XL006 INFO, XL102 WARN | **Yes** |
| B2b — same shape, different mechanics | 0 | 0 | 1 | XL006 INFO, XL102 WARN | **No** |

All three reported `10 of 10 rules evaluated`. Nothing was skipped, so the COM
authoring delivered the cached values the `CACHED_VALUES` rules need and no
rule was silently inert. Both incidental findings were predicted above before
the run; no unpredicted finding appeared, so no fixture is invalid.

Verbatim, with the worktree path abbreviated:

````
=== b1_offsheet_driver_no_named_range ===
Workbook                 ~ XL006  no period axis detected; inconsistent-period-axis was not evaluated
Workbook                 XL102  no chk_* defined name found

10 of 10 rules evaluated   0 error   1 warn
config: builtin, <worktree>\excel-library\xllib.toml
exit 0

=== b2a_adjacent_columns_different_shapes ===
Benefits!B7:C7           ~ XL003  2 formula shapes in inferred run B7:C7
Workbook                 ~ XL006  no period axis detected; inconsistent-period-axis was not evaluated
Workbook                 XL102  no chk_* defined name found

10 of 10 rules evaluated   1 error   1 warn
config: builtin, <worktree>\excel-library\xllib.toml
exit 1

=== b2b_adjacent_columns_same_shape ===
Workbook                 ~ XL006  no period axis detected; inconsistent-period-axis was not evaluated
Workbook                 XL102  no chk_* defined name found

10 of 10 rules evaluated   0 error   1 warn
config: builtin, <worktree>\excel-library\xllib.toml
exit 0
````

The pre-registration promised the raw JSON in this commit. It is **not**
committed, and the reason is the standing one: the reports embed absolute
paths carrying the operator's username and this repository is public. They are
at `%TEMP%\xllib_experiment_b\*.report.json` and regenerate from the builder.
The text above is the same content minus the paths.

### The reader-harm half

The renders are committed in `experiment-b/` because the registered rule turns
on a judgement about what a reader sees, and that judgement should not rest on
the word of the agent that wants a particular answer.

**B1 `Summary`** — the whole sheet is two cells: a label and `$6,630`. There is
no driver, no formula, no cross-reference, and no indication that a `Drivers`
tab exists. A reader cannot answer "how was this number produced?", cannot
discover what would change it, and has nothing on the sheet to follow. The harm
of reference failure (a) is reproduced in full, and there is no named range
anywhere in the workbook.

**B2b `Benefits`** — under the parallel headers "Automation" and "Vendor
consolidation", the sheet reads:

| | Automation | Vendor consolidation |
|---|---|---|
| Hours saved | 1,200 | 8.5% |
| Blended rate | $45 | $640,000 |
| Annual benefit | $54,000 | $54,400 |

The right-hand column's labels are simply false: 8.5% is not a count of hours
and $640,000 is not a rate. The two bottom lines land four-tenths of a percent
apart, which is exactly what invites a reader to treat them as comparable. The
harm of reference failure (b) is reproduced in full, and the linter reports
nothing.

### Outcome against the registered decision rule

**Row 1.** The control fired, both test fixtures passed clean, and the reader
harm is reproduced in both. **ADR-0003's argument 1 is wrong as stated.** Both
reference failures survive a lint-clean workbook, and failure (b) survives
specifically because the harm lives in column adjacency and header parallelism,
which no rule reads.

### Three things found that were not registered

Recorded because they change the amendment, and the third cuts against the
conclusion above.

**1. The linter catches the visible failure and misses the deceptive one.**
Compare the two renders. B2a, which XL003 catches, is the version a human
reviewer would also catch: it has a visible "Uplift factor 12%" row that only
one column uses, and bottom lines that differ by a factor of eight. B2b, which
nothing catches, is the one that survives review — parallel labels, plausible
numbers, bottom lines four-tenths of a percent apart. XL003's discriminator is
formula shape, and formula shape turns out to correlate *inversely* with how
deceptive the rendering is. The rule is most alert where it is least needed.

**2. Number format is an unread signal that is already in the IR.** In B2b the
right-hand column carries `0.0%` on the row labelled "Hours saved" and
`$#,##0` on the row labelled "Blended rate". A human spots it immediately.
Nothing compares number formats across adjacent columns in the same row, even
though `Cell.number_format` is already loaded for every cell.

**3. This qualifies the conclusion, and the qualification matters.** Finding 2
means failure (b) is reachable by a *cell-level* rule — compare number formats
and label applicability across the columns of a row — and such a rule is lint,
not a template. So the honest reading is narrower than "templates are needed":

> The reference failures have a spatial component that the current rule set
> does not read. It does not follow that only a layout mechanism can read it.

ADR-0003's argument 1 is wrong because it claims the failures are *purely*
formula-level and semantic. The correct claim is that they are formula-level
**and spatial**, that the spatial half is currently unimplemented, and that the
spatial half is addressable either by a new lint rule or by a layout mechanism.
This experiment discriminates between "argument 1 is sound" and "argument 1 is
unsound." It does **not** discriminate between "add a rule" and "adopt
templates," and the amendment must not pretend it does.

### Fixture-construction note

B1 honours "no named range anywhere" literally, which guarantees the XL102
warning, because the only sanctioned check convention is a `chk_*` defined
name. This is a property of the fixture, not a contradiction in GOAL: rule 1
bans an off-sheet named range *acting as a scenario driver*, not named ranges
as such. Adding a check block would have removed the warning without touching
the result.
