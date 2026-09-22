"""The silencing gate's in-memory contract.

Separate from `test_lint_framework.py` because these are adversarial rather
than functional: each one is a route around the gate that an independent
review found open on `d004b10`, recorded in `BACKLOG.md` under
"Silencing-gate review (2026-09-22)".

Every refusal here is paired with a control that must still succeed. Without
them a gate that refused everything would pass the whole file.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from xllib.lint.config import DEFAULT_THRESHOLDS, Config
from xllib.lint.rule import Waiver

_TOMORROW = (date.today() + timedelta(days=1)).isoformat()
_YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
_READ_ONLY = "does not support item assignment"


def _waiver(
    *,
    rule: str = "XL999",
    scope: str = "*",
    reason: str = "test",
    approver: str = "owner",
    expires: str = _TOMORROW,
) -> Waiver:
    return Waiver(rule=rule, scope=scope, reason=reason, approver=approver, expires=expires)


def _silenced(**fields: str) -> Config:
    """A rule switched off, authorised by one rule-wide waiver."""
    return Config(rules={"XL999": {"severity": "off"}}, waivers=(_waiver(**fields),))


# --- the mappings are read-only ------------------------------------------


def test_a_rule_cannot_be_silenced_by_mutating_rules_after_construction() -> None:
    config = Config()
    with pytest.raises(TypeError, match=_READ_ONLY):
        config.rules["XL002"] = {"severity": "off"}
    assert not config.is_off("XL002")


def test_a_rule_cannot_be_silenced_by_mutating_its_own_options() -> None:
    """Freezing only the outer mapping would leave every inner dict writable."""
    config = Config(rules={"XL999": {"severity": "warn"}})
    with pytest.raises(TypeError, match=_READ_ONLY):
        config.rules["XL999"]["severity"] = "off"
    assert not config.is_off("XL999")


def test_a_budget_cannot_be_raised_by_mutating_thresholds() -> None:
    """GOAL puts budgets under the same prohibition as waivers: not agent-raisable."""
    config = Config()
    with pytest.raises(TypeError, match=_READ_ONLY):
        config.thresholds["sheets_per_workbook"] = 999
    assert config.thresholds["sheets_per_workbook"] == DEFAULT_THRESHOLDS["sheets_per_workbook"]


def test_mutating_the_caller_dict_afterwards_does_not_reach_the_config() -> None:
    """A read-only view over the caller's own dict is still writable through it."""
    rules = {"XL999": {"severity": "warn"}}
    config = Config(rules=rules)
    rules["XL999"]["severity"] = "off"
    assert not config.is_off("XL999")


def test_a_copy_inherits_the_frozen_mapping() -> None:
    """`copy.copy` on a slots dataclass skips `__init__`, and so skips the gate."""
    config = copy.copy(Config())
    with pytest.raises(TypeError, match=_READ_ONLY):
        config.rules["XL002"] = {"severity": "off"}


# --- a waiver has to be real before it authorises anything ----------------


def test_an_expired_waiver_does_not_authorise_a_rule_wide_silence() -> None:
    with pytest.raises(ValueError, match="it expired on"):
        _silenced(expires=_YESTERDAY)


def test_a_waiver_naming_no_approver_does_not_authorise_a_rule_wide_silence() -> None:
    with pytest.raises(ValueError, match="names no approver"):
        _silenced(approver="   ")


def test_a_waiver_giving_no_reason_does_not_authorise_a_rule_wide_silence() -> None:
    with pytest.raises(ValueError, match="gives no reason"):
        _silenced(reason="")


def test_a_waiver_with_a_malformed_expiry_does_not_authorise_a_rule_wide_silence() -> None:
    with pytest.raises(ValueError, match="is not a date"):
        _silenced(expires="soon")


def test_a_valid_waiver_still_authorises_a_rule_wide_silence() -> None:
    """The control. Without it the four refusals above pass on an always-refusing gate."""
    assert _silenced().is_off("XL999")


def test_a_waiver_expiring_today_still_authorises() -> None:
    """The boundary: the last day is inclusive, as the file loader also treats it."""
    assert _silenced(expires=date.today().isoformat()).is_off("XL999")


def test_the_error_distinguishes_an_absent_waiver_from_a_disqualified_one() -> None:
    """"You wrote none" and "yours lapsed" used to produce the same sentence."""
    with pytest.raises(ValueError, match="requires a waiver") as absent:
        Config(rules={"XL999": {"severity": "off"}})
    assert "does not qualify" not in str(absent.value)

    with pytest.raises(ValueError, match="does not qualify") as lapsed:
        _silenced(expires=_YESTERDAY)
    assert _YESTERDAY in str(lapsed.value)


# --- per-finding waivers are judged by the same predicate -----------------


def test_an_expired_waiver_does_not_excuse_its_own_cell() -> None:
    config = Config(waivers=(_waiver(scope="Calc!D7", expires=_YESTERDAY),))
    assert config.waiver_for("XL999", "Calc!D7") is None


def test_an_unattributed_waiver_does_not_excuse_its_own_cell() -> None:
    config = Config(waivers=(_waiver(scope="Calc!D7", approver=""),))
    assert config.waiver_for("XL999", "Calc!D7") is None


def test_a_malformed_expiry_does_not_crash_waiver_for() -> None:
    """It used to call `date.fromisoformat` unguarded, so this raised instead of declining."""
    config = Config(waivers=(_waiver(scope="Calc!D7", expires="soon"),))
    assert config.waiver_for("XL999", "Calc!D7") is None


def test_a_valid_waiver_still_excuses_its_own_cell() -> None:
    """The control for the three above, and the scope narrowing still holds."""
    config = Config(waivers=(_waiver(scope="Calc!D7"),))
    assert config.waiver_for("XL999", "Calc!D7") is not None
    assert config.waiver_for("XL999", "Calc!D8") is None
