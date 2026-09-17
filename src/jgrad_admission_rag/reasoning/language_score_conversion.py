"""Reviewed exact score conversion for one official appendix policy."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from fractions import Fraction
from math import gcd
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .applicant_profile import ApplicantProfile, LanguageTestKind
from .applicability import OfficialEvidenceBinding, _selected_language_result


class LanguageScoreConversionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClosedIntegerInterval(LanguageScoreConversionModel):
    lower: StrictInt = Field(ge=0)
    upper: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def bounds_must_be_ordered(self) -> ClosedIntegerInterval:
        if self.lower > self.upper:
            raise ValueError("interval bounds must be ordered")
        return self


class ScoreConversionTableRow(LanguageScoreConversionModel):
    row_id: str
    group_index: StrictInt = Field(ge=1)
    row_index: StrictInt = Field(ge=1)
    raw_ibt_cell: str
    raw_pbt_cell: str
    ibt: ClosedIntegerInterval
    pbt: ClosedIntegerInterval
    source_page: StrictInt = Field(ge=1)

    @field_validator("row_id", "raw_ibt_cell", "raw_pbt_cell")
    @classmethod
    def strings_must_be_explicit(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("conversion row strings must be explicit")
        return value

    @model_validator(mode="after")
    def raw_cells_must_match_intervals(self) -> ScoreConversionTableRow:
        if _parse_integer_interval(self.raw_ibt_cell) != self.ibt:
            raise ValueError("raw iBT cell does not match its interval")
        if _parse_integer_interval(self.raw_pbt_cell) != self.pbt:
            raise ValueError("raw PBT cell does not match its interval")
        return self


class LanguageScoreConversionPolicy(LanguageScoreConversionModel):
    policy_id: str
    evidence_binding: OfficialEvidenceBinding
    pbt_offset: Literal["296"] = "296"
    pbt_to_toeic_divisor: Literal["0.348"] = "0.348"
    toeic_inapplicable_at_or_below: Literal["300"] = "300"
    table_rows: tuple[ScoreConversionTableRow, ...] = Field(min_length=1)
    limitation_statement: str

    @field_validator("policy_id", "limitation_statement")
    @classmethod
    def text_must_be_explicit(cls, value: str) -> str:
        if not value or value != value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("conversion policy text must be explicit")
        return value

    @model_validator(mode="after")
    def rows_must_be_canonical(self) -> LanguageScoreConversionPolicy:
        keys = tuple((row.group_index, row.row_index) for row in self.table_rows)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("conversion rows must be ordered and unique")
        row_ids = tuple(row.row_id for row in self.table_rows)
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("conversion row IDs must be unique")
        if any(
            row.source_page not in self.evidence_binding.source_pages for row in self.table_rows
        ):
            raise ValueError("conversion rows must use an evidence-bound source page")
        return self


class ExactScoreValue(LanguageScoreConversionModel):
    numerator: StrictInt
    denominator: StrictInt = Field(gt=0)
    decimal: str | None = None

    @field_validator("decimal")
    @classmethod
    def decimal_must_be_canonical(cls, value: str | None) -> str | None:
        if value is not None and _canonical_decimal(Decimal(value)) != value:
            raise ValueError("decimal display must be canonical")
        return value

    @model_validator(mode="after")
    def value_must_be_reduced_and_exact(self) -> ExactScoreValue:
        if gcd(abs(self.numerator), self.denominator) != 1:
            raise ValueError("exact score value must be reduced")
        if self.decimal is not None:
            decimal_fraction = _fraction_from_decimal(Decimal(self.decimal))
            if decimal_fraction != Fraction(self.numerator, self.denominator):
                raise ValueError("decimal display must equal the exact rational")
        return self


class ScoreConversionCandidate(LanguageScoreConversionModel):
    lower: ExactScoreValue
    upper: ExactScoreValue
    source_row_ids: tuple[str, ...]
    raw_source_cells: tuple[str, ...]

    @model_validator(mode="after")
    def candidate_must_be_canonical(self) -> ScoreConversionCandidate:
        if _as_fraction(self.lower) > _as_fraction(self.upper):
            raise ValueError("candidate bounds must be ordered")
        if self.source_row_ids != tuple(sorted(set(self.source_row_ids))):
            raise ValueError("candidate row IDs must be sorted and unique")
        if self.raw_source_cells != tuple(sorted(set(self.raw_source_cells))):
            raise ValueError("candidate raw cells must be sorted and unique")
        return self


class ConversionStatus(str, Enum):
    CONVERTED = "converted"
    NOT_APPLICABLE = "not_applicable"
    NOT_REQUIRED = "not_required"
    MISSING_SELECTION = "missing_selection"
    MISSING_TEST_KIND = "missing_test_kind"
    MISSING_SCORE = "missing_score"
    UNSUPPORTED_TEST_KIND = "unsupported_test_kind"
    UNSUPPORTED_SCORE = "unsupported_score"
    OUT_OF_TABLE = "out_of_table"


class ConversionResultShape(str, Enum):
    NONE = "none"
    SINGLE = "single"
    INTERVAL = "interval"
    CANDIDATES = "candidates"


class ConversionStep(LanguageScoreConversionModel):
    operation: Literal[
        "selected_input",
        "toeic_to_pbt_formula",
        "ibt_table_lookup",
        "pbt_to_toeic_formula",
    ]
    expression: str

    @field_validator("expression")
    @classmethod
    def expression_must_be_explicit(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("conversion step must be explicit")
        return value


class LanguageScoreConversionResult(LanguageScoreConversionModel):
    policy_id: str
    status: ConversionStatus
    result_shape: ConversionResultShape
    input_test_kind: LanguageTestKind | None
    input_score: str | None
    conversion_chain: tuple[ConversionStep, ...]
    pbt_candidates: tuple[ScoreConversionCandidate, ...]
    toeic_candidates: tuple[ScoreConversionCandidate, ...]
    evidence_binding: OfficialEvidenceBinding
    missing_fields: tuple[str, ...]
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def result_fields_must_reconcile(self) -> LanguageScoreConversionResult:
        has_results = bool(self.pbt_candidates or self.toeic_candidates)
        if (self.status is ConversionStatus.CONVERTED) != has_results:
            raise ValueError("converted status must reconcile with candidates")
        if self.result_shape is ConversionResultShape.NONE and has_results:
            raise ValueError("none shape cannot contain candidates")
        if self.result_shape is not ConversionResultShape.NONE and not has_results:
            raise ValueError("result shape requires candidates")
        if self.missing_fields != tuple(sorted(set(self.missing_fields))):
            raise ValueError("missing fields must be sorted and unique")
        return self


def convert_selected_language_score(
    profile: ApplicantProfile,
    policy: LanguageScoreConversionPolicy,
) -> LanguageScoreConversionResult:
    """Convert only the applicant's unambiguous selected score under one reviewed policy."""

    if profile.target_application.department_or_program == "数学系":
        return _empty_result(policy, ConversionStatus.NOT_REQUIRED)

    results = profile.language_test_results or ()
    selected = _selected_language_result(profile)
    if selected is None:
        field = (
            "language_test_results.selected_for_submission"
            if len(results) > 1
            else "language_test_results"
        )
        return _empty_result(policy, ConversionStatus.MISSING_SELECTION, (field,))
    if selected.test_kind is None:
        return _empty_result(
            policy,
            ConversionStatus.MISSING_TEST_KIND,
            ("language_test_results.selected.test_kind",),
        )
    if selected.score is None:
        return _empty_result(
            policy,
            ConversionStatus.MISSING_SCORE,
            ("language_test_results.selected.score",),
            selected.test_kind,
        )
    score = _parse_score(selected.score)
    if score is None or score < 0:
        return _empty_result(
            policy,
            ConversionStatus.UNSUPPORTED_SCORE,
            test_kind=selected.test_kind,
            input_score=str(selected.score),
        )
    canonical_score = _canonical_decimal(score)
    selected_step = ConversionStep(
        operation="selected_input",
        expression=f"{selected.test_kind.value}={canonical_score}",
    )

    if selected.test_kind is LanguageTestKind.TOEIC_LR:
        threshold = Decimal(policy.toeic_inapplicable_at_or_below)
        if score <= threshold:
            return _empty_result(
                policy,
                ConversionStatus.NOT_APPLICABLE,
                test_kind=selected.test_kind,
                input_score=canonical_score,
                chain=(selected_step,),
            )
        pbt = score * Decimal(policy.pbt_to_toeic_divisor) + Decimal(policy.pbt_offset)
        candidate = _candidate_from_fractions(
            _fraction_from_decimal(pbt),
            _fraction_from_decimal(pbt),
            (),
            (),
        )
        return _converted_result(
            policy,
            selected.test_kind,
            canonical_score,
            (
                selected_step,
                ConversionStep(
                    operation="toeic_to_pbt_formula",
                    expression=(
                        f"PBT={canonical_score}*{policy.pbt_to_toeic_divisor}"
                        f"+{policy.pbt_offset}={_canonical_decimal(pbt)}"
                    ),
                ),
            ),
            (candidate,),
            (),
        )

    if selected.test_kind not in {
        LanguageTestKind.TOEFL_IBT,
        LanguageTestKind.TOEFL_IBT_HOME_EDITION,
    }:
        return _empty_result(
            policy,
            ConversionStatus.UNSUPPORTED_TEST_KIND,
            test_kind=selected.test_kind,
            input_score=canonical_score,
            chain=(selected_step,),
        )
    if score != score.to_integral_value():
        return _empty_result(
            policy,
            ConversionStatus.UNSUPPORTED_SCORE,
            test_kind=selected.test_kind,
            input_score=canonical_score,
            chain=(selected_step,),
        )

    ibt = int(score)
    matched = tuple(row for row in policy.table_rows if row.ibt.lower <= ibt <= row.ibt.upper)
    if not matched:
        return _empty_result(
            policy,
            ConversionStatus.OUT_OF_TABLE,
            test_kind=selected.test_kind,
            input_score=canonical_score,
            chain=(selected_step,),
        )
    pbt_candidates = _deduplicate_candidates(
        tuple(
            _candidate_from_fractions(
                Fraction(row.pbt.lower),
                Fraction(row.pbt.upper),
                (row.row_id,),
                (row.raw_pbt_cell,),
            )
            for row in matched
        )
    )
    divisor = _fraction_from_decimal(Decimal(policy.pbt_to_toeic_divisor))
    offset = Fraction(int(policy.pbt_offset))
    toeic_candidates = _deduplicate_candidates(
        tuple(
            _candidate_from_fractions(
                (_as_fraction(candidate.lower) - offset) / divisor,
                (_as_fraction(candidate.upper) - offset) / divisor,
                candidate.source_row_ids,
                candidate.raw_source_cells,
            )
            for candidate in pbt_candidates
        )
    )
    return _converted_result(
        policy,
        selected.test_kind,
        canonical_score,
        (
            selected_step,
            ConversionStep(operation="ibt_table_lookup", expression=f"iBT={ibt}"),
            ConversionStep(
                operation="pbt_to_toeic_formula",
                expression=f"TOEIC=(PBT-{policy.pbt_offset})/{policy.pbt_to_toeic_divisor}",
            ),
        ),
        pbt_candidates,
        toeic_candidates,
    )


