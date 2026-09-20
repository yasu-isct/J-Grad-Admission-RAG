"""Reviewed presentation data for exact application-date claims and highlights."""

from __future__ import annotations

from datetime import date, time
import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator


_SAFE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._:-]*[A-Za-z0-9])?$")
_EVENT_ORDER = {
    "registration_open": 0,
    "application_window": 1,
    "arrival_deadline": 2,
    "recommended_arrival": 3,
}


class ReviewedDatePresentationError(Exception):
    """Raised when reviewed date presentation data cannot be trusted."""


class DatePresentationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewedDateEvent(DatePresentationModel):
    event_id: str = Field(min_length=1, max_length=200)
    intake_year: StrictInt = Field(ge=1)
    intake_month: StrictInt = Field(ge=1, le=12)
    event_type: Literal[
        "registration_open",
        "application_window",
        "arrival_deadline",
        "recommended_arrival",
    ]
    label: str = Field(min_length=1, max_length=100)
    display_text: str = Field(min_length=1, max_length=300)
    start_date: date
    start_time: time | None = None
    end_date: date | None = None
    end_time: time | None = None
    timezone: Literal["Asia/Tokyo"] = "Asia/Tokyo"
    nature: Literal["opens", "period", "must_arrive", "recommended_arrival"]
    precision: Literal["date", "minute"]
    unknown_fields: tuple[Literal["start_time", "end_date", "end_time"], ...] = ()
    uncertainty_note: str | None = Field(default=None, min_length=1, max_length=300)
    highlight_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def event_must_be_coherent(self) -> "ReviewedDateEvent":
        _validate_id(self.event_id, "event ID")
        _validate_text(self.label, "event label")
        _validate_text(self.display_text, "event display text")
        if self.uncertainty_note is not None:
            _validate_text(self.uncertainty_note, "event uncertainty note")
        _validate_sorted_unique(self.unknown_fields, "unknown fields")
        _validate_sorted_unique(self.highlight_ids, "highlight IDs")
        if self.precision == "minute" and self.start_time is None:
            raise ValueError("minute precision requires a start time")
        if self.start_time is None and "start_time" not in self.unknown_fields:
            raise ValueError("missing start time must be explicit")
        if self.end_date is None and "end_date" not in self.unknown_fields:
            raise ValueError("missing end date must be explicit")
        if self.end_time is None and "end_time" not in self.unknown_fields:
            raise ValueError("missing end time must be explicit")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("date event cannot end before it starts")
        if self.event_type == "registration_open" and self.nature != "opens":
            raise ValueError("registration-open event nature is invalid")
        if self.event_type == "application_window" and self.nature != "period":
            raise ValueError("application-window event nature is invalid")
        if self.event_type == "arrival_deadline" and self.nature != "must_arrive":
            raise ValueError("arrival-deadline event nature is invalid")
        if self.event_type == "recommended_arrival" and self.nature != "recommended_arrival":
            raise ValueError("recommended-arrival event nature is invalid")
        return self


class ReviewedEvidenceHighlight(DatePresentationModel):
    highlight_id: str = Field(min_length=1, max_length=200)
    fact_id: str = Field(min_length=1, max_length=200)
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    exact_text: str = Field(min_length=1)
    claim_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def highlight_must_be_coherent(self) -> "ReviewedEvidenceHighlight":
        _validate_id(self.highlight_id, "highlight ID")
        _validate_id(self.fact_id, "fact ID")
        _validate_sorted_unique(self.claim_ids, "highlight claim IDs")
        if self.end <= self.start:
            raise ValueError("highlight offsets must be a non-empty forward range")
        if len(self.exact_text) != self.end - self.start:
            raise ValueError("highlight exact text length must match its offsets")
        return self


