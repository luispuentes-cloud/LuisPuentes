# Addendum — Living Value Cases vs One-Off Analyses

**Scope:** extends the main report, which implicitly assumed a build-review-sign-off-ship lifecycle. A monitored value case has requirements the one-off case does not, and three of the main report's recommendations reverse.

---

## 1. What the main report already covers (honestly: not much)

Directly transferable: spec-in-Git with `.xlsx` as build artifact; golden-master and assertion testing; automated diffing; model/report separation; IBCS scenario notation; SR 11-7's validation vocabulary; the EUC-governance vendor ecosystem (CIMCON, Apparity, Workscope, ClusterSeven) — which is *specifically* built for recurring spreadsheets, and which the report wrongly framed as regulated-bank-only.

What it misses entirely: baseline immutability, actuals ingestion, variance decomposition, period-roll mechanics, and the entire benefits-realisation literature. The report treats a workbook as a document. A living value case is closer to an application with a data pipeline.

---

## 2. The architectural core: three ledgers, not one set of numbers

A one-off model has one set of numbers — the answer. A living value case has three, with different lifecycles, different permissions, and different tests:

| Ledger | Mutability | Changed by | Test |
|---|---|---|---|
| **Baseline** | Immutable once approved | Formal change control only | Bit-identical regression test, forever |
| **Forecast** | Freely updated each cycle | Model owner | Invariant tests only |
| **Actuals** | Append-only | Scripted ingestion, never typed | Reconciliation to source system |

Plus a fourth artifact that isn't numbers: a **baseline change log** — every baseline change with date, approver, reason, and the superseded values retained.

This maps cleanly onto IBCS scenario notation (PL/BU for plan/budget, FC for forecast, AC for actual, PY for prior year), which is the strongest argument for adopting IBCS that the main report failed to make.

**The single highest-risk failure mode in the living case — and it does not exist in the one-off case at all:** someone edits a baseline assumption during a routine monthly refresh. Variance history silently becomes meaningless. Nobody notices for two quarters. Your driver block must *visibly* separate frozen baseline assumptions from revisable operating assumptions, and your generator should refuse to emit a workbook where a baseline cell is unprotected.

The governing principle, well established in project controls and worth adopting verbatim: **re-forecasting does not require baseline change control; re-baselining does.** Re-baselining in response to poor performance destroys the meaning of variance — if the benchmark moves whenever performance misses it, the baseline stops measuring anything. SR 11-7 makes the same point from the model-risk side: performance benchmarks must be defined *before* results are known, not reverse-engineered afterwards.

---

## 3. What changes concretely

**Time axis becomes a moving window.** A one-off model has fixed columns. A living model rolls. This is where my scepticism about structured Tables reverses: for actuals, store **long-format** (one row per period × benefit line × measure) in a Table, and *generate* the wide presentation grid from it. Wide grids break every time you add a period; a long table with a period key does not.

**Variance decomposition becomes a required tab.** "Actual ≠ baseline" is useless on its own. You need a bridge: volume, rate, timing, scope change, baseline error. Without decomposition, every monthly review degenerates into an unresolvable argument about whether the model was wrong or the business underdelivered — and that argument is what kills value cases politically, not model quality.

**Reconciliation flips direction.** In the one-off case you reconcile *to* a source-of-truth model. In the living case you reconcile to *actuals from source systems*, on a schedule. That means the data pull must be scripted. Your COM-driven recalculation stops being a one-time inconvenience and becomes a recurring operational dependency — which materially strengthens the case for moving to `formulas` or headless LibreOffice.

**Golden-master testing splits in two.** For a one-off, golden master means "outputs didn't change unexpectedly." In a living model outputs *should* change every period. So: assert baseline outputs are bit-identical forever (a true regression test), and check forecast outputs only against invariants. Conflating these gives you either a test that always fails or a test that never catches anything.

**Provenance moves from blind spot to primary requirement.** Every actual carries source system, pull date, and sign-off. The main report listed lineage as something you hadn't asked about; in the living case it's load-bearing.

---

## 4. The prior art you didn't ask about

This is the **benefits realisation management (BRM)** literature. It is a genuinely separate body of work from the spreadsheet-standards world, and it is where the living-model patterns actually live.

**Tier (a) — formal, named maintaining body**