def _parse_integer_interval(value: str) -> ClosedIntegerInterval:
    parts = value.split("-")
    if len(parts) == 1:
        lower = upper = int(parts[0])
    elif len(parts) == 2:
        lower, upper = map(int, parts)
    else:
        raise ValueError("unsupported score interval")
    return ClosedIntegerInterval(lower=lower, upper=upper)


def _parse_score(value: Any) -> Decimal | None:
    try:
        if isinstance(value, bool):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _fraction_from_decimal(value: Decimal) -> Fraction:
    return Fraction(value)


def _canonical_decimal(value: Decimal) -> str:
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in {"-0", ""} else normalized


def _finite_decimal(value: Fraction) -> str | None:
    denominator = value.denominator
    while denominator % 2 == 0:
        denominator //= 2
    while denominator % 5 == 0:
        denominator //= 5
    if denominator != 1:
        return None
    return _canonical_decimal(Decimal(value.numerator) / Decimal(value.denominator))


def _exact_value(value: Fraction) -> ExactScoreValue:
    return ExactScoreValue(
        numerator=value.numerator,
        denominator=value.denominator,
        decimal=_finite_decimal(value),
    )


def _as_fraction(value: ExactScoreValue) -> Fraction:
    return Fraction(value.numerator, value.denominator)


