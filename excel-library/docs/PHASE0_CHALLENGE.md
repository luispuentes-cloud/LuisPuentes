# Challenging GOAL.md before accepting it

**Covers:** kickoff deliverables 2 and 3, plus the invited over-engineering
pushback. Verified facts are marked; everything else is argument.

---

## 1. Is Phase 0 correctly scoped?

Yes, and it is smaller than GOAL implies. But it needs a minimal IR, and not the
one in the architecture diagram.

### Two IRs, not one

There are two different things wanting the name "IR" and they have opposite
requirements:

| | Generation IR (Layer 0) | Inspection IR (Phase 0) |
|---|---|---|
| Represents | Only what is legally expressible | Any garbage a real file contains |
| Vocabulary | Closed, grammar with bad states removed | Open, must survive the unexpected |
| Purpose | Emit a workbook | Describe a workbook |

Forcing one type to do both ends badly in a predictable direction: either the
generation IR gains the ability to represent illegal states — which dissolves the
no-raw-formula guarantee, the highest-value decision in GOAL — or the inspection
IR inherits the closed vocabulary and cannot parse a client file, which kills
Phase 3 intake.

So Phase 0 defines the **inspection IR** only, as an independent read-side
package. Phase 1's generation IR later projects into it via `to_inspection()`,
which is also what makes "output passes lint" a real acceptance test rather than
a second parallel checker.

### The smallest inspection IR that works

Six types: `Workbook`, `Sheet`, `Cell`, `DefinedName`, `RefGraph`, `TokenWalk`.
Plain dataclasses with `slots=True`.

### Verified: no formula AST is needed in Phase 0

I probed this rather than assuming it. On this machine — **Python 3.14.4,
openpyxl 3.1.5** — `openpyxl.formula.tokenizer.Tokenizer` parses GOAL's reference
failure formula into 17 tokens, classified by type and subtype. Two findings
follow, and both change the design:

**(a) The flat token stream is sufficient for more than expected.** Numeric
literals arrive as `OPERAND/NUMBER`, text literals as `OPERAND/TEXT`, and function
boundaries as `FUNC/OPEN` and `FUNC/CLOSE`. So numeric-literal detection, nesting
depth, function-call count, and argument index (via `SEP/ARG` plus depth) are all
decidable by a single stateful walk over the token list. GOAL lists "formula
parser or evaluator" as a non-goal; a tokenizer walk honours that, whereas
building an AST would quietly violate it. **Recommendation: no AST in Phase 0.**

**(b) The tokenizer cannot tell a defined name from a cell reference.** In that
formula, `FTE_TARGET` is emitted as `OPERAND/RANGE` — the identical subtype given
to `K4` and to `$I$4:$I$15`. Name resolution is therefore my job: every
`OPERAND/RANGE` token must be matched against the workbook's defined-names table
to decide what it is. This is a small piece of work but it is load-bearing for
XL001 and it would have been discovered late.

---

## 2. Which of the eight rules are not reliably detectable from a `.xlsx` alone

You expected at least two to be weaker than assumed. It is three undetectable as
written, plus two that are conditional on a convention holding. Rule by rule.

### Rule 1 — visible labelled inputs, no off-sheet named range as scenario driver

**Not detectable as written. And to your specific question: no, you cannot
distinguish a scenario driver from any other named range by inspection.**

Two separate problems. First, "input" is not a property a `.xlsx` records. A cell
holding a constant is just a cell holding a constant; nothing separates a live
driver from a stale note, a version number, or a row label that happens to be
numeric. Second, "scenario driver" is a semantic role that exists in the author's
head and in the spec, never in the file.

What *is* decidable is a useful proxy: a defined name that resolves to a single
cell, that cell holds a constant, formulas reference it, and there is no text
label in the cell immediately left of or above it. That fires on `FTE_TARGET`. It
is narrower than the rule you wrote and it is honest about what it saw.

So rule 1 splits: XL001 catches the undocumented constant reachable from
formulas; the full "every driver lives in a declared input block" version becomes
a **generation-time check in Phase 1**, where the spec makes it trivially true.
That is the right home for it — at generation the property is guaranteed by
construction rather than detected after the fact.

### Rule 2 — no numeric literals in formulas

**Detectable, cleanly.** Verified above.

One defect in the specification, though: the allowlist `0, 1, -1, 100, 12` is a
value list, and what is actually needed is a *positional* exemption table. Some
arguments are structurally required to be literals — `ROUND(x, 2)`,
`VLOOKUP(..., FALSE)`, the offset in `INDEX`/`OFFSET`, `IFERROR`'s second
argument. A value-only allowlist fires on every one of them, and a rule that
fires constantly on correct code is the documented way linters get routed around.
Argument index is available from the token walk, so the fix is cheap — but it has
to be designed in, not patched later.

