from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from xllib.inspect import Capability
from xllib.lint.api import lint
from xllib.lint.config import Config, discover_config, load_config
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


def test_warn_rule_cannot_be_switched_off_without_a_waiver(tmp_path: Path) -> None:
    """GOAL rules 5, 6 and 7 are covered only by WARN rules; silencing them is
    the cheapest route around the linter and needs a named approver too."""
    path = tmp_path / "xllib.toml"
    path.write_text(
        """
[rules.XL101]
severity = "off"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires a waiver"):
        load_config(path)


def test_disabled_rule_is_named_in_the_report() -> None:
    config = Config(rules={"XL999": {"severity": "off"}})
    report = lint(StubWorkbook(), config, (_rule(),))
    assert report.rule_ids == ()
    assert report.as_dict()["config"]["disabled_rules"] == ["XL999"]
    assert "disabled by config: XL999" in report.to_text()


def test_a_disabled_rule_still_counts_against_the_total() -> None:
    """Shrinking the denominator turns "nothing was checked" into a clean bill."""
    config = Config(rules={"XL999": {"severity": "off"}})
    summary = lint(StubWorkbook(), config, (_rule(),)).as_dict()["summary"]
    assert summary["rules_total"] == 1
    assert summary["rules_evaluated"] == 0
    assert summary["rules_disabled"] == 1
    assert "0 of 1 rules evaluated" in lint(StubWorkbook(), config, (_rule(),)).to_text()


def test_a_disabled_rule_is_listed_rather_than_omitted() -> None:
    config = Config(rules={"XL999": {"severity": "off"}})
    rules = lint(StubWorkbook(), config, (_rule(),)).as_dict()["rules"]
    assert rules == [{"id": "XL999", "status": "DISABLED", "findings": 0}]


def test_raising_a_severity_needs_no_waiver(tmp_path: Path) -> None:
    """The gate blocks silencing only; tightening must stay free."""
    path = tmp_path / "xllib.toml"
    path.write_text('[rules.XL101]\nseverity = "error"\n', encoding="utf-8")
    assert load_config(path).severity_for("XL101", Severity.WARN) == Severity.ERROR


def test_restating_a_warn_rule_as_warn_needs_no_waiver(tmp_path: Path) -> None:
    path = tmp_path / "xllib.toml"
    path.write_text('[rules.XL101]\nseverity = "warn"\n', encoding="utf-8")
    assert load_config(path).severity_for("XL101", Severity.WARN) == Severity.WARN


def test_waived_warn_rule_may_be_turned_off(tmp_path: Path) -> None:
    path = tmp_path / "xllib.toml"
    path.write_text(
        """
[rules.XL101]
severity = "off"

[[waivers.entries]]
rule = "XL101"
scope = "*"
reason = "temporary"
approver = "owner"
expires = "2099-01-01"
""",
        encoding="utf-8",
    )
    assert load_config(path).is_off("XL101")


def test_text_report_states_which_config_was_in_force() -> None:
    report = lint(StubWorkbook(), Config(), (_rule(),))
    assert "config: builtin" in report.to_text()


def test_config_discovery_walks_up_from_a_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "xllib.toml").write_text("[budgets]\nsheets_per_workbook = 3\n", encoding="utf-8")
    nested = tmp_path / "models" / "fy26"
    nested.mkdir(parents=True)
    found = discover_config(nested)
    assert found == (tmp_path / "xllib.toml").resolve()
    assert load_config(found).thresholds["sheets_per_workbook"] == 3


def test_config_discovery_returns_none_when_there_is_no_project(tmp_path: Path) -> None:
    assert discover_config(tmp_path) is None


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
