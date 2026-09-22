"""Layered TOML configuration and waiver validation."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .registry import registered_rules
from .rule import DEFAULT_ALLOWED_LITERALS, DEFAULT_POSITIONAL_EXEMPTIONS, Severity, Waiver

CONFIG_FILENAME = "xllib.toml"

DEFAULT_THRESHOLDS = {
    "sheets_per_workbook": 10,
    "sections_per_sheet": 5,
    "distinct_formula_shapes": 40,
    "formula_depth": 4,
    "function_calls_per_cell": 2,
    "live_drivers": 6,
}

# Per-rule options that make a rule accept more than it otherwise would.
WIDENING_OPTIONS = ("allowed_literals", "positional_exemptions")


@dataclass(frozen=True, slots=True)
class Config:
    thresholds: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    rules: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    waivers: tuple[Waiver, ...] = ()
    sources: tuple[str, ...] = ("builtin",)

    def __post_init__(self) -> None:
        # `frozen=True` freezes the attribute, not the mapping behind it, so
        # `config.rules["XL002"] = {"severity": "off"}` silenced a rule after
        # the gate had already run — and a budget could be raised the same way,
        # which GOAL forbids in the same breath as granting waivers. Both
        # mappings become read-only copies before the gate reads them. Copying
        # also detaches them from the caller's dict, and because `copy.copy`
        # on a slots dataclass skips `__init__`, the copy inherits the frozen
        # view rather than getting a fresh mutable one.
        object.__setattr__(self, "thresholds", MappingProxyType(dict(self.thresholds)))
        object.__setattr__(
            self,
            "rules",
            MappingProxyType(
                {rule: MappingProxyType(dict(options)) for rule, options in self.rules.items()}
            ),
        )
        # The gates live here rather than in `load_config` because a gate a
        # caller can walk around by constructing the object directly is not a
        # gate. Every route to a Config now passes through them.
        authorised, refused = _waiver_index(self.waivers, date.today())
        _reject_unwaived_silencing(self.rules, authorised, refused)
        _reject_unwaived_loosening(self.thresholds, self.rules, authorised, refused)

    def options_for(self, rule_id: str) -> Mapping[str, Any]:
        return self.rules.get(rule_id, {})

    def severity_for(self, rule_id: str, default: Severity) -> Severity:
        value = self.options_for(rule_id).get("severity")
        if value is None or str(value).lower() == "off":
            return default
        return Severity(str(value).upper())

    def is_off(self, rule_id: str) -> bool:
        return str(self.options_for(rule_id).get("severity", "")).lower() == "off"

    def waiver_for(self, rule_id: str, locus: str) -> Waiver | None:
        today = date.today()
        for waiver in self.waivers:
            if waiver.rule != rule_id:
                continue
            if waiver.scope not in ("*", locus):
                continue
            if _waiver_defect(waiver, today) is None:
                return waiver
        return None


def _waivers(raw: dict[str, Any]) -> tuple[Waiver, ...]:
    result: list[Waiver] = []
    entries = raw.get("waivers", {}).get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("waivers.entries must be an array")
    for entry in entries:
        waiver = Waiver(
            rule=str(entry.get("rule", "")),
            scope=str(entry.get("scope", "")),
            reason=str(entry.get("reason", "")),
            approver=str(entry.get("approver", "")),
            expires=str(entry.get("expires", "")),
        )
        missing = [
            name
            for name in ("rule", "scope", "reason", "approver", "expires")
            if not getattr(waiver, name)
        ]
        if missing:
            raise ValueError(f"waiver missing required fields: {', '.join(missing)}")
        try:
            expiry = date.fromisoformat(waiver.expires)
        except ValueError as exc:
            raise ValueError(f"invalid waiver expiry: {waiver.expires}") from exc
        if expiry < date.today():
            raise ValueError(f"expired waiver: {waiver.rule} {waiver.scope}")
        result.append(waiver)
    return tuple(result)


def discover_config(start: Path | None = None) -> Path | None:
    """Find the nearest `xllib.toml` at or above `start`, within one project.

    The CLI used to look only in the process working directory, so the same
    workbook linted from a different folder silently lost the project's
    positional exemptions.

    **This does not fully solve that, and the docstring used to imply it did.**
    Discovery walks up from the *working directory*, by a decision recorded on
    2026-09-21, not from the target workbook's directory. In a monorepo whose
    `xllib.toml` sits in a subdirectory, running from the repository root still
    finds nothing and still falls back to built-in defaults. What changed is
    that the report now names the config in force, so the fallback is visible
    instead of silent. Anchoring on the workbook instead is an open operator
    decision, not an oversight — see `BACKLOG.md`.

    The walk stops at a project boundary: the first directory holding a `.git`
    entry, inclusive, or the home directory. Without it a stray `xllib.toml`
    left in a home directory would govern every run on the machine — a config
    route-around needing no waiver and leaving no trace, which is the whole
    class of defect ADR-0002 exists to prevent.
    """
    directory = (start or Path.cwd()).resolve()
    home = Path.home().resolve()
    for candidate in (directory, *directory.parents):
        found = candidate / CONFIG_FILENAME
        if found.is_file():
            return found
        if (candidate / ".git").exists() or candidate == home:
            return None
    return None


def load_config(path: Path | None = None) -> Config:
    thresholds = dict(DEFAULT_THRESHOLDS)
    rules: dict[str, dict[str, Any]] = {}
    sources = ["builtin"]
    waivers: tuple[Waiver, ...] = ()
    if path is not None:
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
        thresholds.update({key: int(value) for key, value in raw.get("budgets", {}).items()})
        rules = {str(key): dict(value) for key, value in raw.get("rules", {}).items()}
        waivers = _waivers(raw)
        _reject_unknown_rule_ids(rules)
        sources.append(str(path))
    return Config(thresholds, rules, waivers, tuple(sources))


def _reject_unknown_rule_ids(rules: Mapping[str, Mapping[str, Any]]) -> None:
    """A misspelled rule id must fail, not quietly do nothing.

    `XL0O2` with a letter O is not `XL002`. The severity lookup returned None
    for it, no gate fired, and the line the operator wrote had no effect on the
    run — a config that silently does not do what it says is worse than one
    that is rejected.

    This is checked only for file-sourced config. A caller constructing a
    `Config` in code passes its own rule set to `lint()`, so the registry is
    not authoritative for it; the silencing gate below is, and that one applies
    everywhere.
    """
    known = {rule.id for rule in registered_rules()}
    unknown = sorted(set(rules) - known)
    if unknown:
        raise ValueError(
            f"unknown rule id in config: {', '.join(unknown)}. "
            f"Registered rules: {', '.join(sorted(known))}"
        )


def _waiver_defect(waiver: Waiver, today: date) -> str | None:
    """Why this waiver authorises nothing, or None when it is good.

    One predicate, two callers: the silencing gate below and `waiver_for`.
    `_waivers` above is deliberately not a third — that one validates a TOML
    entry at the edge and rejects the file, which is a different question from
    whether a waiver already in memory authorises anything.

    The divergence this closes: the file loader checked approver, reason and
    expiry, and the in-memory gate checked none of them. So a `Config` built in
    code accepted an expired or unattributed waiver that the identical entry in
    `xllib.toml` would have been rejected for — and the gate's own error text
    claimed it required "a named approver" while never looking at the field.
    """
    if not waiver.approver.strip():
        return "it names no approver"
    if not waiver.reason.strip():
        return "it gives no reason"
    try:
        expires = date.fromisoformat(waiver.expires)
    except ValueError:
        return f"its expiry {waiver.expires!r} is not a date"
    if expires < today:
        return f"it expired on {waiver.expires}"
    return None


def _waiver_index(
    waivers: tuple[Waiver, ...], today: date
) -> tuple[set[str], dict[str, str]]:
    """Rule-wide waivers that authorise something, and the near misses that do not.

    Shared by both gates below, so a waiver cannot qualify for one and be
    refused by the other.
    """
    authorised: set[str] = set()
    refused: dict[str, str] = {}
    for waiver in waivers:
        if waiver.scope != "*":
            continue
        defect = _waiver_defect(waiver, today)
        if defect is None:
            authorised.add(waiver.rule)
        else:
            refused.setdefault(waiver.rule, defect)
    return authorised, refused


def _refuse(act: str, key: str, refused: Mapping[str, str]) -> None:
    message = f'{act} requires a waiver with a named approver and scope = "*"'
    # Naming the near miss matters: "no waiver" and "the waiver you wrote
    # lapsed last month" are different problems with the same old message.
    defect = refused.get(key)
    if defect is not None:
        message = f"{message}; the waiver present does not qualify because {defect}"
    raise ValueError(message)


def _is_widening(option: str, value: Any) -> bool:
    """Whether this option value makes the rule accept more than the default does."""
    if option == "positional_exemptions":
        try:
            return any(
                position not in DEFAULT_POSITIONAL_EXEMPTIONS.get(str(function), ())
                for function, positions in value.items()
                for position in positions
            )
        except (AttributeError, TypeError):
            return True
    try:
        configured = {float(item) for item in value}
    except (TypeError, ValueError):
        # Unparseable is not demonstrably a narrowing, so it is gated rather
        # than waved through. The rule itself will reject it on use.
        return True
    return not configured <= {float(item) for item in DEFAULT_ALLOWED_LITERALS}


def _reject_unwaived_loosening(
    thresholds: Mapping[str, int],
    rules: Mapping[str, Mapping[str, Any]],
    authorised: set[str],
    refused: Mapping[str, str],
) -> None:
    """Raising a budget or widening a rule needs the same waiver silencing needs.

    GOAL puts budgets under the same prohibition as waivers — "none silently
    raisable by the agent" — but the gate below reads `severity` and nothing
    else, so `[budgets]`, `allowed_literals` and `positional_exemptions` were
    free dials: a config file could raise every threshold and exempt every
    literal without naming an approver, which is the same route-around that
    switching a rule off already required a waiver for. Closed 2026-09-22 by
    operator decision.

    **Only the loosening direction is gated.** Lowering a budget or shortening
    `allowed_literals` makes the linter stricter, and a gate that fires on
    tightening is one people learn to route around.

    A budget is keyed by its own name rather than a rule id. The namespaces
    cannot collide because rule ids are `XLnnn`, and reusing `Waiver` rather
    than adding a second waiver shape keeps one validation path — which is
    what `_waiver_defect` was consolidated for in the first place.
    """
    for key, value in thresholds.items():
        default = DEFAULT_THRESHOLDS.get(key)
        # An unrecognised budget key is a different defect, and a silent
        # no-op rather than a loosening. Recorded in BACKLOG.md.
        if default is None or value <= default:
            continue
        if key in authorised:
            continue
        _refuse(f"raising the {key} budget from {default} to {value}", key, refused)
    for rule_id, options in rules.items():
        if rule_id in authorised:
            continue
        for option in WIDENING_OPTIONS:
            if option in options and _is_widening(option, options[option]):
                _refuse(f"widening {rule_id} through {option}", rule_id, refused)


def _reject_unwaived_silencing(
    rules: Mapping[str, Mapping[str, Any]],
    authorised: set[str],
    refused: Mapping[str, str],
) -> None:
    """Silencing a rule needs a named approver whose waiver covers the whole rule.

    ADR-0002 requires a waiver both to lower an ERROR rule and to switch a rule
    off. Four holes have been closed in turn, each found after the previous
    fix was called done:

    1. Only the ERROR case was enforced, leaving the four WARN rules — which
       carry GOAL's rules 5, 6 and 7 — removable by one unattributed line.
    2. The gate lived only in `load_config`, so `Config(rules={...})` bypassed
       it entirely. It is now called from `Config.__post_init__`.
    3. The waiver was matched on rule id alone, so a waiver scoped to a single
       cell authorised a rule-wide silence. A `[rules]` entry applies to every
       finding of that rule, so only a `scope = "*"` waiver authorises one.
    4. Scope was then the *only* thing checked, so an expired waiver, or one
       with an empty approver, still authorised silence in memory. See
       `_waiver_defect`.

    A fifth, of the same family, is `_reject_unwaived_loosening` above: this
    gate reads `severity` alone, so every other dial in the file was free.
    """
    if not rules:
        return
    defaults = {rule.id: rule.default_severity for rule in registered_rules()}
    for rule_id, options in rules.items():
        requested = str(options.get("severity", "")).lower()
        lowering_error = requested == "warn" and defaults.get(rule_id) == Severity.ERROR
        if not (lowering_error or requested == "off"):
            continue
        if rule_id in authorised:
            continue
        _refuse(f"silencing {rule_id}", rule_id, refused)