### Rule 3 — one formula shape per row

**Partially detectable, and this is the rule most likely to generate noise.**

Shape comparison itself is easy and standard: normalise to R1C1 and compare
strings. The problem is the phrase "the row's declared span" — without a spec
there is no declared span, so it has to be inferred, and the obvious inference
(the contiguous non-empty run) produces a false positive at every legitimate
boundary: a total column at the end, an opening period that differs by design, a
label column, a variance column.

Keep it at ERROR, because it is the direct mechanical expression of the
invariant that every standard agrees on. But mark it HEURISTIC, and require the
finding to report the run bounds it inferred so a false positive is diagnosable in
one glance rather than by re-deriving the tool's reasoning.

### Rule 4 — no text in numeric or currency columns

**Detectable, and the strongest rule in the set.** Worth splitting into two,
because the local and the graph version catch different things:

- **XL004**, purely local: the cached value is a string and the number format is
  numeric or currency. No column inference needed at all, which means no
  heuristic and no false positives. This alone catches `"N/A — no FTE load"`.
- **XL005**, via the reference graph: a text cell sits inside a range that an
  aggregate function elsewhere sums. This is the version with teeth, because it
  proves the harm rather than predicting it — it names the sum that is being
  silently broken.

Note that "column" as GOAL frames it is ill-defined on an unstructured sheet. The
number-format framing sidesteps that entirely and is stronger for it.

### Rule 5 — every sheet declares its block structure and respects the budget

**Not detectable at all.** There is no block concept in the file format. Blocks
can be *estimated* by blank-row and blank-column gap analysis, but enforcing a
budget of 5 against an estimate produces failures the author cannot act on.

Downgrade to a WARN diagnostic (XL101) that reports the estimate and labels it as
one. The budget itself belongs at generation time in Phase 1, where the block
count is declared and the check is exact.

### Rule 6 — at least one check block; checks evaluate to 0 or TRUE

**Both halves are conditional, in different ways, so split them.**

Existence (XL102) is detectable only *by convention* — a `chk_*` defined name, or
a row whose label matches a check vocabulary. Phase 0 must state the convention it
looks for and report honestly that it found none, which is a real finding but a
convention-dependent one.

Evaluation (XL103) requires cached values. A workbook that openpyxl wrote and
Excel never opened has none. **This is the single most dangerous case in Phase 0**:
without a precondition mechanism the rule reads the absent value, finds nothing
failing, and reports clean on a workbook it never actually checked. Hence
`Capability`, `Status.SKIPPED`, and exit code 2. GOAL's own principle — a tool
cannot certify its own blind spot — is this specific bug, and it is the reason the
precondition machinery is not over-engineering.

### Rule 7 — redundant cell-type signalling

**Font and fill are detectable; the legend is convention-dependent.** The deeper
objection is different: as written this rule imposes our house style on arbitrary
files. Run it against a workbook someone else built and it reports a violation on
every input cell, which is noise, not a finding. Run it against our own generated
output and it should have been guaranteed at emit time anyway.

Downgrade to WARN (XL104) in the substantive form — constants that formulas
depend on and that are stylistically indistinguishable from formula cells — and
make it an ERROR at generation time in Phase 1.

### Rule 8 — consistent time axis

**Weakly detectable, and the detector is the weak link.** Finding the header row
and parsing period labels (`FY26`, `Jan-26`, real dates, `Q1`) is feasible. But
not every sheet has a time axis, a sheet may legitimately be transposed, and
period labels are free text.

Keep at ERROR but conditional: where two or more sheets both have a detected
period sequence, assert they agree on column index. Where none is detected,
report informationally. Be aware of the failure mode this leaves: a missed
detection reads as a pass, which is the blind spot exit code 2 does not cover.

### Summary

| Detectability | Rules |
|---|---|
| Reliably detectable | 2, 4 |
| Detectable with a documented heuristic | 3, 8 |
| Detectable only by convention or with a precondition | 6 |
| Not detectable without the spec | 1 (as written), 5, 7 |

The honest ERROR count is six, not eight. Every one of the eight survives in some
form; three are weaker than you assumed and now say so.

---

## 3. Are the budget defaults defensible?

Mostly arbitrary. That is tolerable for some and not for others, and one is
actively self-defeating.

