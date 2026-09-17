from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from xllib.inspect import Capability
from xllib.lint.api import lint
from xllib.lint.config import Config, load_config
from xllib.lint.rule import (
    Confidence,
    Finding,
    Locus,
    Rule,
    Severity,
    Status,
)


@dataclass
class StubWorkbook:
    path: str = "book.xlsx"
    sha256: str = "abc"
    capabilities: frozenset[object] = frozenset()


def _finding(*_: object) -> tuple[Finding, ...]:
    return (
        Finding(
            "XL999",
            Status.VIOLATION,
            Severity.ERROR,
            Confidence.CERTAIN,
            "problem",
            Locus("Calc", "D7", 1, 7, 4),
        ),
    )


def _rule(*, requires: frozenset[Capability] = frozenset()) -> Rule:
    return Rule(
        "XL999",
        "test-rule",
        "Test rule",
        Severity.ERROR,
        Confidence.CERTAIN,
        requires,
        {},
        _finding,
        "docs/rules/XL999.md",
    )


def test_error_finding_sets_exit_one() -> None:
    report = lint(StubWorkbook(), Config(), (_rule(),))
    assert report.exit_code == 1
    assert report.errors == 1
    assert report.as_dict()["findings"][0]["locus"]["ref"] == "D7"


def test_missing_capability_sets_exit_two() -> None:
    report = lint(
        StubWorkbook(), Config(), (_rule(requires=frozenset({Capability.CACHED_VALUES})),)
    )
    assert report.exit_code == 2
    assert report.skipped == 1
    assert "missing CACHED_VALUES" in report.findings[0].message


def test_invalid_waiver_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "xllib.toml"
    path.write_text(
        """
[[waivers.entries]]
rule = "XL999"
scope = "*"
reason = "required"
approver = ""
expires = "2099-01-01"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="approver"):
        load_config(path)


def test_json_findings_are_stable() -> None:
    first = lint(StubWorkbook(), Config(), (_rule(),)).as_dict()["findings"]
    second = lint(StubWorkbook(), Config(), (_rule(),)).as_dict()["findings"]
    assert first == second


def test_error_severity_cannot_drop_without_waiver(tmp_path: Path) -> None:
    path = tmp_path / "xllib.toml"
    path.write_text(
        """
[rules.XL002]
severity = "warn"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires a waiver"):
        load_config(path)


def test_waived_error_may_be_turned_off(tmp_path: Path) -> None:
    path = tmp_path / "xllib.toml"
    path.write_text(
        """
[rules.XL002]
severity = "off"

[[waivers.entries]]
rule = "XL002"
scope = "*"
reason = "temporary"
approver = "owner"
expires = "2099-01-01"
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.is_off("XL002")
    report = lint(StubWorkbook(), config, (_rule(),))
    assert report.rule_ids == ("XL999",)

