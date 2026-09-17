"""Stable rule and finding contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from xllib.inspect import Capability


class Severity(StrEnum):
    ERROR = "ERROR"
    WARN = "WARN"


class Status(StrEnum):
    VIOLATION = "VIOLATION"
    SKIPPED = "SKIPPED"
    INFO = "INFO"


class Confidence(StrEnum):
    CERTAIN = "CERTAIN"
    HEURISTIC = "HEURISTIC"


@dataclass(frozen=True, slots=True)
class Locus:
    sheet: str | None = None
    ref: str | None = None
    sheet_index: int = -1
    row: int = 0
    column: int = 0
    sheet_state: str | None = None

    @property
    def display(self) -> str:
        if self.sheet is None:
            return "Workbook"
        suffix = f"!{self.ref}" if self.ref else ""
        state = f" [{self.sheet_state}]" if self.sheet_state not in (None, "visible") else ""
        return f"{self.sheet}{suffix}{state}"


@dataclass(frozen=True, slots=True)
class Waiver:
    rule: str
    scope: str
    reason: str
    approver: str
    expires: str


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    status: Status
    severity: Severity
    confidence: Confidence
    message: str
    locus: Locus = field(default_factory=Locus)
    evidence: Mapping[str, str] = field(default_factory=dict)
    remediation: str = ""
    waiver: Waiver | None = None


@dataclass(frozen=True, slots=True)
class RuleContext:
    thresholds: Mapping[str, int]
    options: Mapping[str, Any]


Check = Callable[[Any, RuleContext], Iterable[Finding]]


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    slug: str
    title: str
    default_severity: Severity
    confidence: Confidence
    requires: frozenset[Capability]
    thresholds: Mapping[str, int]
    check: Check
    doc: str
