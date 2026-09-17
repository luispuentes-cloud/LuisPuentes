"""Rule runner."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from xllib.inspect import capabilities as inspect_capabilities

from .config import Config
from .report import Report
from .rule import Finding, Rule, RuleContext, Status


def _sort_key(finding: Finding) -> tuple[str, int, int, int]:
    locus = finding.locus
    return finding.rule_id, locus.sheet_index, locus.row, locus.column


def lint(workbook: Any, config: Config, rules: tuple[Rule, ...]) -> Report:
    capabilities = (
        frozenset(workbook.capabilities)
        if hasattr(workbook, "capabilities")
        else inspect_capabilities(workbook)
    )
    findings: list[Finding] = []
    active = tuple(rule for rule in rules if not config.is_off(rule.id))
    for rule in active:
        missing = sorted(capability.value for capability in rule.requires - capabilities)
        severity = config.severity_for(rule.id, rule.default_severity)
        if missing:
            findings.append(
                Finding(
                    rule_id=rule.id,
                    status=Status.SKIPPED,
                    severity=severity,
                    confidence=rule.confidence,
                    message=f"could not evaluate: missing {', '.join(missing)}",
                    remediation="recalculate the workbook or provide the missing workbook data",
                )
            )
            continue
        context = RuleContext(
            thresholds={**config.thresholds, **rule.thresholds},
            options=config.options_for(rule.id),
        )
        for raw in rule.check(workbook, context):
            finding = replace(raw, severity=severity)
            waiver = config.waiver_for(rule.id, finding.locus.display)
            if waiver is not None:
                finding = replace(finding, status=Status.INFO, waiver=waiver)
            findings.append(finding)
    path = Path(str(getattr(workbook, "path", "")))
    target = {
        "path": str(path),
        "sha256": str(getattr(workbook, "sha256", "")),
        "capabilities": sorted(capability.value for capability in capabilities),
        "missing_capabilities": sorted(
            capability.value
            for rule in active
            for capability in rule.requires
            if capability not in capabilities
        ),
    }
    return Report(
        target=target,
        config={"sources": list(config.sources), "thresholds": config.thresholds},
        rule_ids=tuple(rule.id for rule in active),
        findings=tuple(sorted(findings, key=_sort_key)),
    )
