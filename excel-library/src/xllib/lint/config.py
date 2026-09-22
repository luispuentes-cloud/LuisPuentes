"""Layered TOML configuration and waiver validation."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .registry import registered_rules
from .rule import Severity, Waiver

CONFIG_FILENAME = "xllib.toml"

DEFAULT_THRESHOLDS = {
    "sheets_per_workbook": 10,
    "sections_per_sheet": 5,
    "distinct_formula_shapes": 40,
    "formula_depth": 4,
    "function_calls_per_cell": 2,
    "live_drivers": 6,
}


@dataclass(frozen=True, slots=True)
class Config:
    thresholds: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    waivers: tuple[Waiver, ...] = ()
    sources: tuple[str, ...] = ("builtin",)

    def __post_init__(self) -> None:
        # The gate lives here rather than in `load_config` because a gate a
        # caller can walk around by constructing the object directly is not a
        # gate. Every route to a Config now passes through it.
        _reject_unwaived_silencing(self.rules, self.waivers)

    def options_for(self, rule_id: str) -> dict[str, Any]:
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
            if date.fromisoformat(waiver.expires) >= today:
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


def _reject_unknown_rule_ids(rules: dict[str, dict[str, Any]]) -> None:
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


def _reject_unwaived_silencing(
    rules: dict[str, dict[str, Any]], waivers: tuple[Waiver, ...]
) -> None:
    """Silencing a rule needs a named approver whose waiver covers the whole rule.

    ADR-0002 requires a waiver both to lower an ERROR rule and to switch a rule
    off. Three holes have been closed in turn, each found after the previous
    fix was called done:

    1. Only the ERROR case was enforced, leaving the four WARN rules — which
       carry GOAL's rules 5, 6 and 7 — removable by one unattributed line.
    2. The gate lived only in `load_config`, so `Config(rules={...})` bypassed
       it entirely. It is now called from `Config.__post_init__`.
    3. The waiver was matched on rule id alone, so a waiver scoped to a single
       cell authorised a rule-wide silence. A `[rules]` entry applies to every
       finding of that rule, so only a `scope = "*"` waiver authorises one.
    """
    if not rules:
        return
    waived = {waiver.rule for waiver in waivers if waiver.scope == "*"}
    defaults = {rule.id: rule.default_severity for rule in registered_rules()}
    for rule_id, options in rules.items():
        requested = str(options.get("severity", "")).lower()
        lowering_error = requested == "warn" and defaults.get(rule_id) == Severity.ERROR
        if not (lowering_error or requested == "off"):
            continue
        if rule_id not in waived:
            raise ValueError(
                f'silencing {rule_id} requires a waiver with a named approver and scope = "*"'
            )
