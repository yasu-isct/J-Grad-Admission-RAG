from pathlib import Path


STATIC_ROOT = Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"


def test_key_dates_are_server_owned_structured_conclusions() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "event.display_text" in javascript
    assert "event.nature" in javascript
    assert "event.uncertainty_note" in javascript
    assert 'dateList.className = "date-event-list"' in javascript
    assert "new Date(" not in javascript
    assert "Date.parse(" not in javascript
    assert "2026年6月" not in javascript


def test_direct_evidence_is_highlighted_without_html_injection() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "appendHighlightedOfficialText" in javascript
    assert (
        "officialText.slice(highlight.start, highlight.end) === highlight.exact_text" in javascript
    )
    assert 'document.createElement("mark")' in javascript
    assert 'label.textContent = "直接依据"' in javascript
    assert 'requirement.title || requirement.label || "官方依据"' in javascript
    assert "for (const evidence of event.evidence)" in javascript
    assert "for (const highlight of highlights)" in javascript
    assert "innerHTML" not in javascript


def test_pdf_route_is_allowlisted_and_official_web_link_remains() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "verifiedLocalPdfHref" in javascript
    assert "source\\.pdf$" in javascript
    assert "#page=${page}" in javascript
    assert 'source.textContent = "打开官方招生网页"' in javascript
    assert 'pdfLink.rel = "noopener noreferrer"' in javascript
    assert 'source.rel = "noopener noreferrer"' in javascript


def test_date_and_evidence_styles_have_non_color_cues_and_mobile_layout() -> None:
    css = (STATIC_ROOT / "app.css").read_text(encoding="utf-8")

    assert '.date-event[data-event-type="arrival_deadline"]' in css
    assert '.date-nature[data-nature="must_arrive"]' in css
    assert ".direct-evidence mark" in css
    assert "border-left: 4px solid #a34b37" in css
    assert ".date-event-list," in css
    assert ".source-link:focus-visible" in css


def test_api_contract_adds_typed_dates_and_optional_pdf_evidence() -> None:
    from jgrad_admission_rag.service import create_app
    from jgrad_admission_rag.service.demo_requirements import DemoEvidence, DemoRequirement

    schema = create_app().openapi()["components"]["schemas"]
    event = schema["DemoDateEvent"]
    evidence = schema["DemoEvidence"]
    requirement = schema["DemoRequirement"]

    assert event["additionalProperties"] is False
    assert {"event_type", "display_text", "nature", "unknown_fields", "evidence"} <= set(
        event["properties"]
    )
    assert event["properties"]["timezone"]["const"] == "Asia/Tokyo"
    assert "highlights" in evidence["properties"]
    assert "local_pdf_url" in evidence["properties"]
    assert "date_events" in requirement["properties"]
    assert DemoEvidence.model_fields["highlights"].default == ()
    assert DemoEvidence.model_fields["local_pdf_url"].default is None
    assert DemoRequirement.model_fields["date_events"].default == ()