class ReviewedDatePresentation(DatePresentationModel):
    schema_version: Literal["1.0"] = "1.0"
    presentation_id: str = Field(min_length=1, max_length=200)
    document_id: str = Field(min_length=1, max_length=200)
    source_pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    events: tuple[ReviewedDateEvent, ...] = Field(min_length=1)
    highlights: tuple[ReviewedEvidenceHighlight, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def claims_and_highlights_must_reconcile(self) -> "ReviewedDatePresentation":
        _validate_id(self.presentation_id, "presentation ID")
        _validate_id(self.document_id, "document ID")
        event_ids = tuple(event.event_id for event in self.events)
        highlight_ids = tuple(highlight.highlight_id for highlight in self.highlights)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("date event IDs must be unique")
        if len(highlight_ids) != len(set(highlight_ids)):
            raise ValueError("highlight IDs must be unique")
        expected_events = tuple(
            sorted(
                self.events,
                key=lambda event: (
                    event.intake_year,
                    event.intake_month,
                    _EVENT_ORDER[event.event_type],
                    event.event_id,
                ),
            )
        )
        if self.events != expected_events:
            raise ValueError("date events must use deterministic intake and type order")
        expected_highlights = tuple(
            sorted(
                self.highlights,
                key=lambda item: (item.fact_id, item.start, item.end, item.highlight_id),
            )
        )
        if self.highlights != expected_highlights:
            raise ValueError("highlights must use deterministic fact and offset order")

        events_by_id = {event.event_id: event for event in self.events}
        highlights_by_id = {item.highlight_id: item for item in self.highlights}
        previous_end_by_fact: dict[str, int] = {}
        for highlight in self.highlights:
            if highlight.start < previous_end_by_fact.get(highlight.fact_id, 0):
                raise ValueError("highlights must not overlap")
            previous_end_by_fact[highlight.fact_id] = highlight.end
            for claim_id in highlight.claim_ids:
                event = events_by_id.get(claim_id)
                if event is None or highlight.highlight_id not in event.highlight_ids:
                    raise ValueError("highlight claim binding is invalid")
        for event in self.events:
            for highlight_id in event.highlight_ids:
                highlight = highlights_by_id.get(highlight_id)
                if highlight is None or event.event_id not in highlight.claim_ids:
                    raise ValueError("date event highlight binding is invalid")
        return self


def validate_highlights_against_official_text(
    presentation: ReviewedDatePresentation,
    fact_text_by_id: dict[str, str],
) -> ReviewedDatePresentation:
    """Fail closed unless every reviewed offset exactly matches the official Fact text."""

    try:
        for highlight in presentation.highlights:
            official_text = fact_text_by_id[highlight.fact_id]
            if not 0 <= highlight.start < highlight.end <= len(official_text):
                raise ValueError("highlight offset is outside official text")
            if official_text[highlight.start : highlight.end] != highlight.exact_text:
                raise ValueError("highlight exact text is stale or misaligned")
        return presentation
    except (KeyError, TypeError, ValueError):
        raise ReviewedDatePresentationError(
            "reviewed date highlights do not match official text"
        ) from None


def load_reviewed_date_presentation(path_value: str | Path) -> ReviewedDatePresentation:
    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError("unsafe reviewed date presentation path")
        return load_reviewed_date_presentation_bytes(path.read_bytes())
    except (OSError, TypeError, ValueError):
        raise ReviewedDatePresentationError(
            "reviewed date presentation file is unavailable or unsafe"
        ) from None


def load_reviewed_date_presentation_bytes(raw_bytes: bytes) -> ReviewedDatePresentation:
    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError("input must be bytes")
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_non_finite_json)
        return ReviewedDatePresentation.model_validate(payload)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise ReviewedDatePresentationError(
            "reviewed date presentation is invalid or unsupported"
        ) from None


def canonical_reviewed_date_presentation_bytes(
    presentation: ReviewedDatePresentation,
) -> bytes:
    try:
        if not isinstance(presentation, ReviewedDatePresentation):
            raise TypeError("wrong durable contract type")
        validated = ReviewedDatePresentation.model_validate(presentation.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return f"{serialized}\n".encode("utf-8")
    except (TypeError, ValidationError, ValueError):
        raise ReviewedDatePresentationError(
            "reviewed date presentation is invalid or unsupported"
        ) from None


def _validate_id(value: str, label: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _validate_text(value: str, label: str) -> None:
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} must be trimmed printable text")


def _validate_sorted_unique(values: tuple[Any, ...], label: str) -> None:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{label} must be sorted and unique")


def _reject_non_finite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


__all__ = [
    "ReviewedDateEvent",
    "ReviewedDatePresentation",
    "ReviewedDatePresentationError",
    "ReviewedEvidenceHighlight",
    "canonical_reviewed_date_presentation_bytes",
    "load_reviewed_date_presentation",
    "load_reviewed_date_presentation_bytes",
    "validate_highlights_against_official_text",
]