| Budget | Default | Verdict |
|---|---|---|
| Blocks per sheet | 5 | Arbitrary but in the right neighbourhood. Not lintable from a file, so it only bites at generation. Keep. |
| **Sheets per workbook** | **10 (was 15)** | **Settled. All sheets count, including hidden.** |
| Distinct formula shapes | 40 | No basis, but it measures the thing that actually hurts. Keep the metric, set the number after measuring. |
| Formula AST depth | 4 | Right instinct, wrong single axis. Add function-call count. |
| Live drivers | 6 | Arbitrary, and it does not matter. |
| Block types | 20 | Not a budget yet. |

**Sheets per workbook is settled at 10, and every sheet counts** — visible,
hidden, and very-hidden. GOAL's 15 equalled the observed size of the artifact
being complained about, so it could never fire. The more consequential half of
the ruling: Phase 1 declares the tab list and Phase 2 confirms it before
anything is generated. Unwanted output is never built.

**Depth 4 is the wrong axis on its own.** `SUM(A1:A10)*B1` is depth 2 and
perfectly fine. `IF(a,IF(b,IF(c,d,e),f),g)` is the actual disease. Function-call
count per cell is the better primary metric — it is also what your own earlier
note reached for ("more than one function call in a single cell") — with depth as
a secondary. Both are free from the token walk.

**Live drivers at 6 is arbitrary and that is fine.** The mechanism is not the
number; it is the interview pushing back when it is exceeded. The number only has
to be low enough to trigger the conversation.

**Block types at 20 is a promise, not a budget.** The vocabulary currently has
zero members. Harmless to write down, but it enforces nothing until Phase 1, and
it should not be counted among the things protecting you today.

### The recommendation that matters

**Calibrate every budget against a measured distribution before any of them
becomes an ERROR.** Phase 0 hands you that instrument for nearly free: `--measure`
emits the metrics with no pass or fail. Run it across the existing corpus, look at
the distribution, then set six numbers you can defend. Six measurements instead of
six guesses, for the cost of one output mode.

---

## 4. Stack changes

| Item | Position |
|---|---|
| Python 3.12+ | Fine as a floor. Note this machine runs **3.14.4** (verified), which is new enough that third-party wheel availability is a live risk — another argument for a one-dependency Phase 0. |
| openpyxl | Correct. **3.1.5 verified installed.** One design constraint to bake in: formulas and cached values require *two* loads (`data_only=False` and `data_only=True`). This is a routine source of bugs and belongs in `load.py` behind one interface. |
| **pydantic** | **Drop from Phase 0.** Not installed here (verified). Its value is validating untrusted input and emitting JSON schema — both Phase 1 spec concerns. The inspection IR is internal, and pydantic model construction across tens of thousands of cells is materially slower than slotted dataclasses for no benefit. Adopt it in Phase 1, where it earns its place. |
| **`formulas`** | **In Phase 0, for recalculation, not for parsing.** Owner Q1 reversed the earlier drop. Verified 2026-09-16: `formulas` 1.3.4 installs on Python 3.14.4 with native `cp314` wheels and evaluates the fixture vocabulary, including the off-sheet named-range driver. Inspection still uses the tokenizer walk (ADR-0001). Recalculation uses this library as the CI default (ADR-0004). |
| pytest | Fine. **9.1.1 verified installed.** |
| ruff, mypy strict, uv | Fine. One warning: mypy strict against openpyxl will need a stub package or a scoped `ignore_missing_imports`. Better to decide that now than to discover it in the first CI run. |
| CLI library | Not needed. `argparse` for one command; do not add typer or click. |

Net effect: Phase 0 has two runtime dependencies, openpyxl and `formulas`.
`pydantic` stays out. Inspection still has one dependency; evaluation is the
second, and it is load-bearing for CI.

---

## 5. The open question: templates versus free generation

### The case for templates

Bloat becomes *inexpressible* rather than merely detectable, which is a stronger
guarantee and the one GOAL says it wants. Layout quality gets set by a human once
instead of being re-derived per run. Screenshot fidelity — a real delivery path —
is a layout property, and layouts are far easier to guarantee when fixed. Diffs
become small and semantic (which blocks appeared, which values moved) instead of
structural. And the `Constraint` intake role needs a template mechanism anyway, so
some of the cost is already sunk.

### The case against

Novel shapes require human template work, and that ceiling binds hardest exactly
when deadlines do. The documented consequence is not that people wait — it is that
they hand-build outside the tool, which forfeits every guarantee at once. Templates
also freeze the current house style as the only expressible style. And in `.xlsx`
form a template is a hand-maintained binary that becomes a second source of
record, which contradicts GOAL's own rule that the workbook is a build artifact.

### The decisive argument, which cuts against GOAL's lean

