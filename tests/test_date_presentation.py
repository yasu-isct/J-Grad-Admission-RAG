from __future__ import annotations

import json
from pathlib import Path

import pytest

from jgrad_admission_rag.demo import load_demo_config
from jgrad_admission_rag.service.date_presentation import (
    ReviewedDatePresentationError,
    canonical_reviewed_date_presentation_bytes,
    load_reviewed_date_presentation_bytes,
    validate_highlights_against_official_text,
)


CONFIG_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "jgrad_admission_rag"
    / "demo_config"
    / "reviewed_date_presentation.json"
)


def test_product_key_dates_are_complete_consistent_and_explicit() -> None:
    presentation = load_demo_config().date_presentation

    assert presentation.document_id == "isct_2027_4_2026_9_master"
    assert len(presentation.events) == 8
    assert {event.event_type for event in presentation.events} == {
        "registration_open",
        "application_window",
        "arrival_deadline",
        "recommended_arrival",
    }
    by_intake = {
        (year, month): tuple(
            (
                event.event_type,
                event.start_date,
                event.start_time,
                event.end_date,
                event.end_time,
                event.nature,
                event.unknown_fields,
            )
            for event in presentation.events
            if (event.intake_year, event.intake_month) == (year, month)
        )
        for year, month in ((2026, 9), (2027, 4))
    }
    assert by_intake[(2026, 9)] == by_intake[(2027, 4)]
    assert all(event.timezone == "Asia/Tokyo" for event in presentation.events)
    assert all(event.unknown_fields for event in presentation.events)
    assert canonical_reviewed_date_presentation_bytes(presentation).endswith(b"\n")


def test_every_product_highlight_matches_the_reviewed_fact_character_for_character() -> None:
    presentation = load_demo_config().date_presentation
    buffers: dict[str, list[str]] = {}
    for highlight in presentation.highlights:
        buffer = buffers.setdefault(highlight.fact_id, ["x"] * highlight.end)
        if len(buffer) < highlight.end:
            buffer.extend("x" for _ in range(highlight.end - len(buffer)))
        buffer[highlight.start : highlight.end] = highlight.exact_text
    expected = {fact_id: "".join(characters) for fact_id, characters in buffers.items()}

    assert validate_highlights_against_official_text(presentation, expected) is presentation


@pytest.mark.parametrize("mutation", ["offset", "binding", "unknown_extra"])
def test_reviewed_date_data_fails_closed_when_tampered(mutation: str) -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if mutation == "offset":
        payload["highlights"][0]["start"] += 1
    elif mutation == "binding":
        payload["highlights"][0]["claim_ids"] = ["date:missing"]
    else:
        payload["events"][0]["unexpected"] = True

    with pytest.raises(ReviewedDatePresentationError):
        load_reviewed_date_presentation_bytes(json.dumps(payload).encode())


def test_reviewed_highlight_rejects_stale_official_fact_text() -> None:
    presentation = load_demo_config().date_presentation

    with pytest.raises(ReviewedDatePresentationError, match="do not match official text"):
        validate_highlights_against_official_text(
            presentation,
            {highlight.fact_id: "stale" for highlight in presentation.highlights},
        )


def test_same_length_highlight_text_still_requires_external_fact_validation() -> None:
    original = load_demo_config().date_presentation
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["highlights"][0]["exact_text"] = "X" + payload["highlights"][0]["exact_text"][1:]
    tampered = load_reviewed_date_presentation_bytes(json.dumps(payload).encode())
    official = {
        highlight.fact_id: "x" * highlight.start + highlight.exact_text
        for highlight in original.highlights
    }

    with pytest.raises(ReviewedDatePresentationError):
        validate_highlights_against_official_text(tampered, official)


@pytest.mark.parametrize("mutation", ["overlap", "reverse_order"])
def test_highlight_overlap_and_nondeterministic_order_fail_closed(mutation: str) -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if mutation == "overlap":
        second = payload["highlights"][1]
        second["start"] = payload["highlights"][0]["end"] - 1
        second["end"] = second["start"] + len(second["exact_text"])
    else:
        payload["highlights"][0], payload["highlights"][1] = (
            payload["highlights"][1],
            payload["highlights"][0],
        )

    with pytest.raises(ReviewedDatePresentationError):
        load_reviewed_date_presentation_bytes(json.dumps(payload).encode())
