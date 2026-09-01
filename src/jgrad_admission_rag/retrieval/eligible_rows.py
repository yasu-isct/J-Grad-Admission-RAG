from __future__ import annotations

from collections.abc import Collection


class EligibleRowsError(ValueError):
    """Raised when an eligible-row constraint is malformed."""


def validate_eligible_rows(
    row_count: int,
    eligible_rows: Collection[int] | None,
) -> tuple[int, ...] | None:
    """Return sorted unique row identities, or None for an unrestricted corpus."""

    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        raise EligibleRowsError("row_count must be a non-negative non-bool integer")
    if eligible_rows is None:
        return None
    if not isinstance(eligible_rows, Collection) or isinstance(
        eligible_rows, (str, bytes, bytearray)
    ):
        raise EligibleRowsError("eligible_rows must be a finite collection of row integers")
    values = tuple(eligible_rows)
    if any(isinstance(row, bool) or not isinstance(row, int) for row in values):
        raise EligibleRowsError("eligible_rows must contain only non-bool integers")
    if len(values) != len(set(values)):
        raise EligibleRowsError("eligible_rows must not contain duplicates")
    if any(row < 0 or row >= row_count for row in values):
        raise EligibleRowsError("eligible_rows contains an out-of-range row")
    return tuple(sorted(values))
