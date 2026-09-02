"""Conservative, deterministic parsing of Japanese admission-query intent and scope."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from ..retrieval.metadata_search import MetadataFilter, ScopePreference

QUERY_INTENT_SCHEMA_VERSION = "1.0"
QUERY_INTENT_CATALOG_SCHEMA_VERSION = "1.0"
QUERY_INTENT_PARSER_VERSION = "lexical-ja-v1"
SUPPORTED_QUERY_INTENT_SCHEMA_VERSIONS = frozenset({QUERY_INTENT_SCHEMA_VERSION})
SUPPORTED_QUERY_INTENT_CATALOG_SCHEMA_VERSIONS = frozenset({QUERY_INTENT_CATALOG_SCHEMA_VERSION})


class QueryIntentError(Exception):
    """Raised when a query intent or its catalog cannot be handled safely."""


class QueryIntentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntentCategory(str, Enum):
    ELIGIBILITY = "eligibility"
    DOCUMENTS = "documents"
    APPLICATION_DATES = "application_dates"
    FEES = "fees"
    LANGUAGE_TESTS = "language_tests"
    SELECTION_EXAMS = "selection_exams"
    RESULTS = "results"
    ENROLLMENT = "enrollment"
    CONTACTS_FORMS = "contacts_forms"
    DEPARTMENT_REQUIREMENTS = "department_requirements"


class MentionKind(str, Enum):
    INTENT = "intent"
    SCOPE_TARGET = "scope_target"
    PARENT_COLLEGE = "parent_college"
    DEGREE_LEVEL = "degree_level"
    INTAKE_MONTH = "intake_month"
    INTAKE_YEAR = "intake_year"


class DiagnosticCode(str, Enum):
    NO_RECOGNIZED_INTENT = "no_recognized_intent"
    AMBIGUOUS_ALIAS = "ambiguous_alias"
    OVERLAPPING_MATCH = "overlapping_match"
    UNMAPPED_RETRIEVAL_CONTEXT = "unmapped_retrieval_context"
    UNKNOWN_SCOPE_ENTITY = "unknown_scope_entity"


class IntentMention(QueryIntentModel):
    canonical_value: str
    mention_kind: MentionKind
    start_offset: StrictInt
    end_offset: StrictInt
    surface: str

    @field_validator("canonical_value", "surface")
    @classmethod
    def strings_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value, "mention value")
        return value

    @model_validator(mode="after")
    def offsets_must_be_valid(self) -> IntentMention:
        if self.start_offset < 0 or self.end_offset <= self.start_offset:
            raise ValueError("mention offsets must be a non-empty forward range")
        return self


class RequestedScope(QueryIntentModel):
    department_or_program_targets: tuple[str, ...]
    parent_college_values: tuple[str, ...]
    target_degree_level: str | None
    intake_year: StrictInt | None
    intake_month: StrictInt | None

    @field_validator("department_or_program_targets", "parent_college_values")
    @classmethod
    def values_must_be_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_sorted_strings(values, "requested scope values")
        return values

    @field_validator("target_degree_level")
    @classmethod
    def degree_level_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_trimmed(value, "target degree level")
        return value

    @field_validator("intake_year")
    @classmethod
    def intake_year_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("intake_year must be positive")
        return value

    @field_validator("intake_month")
    @classmethod
    def intake_month_must_be_valid(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 12:
            raise ValueError("intake_month must be between 1 and 12")
        return value


class QueryIntent(QueryIntentModel):
    schema_version: Literal[QUERY_INTENT_SCHEMA_VERSION]
    parser_version: Literal[QUERY_INTENT_PARSER_VERSION]
    catalog_version: str
    query: str
    requested_categories: tuple[IntentCategory, ...]
    requested_scope: RequestedScope
    matched_mentions: tuple[IntentMention, ...]
    diagnostics: tuple[DiagnosticCode, ...]

    @field_validator("catalog_version", "query")
    @classmethod
    def strings_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value, "query intent value")
        return value

    @field_validator("requested_categories", "diagnostics")
    @classmethod
    def enum_values_must_be_sorted_unique(cls, values: tuple[Any, ...]) -> tuple[Any, ...]:
        if values != tuple(sorted(set(values), key=lambda value: value.value)):
            raise ValueError("enum values must be sorted and unique")
        return values

    @model_validator(mode="after")
    def mentions_must_match_original_query(self) -> QueryIntent:
        previous = (-1, -1, "", "")
        for mention in self.matched_mentions:
            if mention.end_offset > len(self.query):
                raise ValueError("mention offsets exceed query length")
            if self.query[mention.start_offset : mention.end_offset] != mention.surface:
                raise ValueError("mention surface does not match query offsets")
            key = (
                mention.start_offset,
                mention.end_offset,
                mention.mention_kind.value,
                mention.canonical_value,
            )
            if key <= previous:
                raise ValueError("mentions must use stable strictly increasing order")
            previous = key
        return self


class CatalogEntity(QueryIntentModel):
    canonical_value: str
    mention_kind: Literal[
        MentionKind.SCOPE_TARGET,
        MentionKind.PARENT_COLLEGE,
        MentionKind.DEGREE_LEVEL,
        MentionKind.INTAKE_MONTH,
    ]
    aliases: tuple[str, ...]

    @field_validator("canonical_value")
    @classmethod
    def canonical_value_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value, "catalog canonical value")
        return value

    @field_validator("aliases")
    @classmethod
    def aliases_must_be_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_sorted_strings(values, "catalog aliases")
        return values


class IntentLexiconEntry(QueryIntentModel):
    category: IntentCategory
    aliases: tuple[str, ...]

    @field_validator("aliases")
    @classmethod
    def aliases_must_be_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_sorted_strings(values, "intent aliases")
        return values


class AmbiguousAlias(QueryIntentModel):
    surface: str
    mention_kind: Literal[MentionKind.SCOPE_TARGET, MentionKind.PARENT_COLLEGE]
    canonical_values: tuple[str, ...]

    @field_validator("surface")
    @classmethod
    def surface_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value, "ambiguous alias")
        return value

    @field_validator("canonical_values")
    @classmethod
    def values_must_be_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_sorted_strings(values, "ambiguous alias values")
        if len(values) < 2:
            raise ValueError("an ambiguous alias needs at least two canonical values")
        return values


class QueryIntentCatalog(QueryIntentModel):
    schema_version: Literal[QUERY_INTENT_CATALOG_SCHEMA_VERSION]
    catalog_version: str
    entities: tuple[CatalogEntity, ...]
    intent_lexicon: tuple[IntentLexiconEntry, ...]
    ambiguous_aliases: tuple[AmbiguousAlias, ...]

    @field_validator("catalog_version")
    @classmethod
    def catalog_version_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value, "catalog version")
        return value

    @model_validator(mode="after")
    def catalog_entries_must_be_consistent(self) -> QueryIntentCatalog:
        entity_keys = [(entry.mention_kind.value, entry.canonical_value) for entry in self.entities]
        if entity_keys != sorted(entity_keys) or len(entity_keys) != len(set(entity_keys)):
            raise ValueError("catalog entities must be sorted and unique")
        categories = tuple(entry.category for entry in self.intent_lexicon)
        if categories != tuple(sorted(set(categories), key=lambda value: value.value)):
            raise ValueError("intent lexicon categories must be sorted and unique")
        ambiguous_keys = [
            (entry.mention_kind.value, entry.surface) for entry in self.ambiguous_aliases
        ]
        if ambiguous_keys != sorted(ambiguous_keys) or len(ambiguous_keys) != len(
            set(ambiguous_keys)
        ):
            raise ValueError("ambiguous aliases must be sorted and unique")

        declared_ambiguous = {
            (entry.mention_kind.value, entry.surface): set(entry.canonical_values)
            for entry in self.ambiguous_aliases
        }
        alias_targets: dict[tuple[str, str], set[str]] = {}
        for entity in self.entities:
            for alias in entity.aliases:
                alias_targets.setdefault((entity.mention_kind.value, alias), set()).add(
                    entity.canonical_value
                )
        for key, values in alias_targets.items():
            if len(values) > 1 and declared_ambiguous.get(key) != values:
                raise ValueError("inconsistent aliases must be declared explicitly ambiguous")
        for key, values in declared_ambiguous.items():
            if alias_targets.get(key) != values:
                raise ValueError("ambiguous aliases must match declared entity aliases")
        return self


@dataclass(frozen=True, slots=True)
class QueryIntentRetrievalRequest:
    """Existing retrieval types derived from a QueryIntent without ranking logic."""

    metadata_filter: MetadataFilter
    scope_preference: ScopePreference


@dataclass(frozen=True, slots=True)
class _Candidate:
    start_offset: int
    end_offset: int
    mention_kind: MentionKind
    canonical_value: str
    surface: str


def parse_query_intent(query: str, catalog: QueryIntentCatalog) -> QueryIntent:
    """Parse only reviewed lexical terms; unsupported wording remains unselected."""

    if not isinstance(catalog, QueryIntentCatalog):
        raise QueryIntentError("query intent catalog is invalid or unsupported")
    try:
        _validate_trimmed(query, "query")
    except (TypeError, ValueError):
        raise QueryIntentError("query intent input is invalid or unsupported") from None

    normalized_query, offsets = _normalize_with_offsets(query)
    candidates: list[_Candidate] = []
    ambiguous_ranges: list[tuple[int, int]] = []
    diagnostics: set[DiagnosticCode] = set()
    for entry in catalog.ambiguous_aliases:
        for start, end in _find_normalized(normalized_query, entry.surface):
            ambiguous_ranges.append(_original_range(offsets, start, end))
            diagnostics.add(DiagnosticCode.AMBIGUOUS_ALIAS)
    for entry in catalog.entities:
        for surface in (entry.canonical_value, *entry.aliases):
            for start, end in _find_normalized(normalized_query, surface):
                original_start, original_end = _original_range(offsets, start, end)
                if (original_start, original_end) not in ambiguous_ranges:
                    candidates.append(
                        _Candidate(
                            original_start,
                            original_end,
                            MentionKind(entry.mention_kind),
                            entry.canonical_value,
                            query[original_start:original_end],
                        )
                    )
    for entry in catalog.intent_lexicon:
        for surface in entry.aliases:
            for start, end in _find_normalized(normalized_query, surface):
                original_start, original_end = _original_range(offsets, start, end)
                candidates.append(
                    _Candidate(
                        original_start,
                        original_end,
                        MentionKind.INTENT,
                        entry.category.value,
                        query[original_start:original_end],
                    )
                )
    for match in re.finditer(r"(?<!\d)(20\d{2})年度", normalized_query):
        original_start, original_end = _original_range(offsets, match.start(1), match.end(1))
        candidates.append(
            _Candidate(
                original_start,
                original_end,
                MentionKind.INTAKE_YEAR,
                query[original_start:original_end],
                query[original_start:original_end],
            )
        )

    selected, overlaps = _select_longest_non_overlapping(candidates)
    if overlaps:
        diagnostics.add(DiagnosticCode.OVERLAPPING_MATCH)
    categories = tuple(
        sorted(
            {
                IntentCategory(candidate.canonical_value)
                for candidate in selected
                if candidate.mention_kind is MentionKind.INTENT
            },
            key=lambda value: value.value,
        )
    )
    if not categories:
        diagnostics.add(DiagnosticCode.NO_RECOGNIZED_INTENT)
    scope_targets = tuple(
        sorted(
            {
                candidate.canonical_value
                for candidate in selected
                if candidate.mention_kind is MentionKind.SCOPE_TARGET
            }
        )
    )
    parent_colleges = tuple(
        sorted(
            {
                candidate.canonical_value
                for candidate in selected
                if candidate.mention_kind is MentionKind.PARENT_COLLEGE
            }
        )
    )
    degree_levels = tuple(
        sorted(
            {
                candidate.canonical_value
                for candidate in selected
                if candidate.mention_kind is MentionKind.DEGREE_LEVEL
            }
        )
    )
    intake_years = tuple(
        sorted(
            {
                candidate.canonical_value
                for candidate in selected
                if candidate.mention_kind is MentionKind.INTAKE_YEAR
            }
        )
    )
    intake_months = tuple(
        sorted(
            {
                candidate.canonical_value
                for candidate in selected
                if candidate.mention_kind is MentionKind.INTAKE_MONTH
            }
        )
    )
    if degree_levels or intake_years or intake_months:
        diagnostics.add(DiagnosticCode.UNMAPPED_RETRIEVAL_CONTEXT)
    if (
        _looks_like_scope_entity(query)
        and not scope_targets
        and not parent_colleges
        and not ambiguous_ranges
    ):
        diagnostics.add(DiagnosticCode.UNKNOWN_SCOPE_ENTITY)
    mentions = tuple(
        IntentMention(
            canonical_value=candidate.canonical_value,
            mention_kind=candidate.mention_kind,
            start_offset=candidate.start_offset,
            end_offset=candidate.end_offset,
            surface=candidate.surface,
        )
        for candidate in selected
    )
    return QueryIntent(
        schema_version=QUERY_INTENT_SCHEMA_VERSION,
        parser_version=QUERY_INTENT_PARSER_VERSION,
        catalog_version=catalog.catalog_version,
        query=query,
        requested_categories=categories,
        requested_scope=RequestedScope(
            department_or_program_targets=scope_targets,
            parent_college_values=parent_colleges,
            target_degree_level=degree_levels[0] if degree_levels else None,
            intake_year=int(intake_years[0]) if intake_years else None,
            intake_month=int(intake_months[0]) if intake_months else None,
        ),
        matched_mentions=mentions,
        diagnostics=tuple(sorted(diagnostics, key=lambda value: value.value)),
    )


def to_metadata_request(intent: QueryIntent) -> QueryIntentRetrievalRequest:
    """Map explicit scope only to existing soft preferences; never create parser hard filters."""

    if not isinstance(intent, QueryIntent):
        raise QueryIntentError("query intent is invalid or unsupported")
    return QueryIntentRetrievalRequest(
        metadata_filter=MetadataFilter(),
        scope_preference=ScopePreference(
            preferred_scope_targets=intent.requested_scope.department_or_program_targets,
            preferred_parent_colleges=intent.requested_scope.parent_college_values,
        ),
    )


def canonical_query_intent_bytes(intent: QueryIntent) -> bytes:
    return _canonical_bytes(intent, QueryIntent, "Query intent")


def canonical_query_intent_catalog_bytes(catalog: QueryIntentCatalog) -> bytes:
    return _canonical_bytes(catalog, QueryIntentCatalog, "Query intent catalog")


def load_query_intent_bytes(raw_bytes: bytes) -> QueryIntent:
    return _load_bytes(raw_bytes, QueryIntent, "Query intent")


def load_query_intent_catalog_bytes(raw_bytes: bytes) -> QueryIntentCatalog:
    return _load_bytes(raw_bytes, QueryIntentCatalog, "Query intent catalog")


def load_query_intent_catalog(path_value: str | Path) -> QueryIntentCatalog:
    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError("unsafe catalog path")
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise QueryIntentError("Query intent catalog file is unavailable or unsafe") from None
    return load_query_intent_catalog_bytes(raw_bytes)


def _canonical_bytes(value: Any, model_type: type[QueryIntentModel], name: str) -> bytes:
    try:
        if not isinstance(value, model_type):
            raise TypeError("wrong durable contract type")
        validated = model_type.model_validate(value.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError):
        raise QueryIntentError(f"{name} is invalid or unsupported") from None
    return f"{serialized}\n".encode("utf-8")


def _load_bytes(raw_bytes: bytes, model_type: type[QueryIntentModel], name: str) -> Any:
    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError("input must be bytes")
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_non_finite_json)
        return model_type.model_validate(payload)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise QueryIntentError(f"{name} bytes are invalid or unsupported") from None


def _normalize_with_offsets(value: str) -> tuple[str, tuple[int, ...]]:
    pieces: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(value):
        normalized = unicodedata.normalize("NFKC", character).casefold()
        pieces.append(normalized)
        offsets.extend([index] * len(normalized))
    return "".join(pieces), tuple(offsets)


def _find_normalized(query: str, surface: str) -> tuple[tuple[int, int], ...]:
    normalized_surface, _ = _normalize_with_offsets(surface)
    found: list[tuple[int, int]] = []
    start = query.find(normalized_surface)
    while start >= 0:
        found.append((start, start + len(normalized_surface)))
        start = query.find(normalized_surface, start + 1)
    return tuple(found)


def _original_range(offsets: tuple[int, ...], start: int, end: int) -> tuple[int, int]:
    return offsets[start], offsets[end - 1] + 1


def _select_longest_non_overlapping(
    candidates: list[_Candidate],
) -> tuple[tuple[_Candidate, ...], bool]:
    ordered = sorted(
        candidates,
        key=lambda value: (
            value.start_offset,
            -(value.end_offset - value.start_offset),
            value.mention_kind.value,
            value.canonical_value,
        ),
    )
    selected: list[_Candidate] = []
    overlaps = any(
        candidate.start_offset < other.end_offset
        and other.start_offset < candidate.end_offset
        and (
            candidate.mention_kind is not other.mention_kind
            or candidate.canonical_value != other.canonical_value
        )
        for position, candidate in enumerate(ordered)
        for other in ordered[position + 1 :]
    )
    for candidate in ordered:
        same_kind_overlap = any(
            candidate.mention_kind is selected_value.mention_kind
            and candidate.start_offset < selected_value.end_offset
            and selected_value.start_offset < candidate.end_offset
            for selected_value in selected
        )
        if same_kind_overlap:
            continue
        if candidate not in selected:
            selected.append(candidate)
    return tuple(
        sorted(
            selected,
            key=lambda value: (
                value.start_offset,
                value.end_offset,
                value.mention_kind.value,
                value.canonical_value,
            ),
        )
    ), overlaps


def _looks_like_scope_entity(query: str) -> bool:
    return "系" in query or "学院" in query


def _reject_non_finite_json(_: str) -> Any:
    raise ValueError("non-finite JSON values are unsupported")


def _validate_trimmed(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")


def _validate_sorted_strings(values: tuple[str, ...], name: str) -> None:
    for value in values:
        _validate_trimmed(value, name)
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} must be sorted and unique")
