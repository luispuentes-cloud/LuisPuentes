# Backlog

Deferred work, each with the trigger that should cause it to be picked up. An item
here is not a plan; it is a decision already made to *not* do something yet, with
the condition under which that decision gets revisited.

Sourced from GOAL.md's non-goals, plus items cut during Phase 0 design.

---

## Deferred non-goals (from GOAL.md)

| Item | Pick up when |
|---|---|
| Formula parser or evaluator of our own | Never, by preference. Recalculation uses `formulas` in Phase 0 (ADR-0004); inspection uses the openpyxl tokenizer walk (ADR-0001). Revisit only if both prove insufficient for a required rule. |
| Wrapping the full openpyxl API | Never. Wrap only what an emitter or loader needs, when it needs it. |
| Reading arbitrary workbooks losslessly | Never — GOAL is right that a lossless importer is an anti-feature, because the "here is the 19% I cannot express" conversation *is* the de-bloating mechanism. |
| Charts beyond preset minimums | A preset requires a chart that cannot be supplied as a screenshot-ready table. |
| `LET` / `LAMBDA` / dynamic arrays / Power Query | Deliberate exclusion: they improve write-comfort, not auditability. Revisit only if a client mandates a workbook that already uses them, which becomes an intake problem rather than a generation one. |
| GUI or web app | Never for this library. The CLI plus the chat interview is the surface. |
| Non-Excel targets | A deliverable is required in another format. Keeping Layers 0–2 free of Excel-specific semantics is what would make this cheap; that is not currently a goal. |
| Commercial tool integration (OAK, PerfectXL, xltrail) | Licensed access is confirmed. Until then, unknown availability makes design speculative. |
| Database and BI graduation for monitored value cases | Explicitly a separate product per the addendum. Trigger: a value case is tracked past 12 months with scheduled actuals ingestion. Do not let its requirements leak into the one-off generator as configuration. |
| AI-generated specs that bypass the interview | Never. The interview is the determinism boundary; bypassing it relocates drift up a layer. |

## Lint rules cut from Phase 0

Both are good ideas from the lane's earlier notes, and neither is in GOAL's eight.
Adding them during Phase 0 design would have been precisely the drift this project
exists to prevent.

| Rule | Pick up when |
|---|---|
| `inconsistent-column-semantics` — adjacent columns in one row presented as parallel while carrying different *kinds* of quantity, detected by comparing `Cell.number_format` and label applicability across the row's columns | **Now the strongest candidate, ahead of the two below.** Added 2026-09-21 from [EXPERIMENT_B.md](docs/EXPERIMENT_B.md), which is the "caught a real bug" evidence GOAL's rule-addition policy asks for: fixture B2b reproduces reference failure (b) in full and lints clean at exit 0, because XL003 discriminates on formula shape and the two columns normalise identically. The signal that would catch it is already in the IR — the right-hand column carries `0.0%` on a row labelled "Hours saved". Pick up once GOAL rule 1's off-sheet scope is settled, since both touch what a reader can conclude from one sheet. |
| `repeated-aggregate-in-run` — the same identical range aggregated on every row of a run, where a single shared scalar belongs | Every Phase 0 rule has caught a real bug, per GOAL's rule-addition policy. |
| `blanket-iferror` — `IFERROR` wrapping a whole expression instead of an explicit precondition test | As above, and additionally requires formula structure rather than token sequence, so it also triggers the ADR-0001 revisit. |

A caution on the first row, recorded so it is not lost between sessions: XL003
catches the version of this failure a human reviewer would also catch, and
misses the version that survives review. Formula shape correlates inversely
with how deceptive the rendering is. That is an argument for the new rule, and
also a reason to expect the existing one's real-world hit rate to be lower than
its fixture coverage suggests.

## Structural items deferred with reasons

| Item | Pick up when |
|---|---|
| The five-role intake taxonomy | Three real intakes have happened and can name their own roles. Predecessor and Source are clearly real; Seed and Subject look like one thing with two output modes; Constraint may reduce to "waivers exist". |
| The five-axis preset system | A third preset exists. Until then, hard-code one preset in Phase 1; the axes are a thinking tool, not yet an implementation. |
| Block-type vocabulary cap of 20 | The vocabulary has members. It currently has none, so the cap is a promise rather than a constraint. |
| Budget threshold calibration | `--measure` has been run across the existing workbook corpus. Every budget default is currently a guess; the distribution converts six guesses into six measurements for the cost of one output mode. |
| Version control for this repo | Monorepo at orchestrator root with lane worktrees (2026-09-17). Remaining: named remote, then the first Linux CI run on that remote. Do not invent a GitHub repo. |
| Disposition of `xldump.py` and `xlbuild.py` | Closed for `xldump.py`: leave it alone (Q6). Add a one-line pointer once Phase 0 ships. `xlbuild.py` stays fenced with the Framework lane until that pointer lands. |
