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
| Budget threshold calibration | **Trigger fired 2026-09-23.** `--measure` run in place across 8 real business-case workbooks. 6 of the 8 breach at least one budget, and two defaults — `sections_per_sheet` at 5 and `function_calls_per_cell` at 2 — sit *below* the observed median, so as shipped they would hard-stop most real work. The six guesses are now six measurements. Budgets deliberately left unchanged: raising one goes through the loosening gate and GOAL forbids the agent doing it silently. Decision sits with Orchestrator Brain; per-workbook numbers are in the Framework tracker, de-identified. Caveat: 8 workbooks from about four engagements is conventions, not statistics. |
| `.xlsb` read support | A licence decision on `pyxlsb`, which is **LGPLv3+**. Two of the ten shortlisted calibration workbooks are `.xlsb`, and they are the submitted business case and the reworked/rejected model — the two types the sourcing brief rates highest. `pyxlsb` is already present in this environment and opens one of them cleanly, so the blocker is licence and packaging, not capability. `openpyxl` will never read `.xlsb`; it says so and exits 3, which is the right behaviour until this is settled. |
| Version control for this repo | Monorepo at orchestrator root with lane worktrees (2026-09-17). Remaining: named remote, then the first Linux CI run on that remote. Do not invent a GitHub repo. |
| Disposition of `xldump.py` and `xlbuild.py` | Closed for `xldump.py`: leave it alone (Q6). Add a one-line pointer once Phase 0 ships. `xlbuild.py` stays fenced with the Framework lane until that pointer lands. |

## Residuals from the loosening gate (2026-09-22)

Found in-lane while building `_reject_unwaived_loosening`, and deliberately
kept out of that diff. Both are real; neither is what the operator approved,
and GOAL caps the diff per increment.

| Residual | Pick up when |
|---|---|
| An **unrecognised budget key** in `xllib.toml` is a silent no-op. `load_config` does `thresholds.update(...)` with whatever keys the file holds, so `formula_dept = 99` sets a key nothing reads and the operator believes a budget was raised. This is the identical defect `_reject_unknown_rule_ids` exists to reject for rule ids, and the same argument applies: a config that silently does not do what it says is worse than one that is rejected. Fails safe (strict), which is why it is not urgent | Next time `config.py` is opened. The fix mirrors `_reject_unknown_rule_ids` — file-only, in `load_config`, not in `__post_init__`, because `Rule.thresholds` lets a rule legitimately declare a key that is not a built-in budget |
| **`Rule.thresholds` bypasses the gate.** `api.py` builds `RuleContext` as `{**config.thresholds, **rule.thresholds}`, after `Config.__post_init__` has run, so a rule declaring its own threshold overrides a gated budget with no waiver. All ten rules currently pass `{}`, so nothing exploits it today | When any rule first declares a non-empty `thresholds`. Editing rule *code* is a larger trust boundary than editing a TOML, so this is a lower-severity hole than the config one it mirrors — but it is the same hole |

## Test-bite review (2026-09-22)

Independent revert-and-restore pass on `3f20930` and `8976088`. Verdict
**PARTIAL**. The silencing gate, unknown-rule rejection, the `.git` discovery
boundary and the `--measure` counts are all genuinely bitten. Two gaps:

| Gap | Status |
|---|---|
| `assert_readable` before recalc was **not** bitten — reverting it left both exit-3 tests passing, because the file reached the recalc chain and returned 3 from the `UNREADABLE` handler ~70s later. The exit code cannot distinguish the two paths | **Closed 2026-09-22.** `test_an_unreadable_file_is_refused_before_recalculation` asserts `recalculate` is never reached |
| The **home-directory** stop in `discover_config` has no dedicated test; only the parent-`.git` case is covered | **Left open deliberately.** [ADR-0007](docs/adr/0007-config-discovery-anchor.md) recommends changing this behaviour, and pinning it with a test now would fix the thing under review. The test lands with the ADR's resolution |

## Silencing-gate review (2026-09-22)

Independent adversary pass on HEAD `d004b10` (`config.py` not dirty). Constructor, `dataclasses.replace`, `scope="*"` per-rule, unknown-id in `load_config`, and worktree `.git`-as-file discovery **hold**.

**Status: every High and Med hole below is closed.** All four went in `f8d9738`; the rows carry their own evidence. Re-verified against `config.py` on 2026-09-22 before Phase 0 was declared shipped, because the "pick up when" column had gone stale and still read as three open High blockers after the fix had landed. Nothing in this section gates shipping.

**Provenance caveat — these findings were recovered, not reported.** The brief
that produced them stalled without returning: twice, in fact, once in the
session that first launched it and again on relaunch, which errored with
"repeated resume attempts made no progress". It plainly ran — it left a probe
file behind and wrote this section directly — and five of its six required
deliverables are present below. The **model line and the verdict one-liner are
not**, so completeness is unconfirmed and no model attribution is possible.
Treat the holes listed here as a genuine independent pass, but not as an
exhaustive one; an absent finding is not evidence of an absent hole.
**Do not relaunch that brief as written.** Two stalls on one prompt is a fact
about the prompt, not the runner — it asked for adversarial reasoning plus
probes across four claims in one turn on a machine where every shell call
costs 40–90s. Split it, or run it in-lane.

**Closed, do not reopen:** put `_reject_unknown_rule_ids` in `Config.__post_init__`. **No.** `lint()` takes an arbitrary `rules` tuple; unknown-id is a file/CLI check. Doing it in `__post_init__` would block programmatic custom rules and would not close the misspelling hole twice.

| Hole | Severity | Pick up when |
|---|---|---|
| `config.rules` is a mutable dict; post-init mutation (and `copy.copy`) silences without a waiver | High | **Closed 2026-09-22 by `f8d9738`.** `__post_init__` replaces the mapping with a `MappingProxyType` copy, nested per-rule options included, before either gate reads it. `copy.copy` on a slots dataclass skips `__init__`, so the copy inherits the frozen view rather than a fresh mutable one |
| `config.thresholds` is a mutable dict of the same shape, so a budget can be raised post-construction with no waiver and no trace. **Not flagged by the adversary pass — found in-lane 2026-09-22 while fixing the row above.** GOAL's budgets are "none silently raisable by the agent." Note `report.py` serialises `config.thresholds` directly, so freezing it needs a `dict()` at the report boundary | High | **Closed 2026-09-22 by `f8d9738`**, with the row above — same mechanism, same `__post_init__` |
| Expired `scope="*"` waiver still authorises silence on direct `Config`; file path rejects it | High | **Closed 2026-09-22 by `f8d9738`.** `__post_init__` builds the index through `_waiver_index(self.waivers, date.today())`, so the in-memory path applies `_waiver_defect` on the same terms the file loader does |
| Empty `approver`/`reason` still satisfy the in-memory gate; error text claims otherwise | Med | **Closed 2026-09-22 by `f8d9738`**, in the same pass as the expired-waiver row — `_waiver_defect` is the one validation path for both |
| Walk will load `~/xllib.toml` if no `.git` sits above the start dir (home is inclusive, contra the stray-home comment) | Med | Raised as [ADR-0007](docs/adr/0007-config-discovery-anchor.md), Proposed — it closes with the anchor decision, since the two share a root cause |
| `object.__new__` / `object.__setattr__` skip the gate | Low | Never, unless someone starts constructing Config that way in production |
| Unknown ids on direct `Config` (misspell as `warn` is a silent no-op) | Low | Closed as a `__post_init__` change; leave as file/CLI only |