def _candidate_from_fractions(
    lower: Fraction,
    upper: Fraction,
    row_ids: tuple[str, ...],
    raw_cells: tuple[str, ...],
) -> ScoreConversionCandidate:
    return ScoreConversionCandidate(
        lower=_exact_value(lower),
        upper=_exact_value(upper),
        source_row_ids=tuple(sorted(set(row_ids))),
        raw_source_cells=tuple(sorted(set(raw_cells))),
    )


def _deduplicate_candidates(
    candidates: tuple[ScoreConversionCandidate, ...],
) -> tuple[ScoreConversionCandidate, ...]:
    grouped: dict[tuple[Fraction, Fraction], tuple[set[str], set[str]]] = {}
    for candidate in candidates:
        key = (_as_fraction(candidate.lower), _as_fraction(candidate.upper))
        rows, cells = grouped.setdefault(key, (set(), set()))
        rows.update(candidate.source_row_ids)
        cells.update(candidate.raw_source_cells)
    return tuple(
        _candidate_from_fractions(lower, upper, tuple(rows), tuple(cells))
        for (lower, upper), (rows, cells) in sorted(grouped.items())
    )


def _result_shape(
    pbt: tuple[ScoreConversionCandidate, ...],
    toeic: tuple[ScoreConversionCandidate, ...],
) -> ConversionResultShape:
    candidates = toeic or pbt
    if not candidates:
        return ConversionResultShape.NONE
    if len(candidates) > 1:
        return ConversionResultShape.CANDIDATES
    if candidates[0].lower != candidates[0].upper:
        return ConversionResultShape.INTERVAL
    return ConversionResultShape.SINGLE


