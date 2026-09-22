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
    Waiver,
)


def _waiver(rule: str = "XL999", scope: str = "*") -> Waiver:
    return Waiver(
        rule=rule,
        scope=scope,
        reason="test",
        approver="owner",
        expires="2099-01-01",
    )


def _disabled_config(rule: str = "XL999") -> Config:
    """A rule switched off the only way the gate permits: with a rule-wide waiver."""
    return Config(rules={rule: {"severity": "off"}}, waivers=(_waiver(rule),))


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
    config = _disabled_config()
    report = lint(StubWorkbook(), config, (_rule(),))
    assert report.rule_ids == ()
    assert report.as_dict()["config"]["disabled_rules"] == ["XL999"]
    assert "disabled by config: XL999" in report.to_text()


def test_a_disabled_rule_still_counts_against_the_total() -> None:
    """Shrinking the denominator turns "nothing was checked" into a clean bill."""
    config = _disabled_config()
    summary = lint(StubWorkbook(), config, (_rule(),)).as_dict()["summary"]
    assert summary["rules_total"] == 1
    assert summary["rules_evaluated"] == 0
    assert summary["rules_disabled"] == 1
    assert "0 of 1 rules evaluated" in lint(StubWorkbook(), config, (_rule(),)).to_text()


def test_a_disabled_rule_is_listed_rather_than_omitted() -> None:
    config = _disabled_config()
    rules = lint(StubWorkbook(), config, (_rule(),)).as_dict()["rules"]
    assert rules == [{"id": "XL999", "status": "DISABLED", "findings": 0}]


def test_constructing_a_config_directly_cannot_bypass_the_gate() -> None:
    """The gate used to live only in `load_config`.

    Every test above that disables a rule went straight past it by building the
    object, which is also all a caller has to do.
    """
    with pytest.raises(ValueError, match="requires a waiver"):
        Config(rules={"XL999": {"severity": "off"}})


def test_a_cell_scoped_waiver_does_not_authorise_a_rule_wide_silence() -> None:
    """`[rules]` is rule-wide, so authorising it needs a rule-wide waiver.

    A waiver reading `scope = "Calc!D7"` says one cell is excused. Accepting it
    as grounds to switch the rule off everywhere grants far more than the
    approver signed for.
    """
    with pytest.raises(ValueError, match='scope = "\\*"'):
        Config(
            rules={"XL999": {"severity": "off"}},
            waivers=(_waiver(scope="Calc!D7"),),
        )


def test_a_cell_scoped_waiver_still_excuses_its_own_cell() -> None:
    """The narrowing must not break what scoped waivers are for."""
    config = Config(waivers=(_waiver(scope="Calc!D7"),))
    assert config.waiver_for("XL999", "Calc!D7") is not None
    assert config.waiver_for("XL999", "Calc!D8") is None


def test_a_misspelled_rule_id_is_rejected(tmp_path: Path) -> None:
    """`XL0O2` is a letter O. It used to be accepted and then do nothing."""
    path = tmp_path / "xllib.toml"
    path.write_text('[rules.XL0O2]\nseverity = "warn"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown rule id"):
        load_config(path)


def test_a_correctly_spelled_rule_id_is_still_accepted(tmp_path: Path) -> None:
    path = tmp_path / "xllib.toml"
    path.write_text('[rules.XL101]\nseverity = "error"\n', encoding="utf-8")
    assert load_config(path).severity_for("XL101", Severity.WARN) == Severity.ERROR


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
    """Bounded deliberately.

    This used to walk all the way to the filesystem root and pass only because
    no `xllib.toml` happened to sit there — a green test that depended on the
    machine it ran on. The `.git` marker makes the stopping point the test's
    own, so it asserts the boundary rather than the absence of a stray file.
    """
    (tmp_path / ".git").mkdir()
    assert discover_config(tmp_path) is None


def test_config_above_the_project_boundary_is_not_adopted(tmp_path: Path) -> None:
    """A stray `xllib.toml` in a home directory must not govern every run.

    Silencing a rule needs a waiver with a named approver. A config file one
    level above the project would reach the same outcome with neither, and
    nothing in the report would look unusual.
    """
    (tmp_path / "xllib.toml").write_text("[budgets]\nsheets_per_workbook = 1\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    assert discover_config(project) is None


def test_config_inside_the_project_is_still_found(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "models" / "fy26").mkdir(parents=True)
    (project / ".git").mkdir()
    (project / "xllib.toml").write_text("[budgets]\nsheets_per_workbook = 3\n", encoding="utf-8")
    found = discover_config(project / "models" / "fy26")
    assert found == (project / "xllib.toml").resolve()


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
