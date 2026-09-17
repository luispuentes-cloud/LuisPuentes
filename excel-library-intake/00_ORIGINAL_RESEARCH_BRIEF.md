# Research Brief — Excel Prior Art for a Consulting Workbook Library

**How to use this:** paste or attach the whole document to a research-capable
Claude session with web access. It is written to be self-contained.

**Confidentiality:** this brief contains no client names, figures, or source
material, and the receiving session must not be given any. Everything below is
generic tradecraft. Keep it that way.

---

## Objective

I am about to build a reusable internal library of standards and tooling for
building consulting financial models in Excel. Before I build anything, I want
to know what already exists at the top of this field, what is genuinely
authoritative versus merely popular, and what I should adopt rather than
reinvent.

Be rigorous and opinionated. I would rather be told my approach is wrong than
be agreed with.

---

## Context — what I do and where it hurts

I build value cases, cost models, and margin models for enterprise consulting
engagements. Typical characteristics:

- Excel workbooks of roughly 10–15 visible tabs.
- Generated **programmatically** from Python (`openpyxl`) with a shared styling
  scaffold, then recalculated by driving desktop Excel through COM, because
  `openpyxl` does not evaluate formulas.
- A live driver/input section, a calculation engine, scenario comparisons, cost
  build-ups, reconciliation against source-of-truth models, and an executive
  walk from current state to target.
- Audience is split and this is the core tension: **partners and client
  executives** who need to read a headline and explain it upward, and
  **analysts and reviewers** who need to audit the arithmetic.
- Outputs frequently get screenshotted into slide decks.

### The specific failure mode I want solved

The models are analytically sound but have become hard to follow, and the same
problem recurs on every iteration no matter how many times it is cleaned up.
Two concrete symptoms:

**1. Scenario logic hidden inside formulas.** A recent sheet had one input
table and three result columns, where the only thing distinguishing the columns
lived inside the formulas. A representative cell, repeated once per row:

```
=IF(SUM($I$4:$I$15)=0,"N/A — no FTE load",K4*FTE_TARGET/SUM($I$4:$I$15))
```

The defining input (`FTE_TARGET`) is a named range that appears nowhere on the
sheet, so a reader genuinely cannot answer "how was this number produced?" from
the sheet. The denominator is recomputed on every row, the zero-guard is
duplicated a dozen times, and a text string is written into a currency column
where it silently breaks downstream sums. Adjacent columns were also produced
by *different mechanics* — one a pro-rata rescale, one a scope filter — while
presented as if parallel.

**2. Structural bloat.** Too many sections per sheet. Each one is individually
justifiable; collectively they defeat the reader.

My working hypothesis is that prose standards do not fix this. I already have a
thorough internal methodology document and it drifts, because nothing fails
when it is violated. I believe the missing piece is **mechanical enforcement**.
Tell me if that hypothesis is wrong or incomplete.

---

## What I want answered

Treat each numbered section as a required part of the deliverable.

### 1. What represents elite practice, and who says so

Inventory the bodies of work that constitute the top of this field. For each,
state what it is, who maintains it, its licence/cost, and its standing.

**Critically, separate these three tiers and never conflate them:**

- **(a) Formal published standards** with a named maintaining body.
- **(b) De facto industry convention** — widely adopted, unwritten or
  semi-written, often bank- or firm-specific.
- **(c) Individual practitioner opinion** — influential authors, trainers,
  bloggers.

Starting points I believe are relevant. **Confirm, correct, or reject each, and
add what I have missed.** Do not simply affirm my list.

- FAST Standard (Flexible, Appropriate, Structured, Transparent)
- ICAEW *Twenty Principles for Good Spreadsheet Practice*
- SMART financial modelling methodology / Corality lineage; Modano
- Operis and the Operis Analysis Kit approach to model audit
- EuSpRIG (European Spreadsheet Risks Interest Group) and the academic
  literature on spreadsheet error rates
- Financial Modeling Institute certifications (AFM/CFM) and what they actually
  examine
- Investment-banking formatting conventions, including the Macabacus-style
  colour convention
- IBCS (International Business Communication Standards) for reporting and
  scenario notation
- Enterprise governance frameworks: End User Computing (EUC) controls,
  SOX-driven spreadsheet controls, and model risk management guidance such as
  SR 11-7
- Named authors: Michael Rees, Danielle Stein Fairhurst, John Tjia, Simon
  Benninga, and anyone more current

For each, tell me whether it is **actually used in practice** or merely
published.

### 2. What makes it elite

Do not restate rules. Identify the underlying principles and, specifically:

- Which principles are **shared across every serious standard** — the invariant
  core that is not up for debate.
- Where the standards **genuinely disagree**, and what the disagreement is
  about.
- Which rules exist for **auditability** versus **maintainability** versus
  **communication**, since these sometimes conflict.
- What the **evidence base** is. Are there measured error rates, audit findings,
  or documented failures that justify particular rules? I need this to defend
  the investment upward.

### 3. What I can integrate or build on

