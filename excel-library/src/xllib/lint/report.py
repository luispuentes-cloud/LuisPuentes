"""Stable machine and human lint reports."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from xllib import __version__

from .rule import Finding, Severity, Status


@dataclass(frozen=True, slots=True)
class Report:
    target: dict[str, Any]
    config: dict[str, Any]
    rule_ids: tuple[str, ...]
    findings: tuple[Finding, ...]

    @property
    def errors(self) -> int:
        return sum(
            finding.status == Status.VIOLATION and finding.severity == Severity.ERROR
            for finding in self.findings
        )

    @property
    def warnings(self) -> int:
        return sum(
            finding.status == Status.VIOLATION and finding.severity == Severity.WARN
            for finding in self.findings
        )

    @property
    def skipped(self) -> int:
        return sum(finding.status == Status.SKIPPED for finding in self.findings)

    @property
    def exit_code(self) -> int:
        if self.errors:
            return 1
        if self.skipped:
            return 2
        return 0

    @property
    def disabled(self) -> tuple[str, ...]:
        return tuple(self.config.get("disabled_rules") or ())

    def as_dict(self) -> dict[str, Any]:
        rules = []
        for rule_id in self.rule_ids:
            matches = [item for item in self.findings if item.rule_id == rule_id]
            status = (
                Status.SKIPPED
                if any(item.status == Status.SKIPPED for item in matches)
                else Status.VIOLATION
                if any(item.status == Status.VIOLATION for item in matches)
                else Status.INFO
            )
            rules.append({"id": rule_id, "status": status.value, "findings": len(matches)})
        # A disabled rule stays in the list. Dropping it shrank the denominator,
        # so a config that switched everything off reported "0 of 0 rules
        # evaluated" and exit 0 — absence of evidence rendered as a clean bill.
        rules.extend(
            {"id": rule_id, "status": "DISABLED", "findings": 0} for rule_id in self.disabled
        )
        findings = []
        for finding in self.findings:
            item = asdict(finding)
            item["status"] = finding.status.value
            item["severity"] = finding.severity.value
            item["confidence"] = finding.confidence.value
            findings.append(item)
        return {
            "schema_version": "1.0",
            "tool": {"name": "xllib", "version": __version__},
            "target": self.target,
            "config": self.config,
            "summary": {
                "error": self.errors,
                "warn": self.warnings,
                "skipped": self.skipped,
                "rules_total": len(self.rule_ids) + len(self.disabled),
                "rules_evaluated": len(self.rule_ids) - self.skipped,
                "rules_disabled": len(self.disabled),
                "exit_code": self.exit_code,
            },
            "rules": rules,
            "findings": findings,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=False)

    def to_text(self) -> str:
        lines: list[str] = []
        for finding in self.findings:
            marker = " ~" if finding.confidence.value == "HEURISTIC" else ""
            lines.append(
                f"{finding.locus.display:<24}{marker} {finding.rule_id}  {finding.message}"
            )
        evaluated = len(self.rule_ids) - self.skipped
        total = len(self.rule_ids) + len(self.disabled)
        lines.extend(
            [
                "",
                f"{evaluated} of {total} rules evaluated   "
                f"{self.errors} error   {self.warnings} warn",
            ]
        )
        if self.skipped:
            lines.append(f"{self.skipped} rules skipped")
        # Which config was in force decides which findings appear at all, so a
        # report that does not say is not reproducible from its own output.
        if self.disabled:
            lines.append(f"{len(self.disabled)} disabled by config: {', '.join(self.disabled)}")
        lines.append(f"config: {', '.join(str(item) for item in self.config.get('sources', ()))}")
        lines.append(f"exit {self.exit_code}")
        return "\n".join(lines)
