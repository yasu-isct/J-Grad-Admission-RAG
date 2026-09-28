"""Pure value comparison and three-state composition shared by reviewed conditions."""

from __future__ import annotations

from typing import Any, Iterable, Literal

ConditionValue = bool | None


def compare(value: Any, operator: str, expected: Any) -> bool:
    """Compare a previously validated, present value with a reviewed operand."""
    if operator == "equals":
        return value == expected
    if operator == "not_equals":
        return value != expected
    if operator == "contains":
        return expected in value
    if operator == "minimum":
        return value >= expected
    if operator == "maximum":
        return value <= expected
    if operator == "on_or_before":
        return value <= expected
    if operator == "on_or_after":
        return value >= expected
    if operator == "is_empty":
        return len(value) == 0
    if operator == "is_non_empty":
        return len(value) > 0
    raise ValueError("unknown condition operator")


def combine(mode: Literal["all", "any"], outcomes: Iterable[ConditionValue]) -> ConditionValue:
    """Kleene-style ALL/ANY with the legacy empty-set behavior."""
    values = tuple(outcomes)
    if any(value is not None and type(value) is not bool for value in values):
        raise ValueError("condition outcomes must be bool or None")
    if mode == "all":
        if False in values:
            return False
        if all(value is True for value in values):
            return True
        return None
    if mode == "any":
        if True in values:
            return True
        if all(value is False for value in values):
            return False
        return None
    raise ValueError("unknown condition mode")
