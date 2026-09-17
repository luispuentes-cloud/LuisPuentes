# Session 1 — Phase 0 design only

You are helping me build the library described in `GOAL.md`. Attached alongside it are two research documents: a landscape review of Excel modelling standards and tooling, and an addendum on monitored versus one-off value cases. Read all three before responding — they contain the reasoning behind every decision in `GOAL.md`.

**Scope for this session is Phase 0 only: a standalone linter.** No generator, no spec schema, no IR, no interview layer, no intake. Those phases exist in `GOAL.md` for context so you can avoid designing Phase 0 in a way that blocks them — not so you can start them.

**Do not write implementation code yet.** The design needs settling first.

## Deliverables

1. **Restate the mission and the Layer 0–2 versus Layer 3 boundary in your own words.** Where your restatement differs from mine, that difference is the most useful thing you produce today.

2. **Challenge `GOAL.md` before accepting it.** Specifically:
   - Is Phase 0 correctly scoped, or is a standalone linter unbuildable without some of the IR? If it needs a minimal IR, say so and define the smallest one that works.
   - Which of the eight lint rules are **not** reliably detectable from a `.xlsx` alone, without the spec that generated it? I expect at least two are weaker than I've assumed. Rule 1 in particular: can you actually distinguish a scenario driver from any other named range by inspection?
   - Are the budget defaults defensible, or arbitrary? Which would you change and on what evidence?
   - Anything in the proposed stack you would replace.

3. **Take a position on the open question** — template slot-filling versus free generation. `GOAL.md` leans toward templates but does not settle it. Argue both sides and recommend one, with attention to what each does to Phase 0's design.

4. **Propose the repo structure** for Phase 0 only — directory tree, one line of purpose per module. Show where later phases will attach without requiring a rewrite.

5. **Propose the rule interface**: how a rule is declared, registered, configured, and reported. Rules are data-driven and independently testable. Include the machine-readable output shape (JSON) and the human-readable one.

6. **Write ADRs** in `docs/adr/` for: minimal-IR-or-none for Phase 0; rule registration and severity model; the template-versus-generative decision from item 3.

7. **Specify the fixture set**: one workbook per rule that violates exactly that rule, plus one clean workbook that passes all eight. Describe each fixture — do not build them yet.

8. **Create `BACKLOG.md`** from the non-goals section, one line each, with a note on what would trigger picking it up.

## How to work

- Ask where `GOAL.md` is underspecified. Do not fill gaps silently.
- **Where you think I am over-engineering, say so plainly.** The research warns specifically about over-engineered internal tooling. Eight rules, six budgets, five intake roles and a five-axis preset system may already be more than this needs. I would rather cut now than discover it in three months.
- Flag anything you cannot verify about library APIs or versions rather than guessing — `formulas` and its coverage limits especially.
- If you agree with everything in `GOAL.md`, you are not reading it critically enough.

Stop after these deliverables and wait for approval before implementing.