**Both reference failures are formula-level and semantic. Neither is a layout
problem.** A scenario driver hidden in an off-sheet named range fits into a
template slot perfectly well. Two adjacent columns computed by different mechanics
fit into adjacent template columns perfectly well. A template constrains *where
things go*; it says nothing about *what they are*.

The mechanism that actually makes those two failures inexpressible is the one GOAL
already committed to: a closed construct vocabulary with no raw formula
passthrough. Adding xlsx templates on top would be a second constraint system
aimed at a problem you did not report having.

### Recommendation

**Constrained generation from a closed block vocabulary, with declarative layout
presets — not slot-filled `.xlsx` templates.**

Keep the word "template" in the sense of a versioned YAML sheet plan that
specifies block order, column geometry, and print and screenshot geometry, and
that the emitter renders. Bloat-impossibility comes from the closed vocabulary
plus the budgets; layout quality and screenshot fidelity come from the layout
preset; and no hand-edited binary enters the pipeline.

**One caveat against my own recommendation, which you should weigh.** This
conclusion is also the one that keeps Phase 0 smallest — an xlsx-template world
would require the linter to distinguish template-supplied structure from
spec-supplied content and to carry waiver plumbing on day one. I do not think
convenience drove the argument, but it aligns suspiciously well with it, and you
should discount accordingly.

The decision is cheap to reverse. ADR-0003 records the triggers: the first
genuinely mandated client output format, or the third time a layout preset cannot
express a required shape.

---

## 6. Where you are over-engineering

You asked plainly, so here it is plainly.

**Eight ERROR rules is more than the file can support.** Six is the honest number.
Convenient that detectability forces the cut rather than taste.

**Five intake roles is a taxonomy built before a single intake.** Predecessor and
Source are clearly real and have genuinely different mechanics. Seed and Subject
look like one thing with two output modes. Constraint may reduce to "waivers
exist". Defer the taxonomy; let the first three real intakes name themselves.

**Five orthogonal axes and a preset system is a generalisation framework for a
library with one preset.** The axes are an excellent thinking tool and a premature
implementation. Hard-code one preset in Phase 1 and extract the axes when there
are three. Nothing is lost, because presets are data.

**The five-layer diagram is a map of a system that is currently a linter.** Keep
it as a map. Do not create five packages in Phase 0 — the design above creates
two.

**And one instance of the same failure in my own work, which I then cut.** My
first pass at the rule catalogue included two extra rules from your earlier notes:
a repeated-aggregate detector and a blanket-`IFERROR` detector. Both are good
ideas and neither is in GOAL's eight. Adding them would be precisely the drift
this project exists to prevent. They are in `BACKLOG.md` with pickup triggers.

### Where I think you are not over-engineering

Three things look expensive and are load-bearing. Keep all three.

- **No raw formula passthrough.** You are right that this is the decision
  everything else rests on, and right that it will be reached for under deadline
  pressure. It has to be absent from the schema, not discouraged.
- **The spec as source, the workbook as artifact.** This is what makes a binary
  format reviewable, and it is the highest-value item in the research.
- **Never write a constraint and the code satisfying it in the same session.** The
  cost is one extra session boundary. The failure it prevents is a test written to
  pass, which is unfalsifiable from the inside.

---

## 7. Owner rulings (closed 2026-09-16)

These were open in the kickoff. They are decisions now. The original wording is
kept only as the question that was asked.

1. **A workbook with no cached values is recalculated automatically, never
   handed back to the user.** Exit 2 remains in the contract but fires only
   when every backend fails (`formulas`, LibreOffice headless, Excel COM).
   Recalc is always against a temp copy. Excel COM sets `Visible=False` and
   `DisplayAlerts=False`. See ADR-0004. `formulas` is back in Phase 0 because
   CI has no Excel.
2. **`chk_*` defined names mark checks.** Every `chk_*` evaluates to 0 or TRUE.
   Phase 1 emits a Checks block that registers each, so the convention holds
   by construction.
3. **All sheets count, cap 10.** The tab list is declared and confirmed before
   anything is generated (Phase 1 spec + Phase 2 interview).
4. **Hidden and very-hidden sheets are linted, counted, and reported as such.**
   Silence about hidden content is the wrong default.
5. **This repo lives in the orchestrator workspace** at `excel-library/`.
   Client projects call it. Variations are added only on demonstrated need.
6. **Leave `xldump.py` alone.** Do not fork, do not delete. Add a one-line
   pointer once Phase 0 ships.

Version control is still unresolved. Settling *where* the repo lives did not
put it under git. Phase 0's definition of done still requires CI on Linux.