- **MSP (Managing Successful Programmes)** — AXELOS/PeopleCert lineage (originally UK Cabinet Office/OGC). Named artifacts: benefits management strategy, benefits map, **benefit profiles**, benefits realisation plan. *Verified* that these artifacts exist and are core to the framework. The **benefit profile** is the single most directly stealable structure for you: it is effectively a per-benefit spec — definition, measure, owner, baseline value, target value, realisation timing, dependencies. That is your YAML schema, already designed. Paid manual.
- **PMI, *Benefits Realization Management: A Practice Guide*** (2019, ISBN 9781628254808; PMI's first standards publication of its 50th-anniversary year). *Verified.* Contains core BRM principles and critical success enablers, one of which is explicitly "Establish Benefits Tracking." Paid. Aligns to PMBOK 6th / Standard for Program Management 4th.
- **SR 11-7** — already in the report, but under-sold. Its three validation activities are *precisely* the living-model problem: conceptual soundness, **ongoing monitoring** (process verification, benchmarking), and **outcomes analysis** (back-testing against actuals). Free, and the vocabulary travels well to non-bank clients.

**Tier (b)/(c) — influential, not standards**

- **Cranfield Benefits Management process model and Benefits Dependency Network (BDN)** — Ward & Daniel, *Benefits Management: Delivering Value from IS and IT Investments* (Wiley 2006; 2nd ed. 2012); Peppard, Ward & Daniel, *MIS Quarterly Executive* (2007); Joe Peppard, HBR (2016). *Verified.* Five-stage cycle: identify and structure benefits → plan realisation → execute → **review and evaluate** → identify further potential. That fourth stage is exactly what your workflow lacks. The BDN itself is a one-page, right-to-left map from business drivers → objectives → benefits → business changes → enablers, with a named owner per benefit. **Adopt the BDN as your narrative layer — it *is* the "explain upward" artifact the main report said you needed, and it already exists.** Academic/book sources are copyrighted; the technique is freely describable.
- Firm benefits-management guides (PwC and others) — convention, not standard.

**Confidence note:** I found no published standard for *spreadsheet-based* benefits tracking specifically. The BRM standards are method-level and silent on workbook mechanics; the spreadsheet standards (FAST, ICAEW) are silent on baselines and actuals. That gap is real, and it is where your library adds genuine value rather than duplicating prior art.

---

## 5. Where my earlier advice reverses

1. **Structured Tables:** was lukewarm; for actuals ingestion they are close to mandatory.
2. **Sign-off as a terminal gate:** becomes a recurring per-period gate with a named owner per benefit line.
3. **Excel as the home:** for a one-off, fine. For a value case tracked over 18+ months, Excel is the wrong long-term home. Stated plainly: the living case should graduate to a database plus a BI layer, with Excel demoted to a reporting client. The moment you add scheduled actuals ingestion you are building an ETL system with a spreadsheet front end, and that is a different engineering discipline from model generation.

---

## 6. Dissent — what I would actually do

**Do not build one library for both cases.** Build the one-off library first; it is the tractable, bounded problem and it is where your current pain is. Treat the living value case as a *separate product* with a data pipeline, not as a one-off model that gets re-run. The failure mode of merging them is that living-case requirements (period roll, ingestion, baseline immutability) leak into the one-off generator as configuration complexity nobody needs.

**And solve the political problem before the technical one.** What kills monitored value cases is almost never model quality — it is that after nine months nobody agrees what the baseline was or who changed it. The frozen baseline plus change log, with an owner per benefit line, buys more than any amount of linting.

**Living-case specific regrets, 12 months out:** baseline assumptions quietly edited during a refresh; period columns hand-added until the grid breaks; the value case outliving its author with the spec as the only documentation; and actuals reconciliation that was never scripted, so it silently stops happening.

---

## 7. Open questions

- Which of MSP's benefit-profile fields survive contact with your clients? Resolvable by mapping one real (anonymised) benefit line against the profile structure.
- Whether your clients will accept scripted actuals ingestion at all, or will insist on manual submission — this single answer determines whether the living case is engineerable or merely documentable.
- Whether any BRM tooling vendor already does baseline/forecast/actual with proper change control well enough to buy rather than build. I did not survey this market; it would take a dedicated pass.