- What is **free or openly licensed** and adoptable as-is?
- What is copyrighted or certification-gated, such that I can learn from it but
  not redistribute it?
- What **tooling** exists for building, auditing, validating, and diffing
  workbooks — commercial and open source? Include anything with an API or CLI
  that could run in an automated pipeline.
- Is there an existing **open-source library or framework** that already does
  what I am proposing? If so, say so plainly and tell me to use it.

### 4. Formatting, structure, and colour

- What are the **competing colour conventions**, where did each originate, and
  which is most immediately recognised by a finance or audit audience? I am
  particularly interested in the blue-font-for-inputs convention versus
  fill-based conventions, and which signals "editable input" most reliably.
- **Accessibility:** colour-blind-safe palettes, and the rule that meaning must
  never be encoded in colour alone. How do serious standards handle this?
- **Layout conventions:** sheet ordering, navigation, consistent time axes,
  row/column structure, one-formula-per-row consistency, freeze panes, grouping,
  print and PDF fidelity.
- How should a workbook be designed so it **survives being screenshotted into a
  slide**, which is a real delivery path for my work?
- What are the conventions for **flagging** input versus calculation versus
  link versus external reference versus error?

### 5. Best ways of working

- What does an elite **workflow** look like end to end: specification, build,
  review, sign-off, change control?
- **Version control** for binary workbooks. What actually works?
- **Build-from-spec versus hand-built.** I already generate workbooks from
  Python. Is a formal declarative specification (YAML/JSON that compiles to a
  workbook) a recognised practice, and does it pay off?
- **Testing.** Is there a real practice of test-driven or assertion-based
  modelling — declaring expected outputs and asserting them? What about
  golden-master or invariant testing across versions?
- **Model review.** What does a professional model audit actually check, in what
  order, and is there a published checklist I should adopt?
- How do teams prevent **drift** back into complexity over successive versions?
  This is my central problem.

### 6. What I am not doing that would improve output

- **Modern Excel features.** How much do `LET`, `LAMBDA`, dynamic arrays,
  structured Tables, and Power Query genuinely change best practice? Be
  sceptical here: `LET` makes a long formula more readable by naming
  intermediates, but in my example above it would *still* hide the scenario
  input inside the formula. Does it actually improve auditability, or does it
  just make hidden complexity more comfortable to write? Take a position.
- **Formula transparency tooling.** Excel Labs / Advanced Formula Environment,
  formula commenting, dependency tracing, any way to make a formula
  self-documenting.
- **Evaluating formulas outside Excel.** Python libraries that can compute
  Excel formulas without opening Excel. Are any production-grade? This matters
  because my current recalculation step depends on driving desktop Excel.
- **Automated diffing of workbooks** for review and for CI.
- **AI-assisted modelling:** prompts, operating models, agent patterns, and
  guardrails specifically for generating and reviewing spreadsheets. What are
  the known failure modes of AI-built models and how do people control for them?
- Any **operating model** — roles, rituals, gates — that materially improves
  output quality.

### 7. Critique and blind spots

- Where is my approach wrong, naive, or over-engineered?
- Is mechanical enforcement the right bet, or is the real problem elsewhere?
- **The two-audience problem.** How do elite practitioners build one artifact
  that an executive can read and explain upward, while an analyst can audit it?
  Is the answer progressive disclosure within one workbook, or genuine
  separation of model from report? What is the recognised pattern?
- **The explain-upward requirement specifically.** If someone must defend a
  number in a room without the model open, what does the workbook owe them? Is
  there a documented pattern for this — a methodology note, an assumptions
  page, a narrative layer?
- What will I regret in twelve months?
- What have I not asked about that matters more than what I did ask about?

---

## Deliverable format

1. **Executive answer first** — the five things that matter most, stated
   plainly, before any detail.
2. **Landscape table** of standards and tooling: name, maintainer, tier (a/b/c
   from section 1), licence/cost, adoptable yes/no, relevance to me.
3. **The invariant core** — the principles every serious standard agrees on,
   as a short list I could adopt verbatim.
4. **Recommended adoption path**, sequenced, with effort and impact for each
   step, and an explicit "do this first."
5. **Specific artifacts to steal** — named checklists, conventions, templates,
   tools, with links.
6. **A dissent section** — where you think I am wrong, and what you would do
   instead.
7. **Open questions** you could not resolve, and what would resolve them.

---

## Standards for your answer

- **Cite sources with links.** Where something is behind a paywall or
  certification, say so.
- **Flag confidence.** Distinguish what you verified from what you believe from
  what you are inferring. If a "standard" may not exist as such, say so — the
  main failure mode of this kind of research is confidently describing
  authoritative-sounding standards that turn out to be one consultant's blog
  post.
- **Prefer primary sources** over summaries and aggregator listicles.
- **Do not give me a tips listicle.** No "top 10 Excel hacks." I am asking about
  standards, governance, structure, and workflow.
- Where practice has **changed recently**, say what changed and when. Some of
  the canonical modelling literature predates dynamic arrays and `LAMBDA`
  entirely.
- Be concrete. Named bodies, named tools, named documents, real links.
