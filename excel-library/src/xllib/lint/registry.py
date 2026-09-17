"""Stable rule registration."""

from .rule import Rule
from .rules import RULES


def registered_rules() -> tuple[Rule, ...]:
    return RULES


__all__ = ["registered_rules"]
