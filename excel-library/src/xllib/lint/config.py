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
    """Find the nearest `xllib.toml` at or above `start`.

    The CLI used to look only in the process working directory, so the same
    workbook linted from a different folder silently lost the project's
    positional exemptions and reported two findings it does not have.
    """
    directory = (start or Path.cwd()).resolve()
    for candidate in (directory, *directory.parents):
        found = candidate / CONFIG_FILENAME
        if found.is_file():
            return found
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
        _reject_unwaived_silencing(rules, waivers)
        sources.append(str(path))
    return Config(thresholds, rules, waivers, tuple(sources))


def _reject_unwaived_silencing(
    rules: dict[str, dict[str, Any]], waivers: tuple[Waiver, ...]
) -> None:
    """Silencing a rule needs a named approver, whatever its default severity.

    ADR-0002 requires a waiver both to lower an ERROR rule and to switch a rule
    off. Only the first was enforced, which left the four WARN rules — GOAL's
    rules 5, 6 and 7 — removable from the run by one unattributed config line.
    """
    waived = {waiver.rule for waiver in waivers}
    defaults = {rule.id: rule.default_severity for rule in registered_rules()}
    for rule_id, options in rules.items():
        requested = str(options.get("severity", "")).lower()
        lowering_error = requested == "warn" and defaults.get(rule_id) == Severity.ERROR
        if not (lowering_error or requested == "off"):
            continue
        if rule_id not in waived:
            raise ValueError(f"silencing {rule_id} requires a waiver with a named approver")
