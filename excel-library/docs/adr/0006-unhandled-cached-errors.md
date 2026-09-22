# ADR-0006 — Whether an unhandled cached error is a rule 4 violation

- **Status:** Proposed — **not decided in this session, by design.**
- **Date:** 2026-09-22
- **Deciders:** Project Owner (pending)
- **Relates to:** [ADR-0002](0002-rule-registration-and-severity.md), [XL004](../rules/XL004.md), [XL005](../rules/XL005.md)

## Why this ADR exists

`XL004.md` closes with an open question that the rule itself could not settle:

> `GOAL.md` rule 4 says error states may "use real Excel error handling," which
> arguably makes a bare `#DIV/0!` compliant. This rule corrected the *wording*
> of the error branch; it did not decide *whether* the branch should fire at
> all. Whether an unhandled error is its own rule needs an ADR.

This is that ADR. It is written without a decision because the choice turns on
a rule-addition policy the operator owns and on evidence that does not exist
yet — see "How to decide it."

## The question

> A formula caches `#DIV/0!`. Is that a violation of GOAL rule 4, a violation
> of something else, or not a lint finding at all in Phase 0?

## What GOAL actually says

Rule 4, in full:

> **No text in numeric or currency columns.** Error and not-applicable states
> go in a separate status column or use real Excel error handling — never a
> string in a summed column.

The clause admits two readings, and the rules currently implement neither
explicitly:

**Reading A — "handled" means the error never surfaces.** "Real Excel error
handling" is `IFERROR` / `IFNA` around the fragile expression, so the cell ends
up holding a number or a controlled result. A bare `#DIV/0!` is then *un*handled
and is a defect — but a defect of arithmetic, not of column hygiene.

**Reading B — "handled" means the native error type rather than a typed
string.** The clause's job is to stop someone typing `"n/a"` into a summed
column; letting Excel's own error propagate is the sanctioned alternative. A
bare `#DIV/0!` is then *compliant* with rule 4, and XL004's error branch is
firing outside the rule it descends from.

**GOAL's own testing section points at Reading A but puts the check
somewhere else.** Under "Testing — three kinds, never conflated," invariants are
"properties that must always hold (margins in 0–100%, no negative headcount,
**no `#REF!`**)." So GOAL does treat an unhandled error as unacceptable — and
classifies it as an *invariant*, not as a lint rule. Invariants are declared in
a spec, which Phase 0 does not have. Taken literally, Phase 0 has no mandate to
report cached errors at all, and Phase 1 acquires one.

## Where the error branch fires today, and where it does not

`Cell.is_error` (`inspect/model.py`) matches an exact `ERROR_LITERALS` member
and corroborates it against the file's own type system — a formula's cached
result, or a static cell Excel typed `e`. That predicate is sound. The problem
is which rules consult it.

`_xl004` fires only when `_numeric_format(cell.number_format)` is true.
`_xl005` fires only for a cell inside an aggregate range whose bounds the
reference graph resolved.

| A cached `#DIV/0!` sitting in… | Reported? | By what |
|---|---|---|
| a numeric- or currency-formatted cell | Yes | XL004, `kind = "error"` |
| a resolved aggregated range | Yes | XL005, `kind = "error"` |
| a `General`-formatted cell, not aggregated | **No** | nothing |
| `SUM(D:D)` or `SUM(Table1[Amount])`, `General` format | **No** | nothing — XL005's known gap |
| a text-formatted (`@`) cell | **No** | nothing |

**This is the load-bearing observation.** Whether a broken formula gets
reported currently depends on the cell's number format and on whether the
reference graph could resolve an aggregate's bounds. Neither property has
anything to do with whether the formula is broken. Coverage of the commonest
real defect in a workbook is therefore incidental rather than designed.

A second, smaller problem: the rule that reports it is named
`text-in-numeric-cell` and its error-branch remediation is "repair the
formula." Anyone filtering on that slug to triage formatting work gets broken
formulas mixed into the queue, and anyone counting rule-4 violations counts
something else.

## Options

**A — Status quo.** Keep the error branch inside XL004/XL005, distinguished by
the `kind` evidence key. *For:* catches the defect today, ships nothing new,
`kind` already lets a consumer separate the two. *Against:* leaves the coverage
gaps in the table above unaddressed, and keeps a rule reporting a defect its
name does not describe.

**B — Split it out.** A new rule — `unhandled-cached-error`, ERROR, CERTAIN,
requires `CACHED_VALUES` — fires on any cached error anywhere, regardless of
format or aggregation. XL004/XL005 revert to text-only and their `kind` key
retires. *For:* detection stops depending on irrelevant properties; each rule
reports what its name says; the remediation splits cleanly. *Against:* it adds
a rule, and GOAL's policy is "Start with exactly these eight. No rule is added
until every existing rule has caught a real bug." That precondition is
currently unverified, which makes this option gated rather than merely
debatable.

**C — Keep the branch, fix the framing.** Status quo in code; record in
`XL004.md`/`XL005.md` that the error branch is Reading A enforcement borrowed
into a rule-4 rule, with the coverage gaps named as known limits. *For:*
honest, zero code, no rule added. *Against:* documents a gap instead of closing
it, and prose is what this project distrusts.

**D — Remove the branch; defer to Phase 1 invariants.** Follow GOAL's own
taxonomy: `#REF!` is an invariant, invariants need a spec, Phase 0 has no spec.
*For:* the most faithful reading of GOAL as written. *Against:* Phase 0 is
meant to be pointed at *existing* workbooks, which is exactly where unhandled
errors live and where no spec will ever exist. It removes working detection and
gets nothing back until Phase 1.

## How to decide it

Two inputs, neither available in this session:

1. **Does the split actually change what gets caught?** Run the linter over the
   approved workbook corpus with `kind = "error"` findings tallied by number
   format and aggregation status. If nearly every cached error already sits in
   a numeric-formatted or aggregated cell, option A's gaps are theoretical and
   the cheapest answer is C. If a material share sits in `General` cells, the
   gaps are real and B earns its rule slot. **Blocked on the same corpus
   pointer and permission that blocks budget calibration.**
2. **Has every existing rule caught a real bug?** GOAL's rule-addition
   precondition. Option B cannot be taken before this is answered, and it is
   answered by the same corpus run.

Until both land, option C is the only one that is both honest and unblocked,
and it is a holding position rather than a decision.

## Consequences of leaving it open

Phase 0 can still ship. The error branch works, is tested, and its two
`kind` fixtures pass; what is unresolved is whether its *placement* is right,
not whether its output is correct. Nothing downstream is blocked.

Phase 1 is mildly affected. Its generated workbooks should not contain cached
errors at all, so whichever option wins, the generator's obligation is
identical: emit no unhandled error. The choice only governs how the linter
reports one it finds in someone else's file, which is a Phase 3 intake concern
more than a Phase 1 one.
