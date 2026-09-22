# ADR-0007 — What config discovery anchors on

- **Status:** Proposed — recommendation stated, operator sign-off pending.
- **Date:** 2026-09-22
- **Deciders:** Project Owner (pending)
- **Relates to:** [ADR-0002](0002-rule-registration-and-severity.md), `lint/config.py::discover_config`

## Why this ADR exists

`discover_config`'s own docstring defers the question:

> Anchoring on the workbook instead is an open operator decision, not an
> oversight — see `BACKLOG.md`.

The 2026-09-22 adversary pass then found a second defect in the same function,
and the two share a root cause, so they should be settled together rather than
patched apart.

## The question

> When `xllib lint PATH` looks for `xllib.toml`, does it walk up from the
> working directory or from the directory holding `PATH`?

## Current behaviour, stated precisely

```python
directory = (start or Path.cwd()).resolve()
home = Path.home().resolve()
for candidate in (directory, *directory.parents):
    found = candidate / CONFIG_FILENAME
    if found.is_file():
        return found
    if (candidate / ".git").exists() or candidate == home:
        return None
```

Two properties follow, and only the first is documented.

**1. The anchor is the working directory.** The same workbook linted from two
different shells can resolve two different configs, and therefore report two
different sets of findings. The report names the config in force, so the
divergence is visible after the fact; nothing prevents it.

**2. The home-directory guard does not do what its comment claims.** The
comment says the boundary exists so that "a stray `xllib.toml` left in a home
directory would [not] govern every run on the machine." But the `found` check
precedes the boundary check, so when the walk reaches home without having
passed a `.git`, `~/xllib.toml` **is** returned and does govern the run. Home
is inclusive, exactly like the `.git` directory itself. The guard stops the
walk from going *above* home; it does not stop home's own config from winning.

Whether property 2 is a bug depends entirely on how property 1 is decided,
which is why this is one ADR and not two.

## Options

**A — Status quo: anchor on the working directory.** *For:* zero change; matches
the intuition that a tool run in a project uses that project's settings.
*Against:* the finding set for a file becomes a property of the operator's
shell. In a monorepo whose `xllib.toml` sits in a subdirectory, running from
the repository root finds nothing and silently falls back to built-in defaults
— the case the docstring already admits it does not solve.

**B — Anchor on the workbook's directory.** Walk up from `PATH`'s parent.
*For:* the report is about the workbook, so the config governing it should be a
property of the workbook's project rather than of where the operator happened
to be standing. It makes a run reproducible from its own output, which is the
same property the byte-stable `findings` block exists to give. It is also what
every comparable tool does — ruff, mypy and eslint all resolve configuration
relative to the file under inspection, not to `cwd`. *Against:* linting a
workbook that happens to sit inside someone else's project silently adopts that
project's exemptions. Mitigated, not removed, by the report naming the source.

**C — Explicit only.** Drop discovery; use `--config` or built-in defaults.
*For:* maximally reproducible and impossible to get wrong by accident.
*Against:* every invocation grows a flag, and a forgotten flag silently
downgrades to defaults — trading a visible wrong config for an invisible
absent one.

**D — Workbook first, working directory as fallback.** *For:* convenience.
*Against:* two discovery paths means the answer to "which config governs this
file" is "it depends," which is the property this ADR is trying to remove.
Rejected on that ground rather than on cost.

## Recommendation

**Option B, with the home directory made exclusive.**

The reasoning is that a lint report should be a function of the file and the
project it lives in, and of nothing else. Option A makes it a function of the
shell as well. The library's own design already commits to this standard
elsewhere: findings are sorted for byte-stability so two runs on one file agree,
and the config source is printed so a report can be reproduced from its own
output. An anchor that varies with `cwd` undercuts both.

Making home exclusive — checking the boundary before the `found` lookup when
the candidate is home — then matches the comment already in the code. A config
in a project directory that also happens to be home stays reachable by
`--config`, which is the explicit path and leaves a trace.

This recommendation is stated rather than taken. It changes resolution
behaviour for every existing invocation, which is an operator call.

## Consequences

If B is adopted: `discover_config` takes the workbook path rather than
defaulting to `Path.cwd()`, the CLI passes it, and the Med-severity home
finding closes in the same change. Existing discovery tests already plant a
`.git` boundary explicitly, so they are anchor-agnostic and should survive.

If A is retained: the home-inclusive behaviour still needs settling, because
the comment currently describes a protection the code does not implement. Fix
the code or fix the comment — the present state is the one thing that is not an
option.

Phase 0 can ship either way. Nothing here changes what the rules find; it
changes only which config decides whether they run.