def _converted_result(
    policy: LanguageScoreConversionPolicy,
    test_kind: LanguageTestKind,
    score: str,
    chain: tuple[ConversionStep, ...],
    pbt: tuple[ScoreConversionCandidate, ...],
    toeic: tuple[ScoreConversionCandidate, ...],
) -> LanguageScoreConversionResult:
    return LanguageScoreConversionResult(
        policy_id=policy.policy_id,
        status=ConversionStatus.CONVERTED,
        result_shape=_result_shape(pbt, toeic),
        input_test_kind=test_kind,
        input_score=score,
        conversion_chain=chain,
        pbt_candidates=pbt,
        toeic_candidates=toeic,
        evidence_binding=policy.evidence_binding,
        missing_fields=(),
        limitations=(policy.limitation_statement,),
    )


def _empty_result(
    policy: LanguageScoreConversionPolicy,
    status: ConversionStatus,
    missing: tuple[str, ...] = (),
    test_kind: LanguageTestKind | None = None,
    input_score: str | None = None,
    chain: tuple[ConversionStep, ...] = (),
) -> LanguageScoreConversionResult:
    return LanguageScoreConversionResult(
        policy_id=policy.policy_id,
        status=status,
        result_shape=ConversionResultShape.NONE,
        input_test_kind=test_kind,
        input_score=input_score,
        conversion_chain=chain,
        pbt_candidates=(),
        toeic_candidates=(),
        evidence_binding=policy.evidence_binding,
        missing_fields=tuple(sorted(set(missing))),
        limitations=(policy.limitation_statement,),
    )


__all__ = [
    "ClosedIntegerInterval",
    "ConversionResultShape",
    "ConversionStatus",
    "ConversionStep",
    "ExactScoreValue",
    "LanguageScoreConversionPolicy",
    "LanguageScoreConversionResult",
    "ScoreConversionCandidate",
    "ScoreConversionTableRow",
    "convert_selected_language_score",
]
