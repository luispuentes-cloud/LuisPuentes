# ADR-0002 — Rule registration, capability preconditions, and the severity model

**Status:** Accepted — implemented in `src/xllib/lint/` (2026-09-16/17).
- **Date:** 2026-09-16
- **Deciders:** implemented against the Phase 0 design; owner rulings Q1–Q6 did not reverse this ADR
- **Context:** Kickoff deliverables 5 and 6; GOAL.md lint rules and waiver policy

## Context

GOAL.md specifies eight ERROR rules, a non-blocking WARN tier, and waivers that
the agent may never grant. It does not specify how a rule is declared, how the
rule set is discovered, what happens when a rule cannot be evaluated, or how
severity may be changed.

The last two are not administrative details. Three Phase 0 rules depend on cached
values, which a workbook written by openpyxl and never opened in Excel does not
have. Without an explicit mechanism, such a rule reads an absent value, finds
nothing wrong, and reports clean on a workbook it never checked.

## Decision

**Rules are frozen dataclass instances in an explicit registry. Each declares the
capabilities it requires, and a rule whose requirements are unmet returns
`SKIPPED` rather than passing. Severity is not a free dial, and "not evaluable"
exits non-zero.**

### Declaration and registration

A rule is a `Rule` dataclass instance exposing a `check` callable — no base class,
no inheritance. `lint/rules/__init__.py` imports each module and collects its
`RULE` constant into an ordered tuple.

Entry-point plugin discovery is explicitly rejected: an installed third-party
package could alter the rule set, which makes a report irreproducible and breaks
the byte-stability property the JSON output depends on.

### Capabilities and status

`Capability` enumerates what a rule may need: `FORMULA_TOKENS`, `CACHED_VALUES`,
`NUMBER_FORMATS`, `REF_GRAPH`, `STYLES`. The loader computes what the workbook in
hand supplies. Each rule declares `requires`. The runner skips any rule whose
requirements are unmet and records the reason.

`Status` is `VIOLATION | SKIPPED | INFO`. There is no `PASS` status, and the
reports do not use the word: they state which rules were evaluated, which were
violated, and which could not be evaluated.

### Confidence

`Confidence` is `CERTAIN | HEURISTIC`, declared on the rule. Three Phase 0 rules
infer spans, columns or header rows. A finding must state on its face whether it
is a fact about the file or an inference about intent.

### Severity

`Severity` is `ERROR | WARN`. Config may raise a severity freely. Lowering a rule
that is `ERROR` by default, or setting it to `off`, requires a matching waiver
entry. A waiver carries `rule`, `scope`, `reason`, `approver` and `expires`; CI
fails on any waiver with an empty `approver` or a past `expires`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All applicable rules evaluated, no ERROR findings, nothing skipped |
| 1 | At least one ERROR finding |
| 2 | No ERROR findings, but one or more rules could not be evaluated |
| 3 | Usage error, unreadable file, or load failure |

## Rationale

Exit 2 is the mechanical form of GOAL's own principle that a tool cannot certify
its own blind spot. Collapsing "checked and clean" into "could not check" is the
single most damaging bug available to a linter, because it converts absence of
evidence into a green build. Making it a distinct non-zero code means the failure
is impossible to reach by accident.

Severity-lowering via waiver rather than via config exists because config is the
obvious route-around. A rule that can be switched off by editing one line is a
rule that will be, at 6pm before a deadline — the same pressure GOAL identifies for
raw formula passthrough. Requiring a named human approver in a committed file is
the enforceable version of "the agent never grants a waiver"; a prose instruction
is not.

Declaring confidence on the rule rather than deriving it per finding keeps it
honest. A heuristic rule cannot claim certainty on a case that happens to look
clear-cut.

## Consequences

Every rule carries a `requires` set even when empty, which is mild ceremony on
rules that need nothing. Fixtures must cover the skip path as well as the
violation path, so the fixture count is larger than the rule count. A workbook
that is genuinely fresh from generation is recalculated in Phase 0 before lint
(ADR-0004), so exit 2 is no longer the expected CI result of a clean emit. It
remains the result when every recalc backend fails.

In exchange, `Status` and `Capability` still earn their keep: a failed backend
chain must skip rather than invent cached values, and Phase 1 generation-time
checks reuse the same machinery.

## Alternatives considered

**Exit 0 when nothing failed, regardless of skips.** Rejected. This is the bug.

**A rule base class with inherited helpers.** Rejected: rules must be independently
testable data, and a shared base class is where cross-rule coupling accumulates.

**Warnings only, with no ERROR tier in Phase 0.** Tempting, since Phase 0 gates
nothing yet. Rejected because Phase 1's acceptance test is "output passes lint",
and that requires a blocking tier that already works.

## Revisit when

Rules need to ship separately from the core package, or a third severity tier
(`INFO` as a first-class severity rather than a status) is genuinely required.
