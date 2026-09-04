import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.schemas.document_identity import (
    DegreeLevel,
    DocumentIdentity,
    DocumentIdentityError,
    canonical_document_identity_bytes,
    load_document_identity,
    load_document_identity_bytes,
)
from tests.identity_helpers import make_document_identity

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_real_reviewed_identity_fixture_loads_exact_document_binding() -> None:
    identity = load_document_identity(FIXTURE_DIR / "document_identity_isct_master_v1.json")
    assert identity.document_id == "isct_2027_4_2026_9_master"
    assert identity.document_family_id == "isct-master-admission-guidelines"
    assert identity.edition_id == "2027-april-2026-september"
    assert [(term.year, term.month) for term in identity.intake_terms] == [
        (2026, 9),
        (2027, 4),
    ]
    assert identity.source_pdf_sha256 == (
        "57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735"
    )


def test_identity_normalizes_controlled_sets_and_is_immutable() -> None:
    payload = make_document_identity().model_dump(mode="json")
    payload["degree_levels"] = ["professional_degree", "master", "doctoral"]
    payload["intake_terms"] = [{"year": 2027, "month": 4}, {"year": 2026, "month": 9}]
    identity = DocumentIdentity.model_validate(payload)
    assert identity.degree_levels == (
        DegreeLevel.DOCTORAL,
        DegreeLevel.MASTER,
        DegreeLevel.PROFESSIONAL_DEGREE,
    )
    assert [(term.year, term.month) for term in identity.intake_terms] == [
        (2026, 9),
        (2027, 4),
    ]
    with pytest.raises(ValidationError):
        identity.document_id = "changed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_id", "../escape"),
        ("document_id", "folder/name"),
        ("edition_id", "bad id"),
        ("institution_id", "#heading"),
        ("document_family_id", "."),
        ("document_id", "trailing."),
        ("document_id", "CON"),
        ("document_id", "COM1.json"),
        ("institution_id", "大学"),
    ],
)
def test_identity_rejects_unsafe_ids(field: str, value: str) -> None:
    payload = make_document_identity().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        DocumentIdentity.model_validate(payload)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.edu/guidelines.pdf",
        "https://user:secret@example.edu/guidelines.pdf",
        "https://example.edu/guidelines.pdf#page=1",
        "https://localhost/guidelines.pdf",
        "https://service.internal/guidelines.pdf",
        "https://127.0.0.1/guidelines.pdf",
        "https://192.168.1.2/guidelines.pdf",
        "https://[::1]/guidelines.pdf",
        "https://example.edu/a/../guidelines.pdf",
        "https://EXAMPLE.edu/guidelines.pdf",
        "https://example.edu:443/guidelines.pdf",
        "https://example.edu/a/%5Cwindows",
        "file:///tmp/guidelines.pdf",
    ],
)
def test_identity_rejects_non_public_or_unsafe_source_urls(url: str) -> None:
    payload = make_document_identity().model_dump(mode="json")
    payload["official_source_url"] = url
    with pytest.raises(ValidationError):
        DocumentIdentity.model_validate(payload)


def test_identity_rejects_duplicate_coverage_and_invalid_intakes() -> None:
    payload = make_document_identity().model_dump(mode="json")
    payload["degree_levels"] = ["master", "master"]
    with pytest.raises(ValidationError):
        DocumentIdentity.model_validate(payload)

    for intake_terms in (
        [{"year": 2027, "month": 4}, {"year": 2027, "month": 4}],
        [{"year": 0, "month": 4}],
        [{"year": 2027, "month": 13}],
    ):
        payload = make_document_identity().model_dump(mode="json")
        payload["intake_terms"] = intake_terms
        with pytest.raises(ValidationError):
            DocumentIdentity.model_validate(payload)


@pytest.mark.parametrize(
    "intake",
    [
        {"year": "2027", "month": 4},
        {"year": 2027, "month": "4"},
        {"year": True, "month": 4},
        {"year": 2027, "month": False},
        {"year": 2027.0, "month": 4},
        {"year": 2027, "month": 4.0},
    ],
)
def test_intake_terms_reject_implicit_integer_coercion(intake: dict) -> None:
    payload = make_document_identity().model_dump(mode="json")
    payload["intake_terms"] = [intake]
    with pytest.raises(ValidationError):
        DocumentIdentity.model_validate(payload)


def test_identity_serialization_and_loading_are_deterministic_and_fail_closed(
    tmp_path: Path,
) -> None:
    identity = make_document_identity()
    raw = canonical_document_identity_bytes(identity)
    assert raw == canonical_document_identity_bytes(load_document_identity_bytes(raw))
    assert raw.endswith(b"\n")

    bad = json.loads(raw)
    bad["unexpected"] = "do-not-echo-this-secret"
    with pytest.raises(DocumentIdentityError, match="invalid or unsupported") as error:
        load_document_identity_bytes(json.dumps(bad).encode())
    assert "secret" not in str(error.value)

    target = tmp_path / "identity.json"
    target.write_bytes(raw)
    link = tmp_path / "identity-link.json"
    try:
        link.symlink_to(target)
    except OSError:
        return
    with pytest.raises(DocumentIdentityError, match="unavailable or unsafe"):
        load_document_identity(link)


def test_same_filename_and_document_family_do_not_collapse_reviewed_editions() -> None:
    fixture = json.loads(
        (FIXTURE_DIR / "document_identity_scenarios_v1.json").read_text(encoding="utf-8")
    )
    assert {item["filename"] for item in fixture["same_filename"]} == {"guideline.pdf"}
    assert len({item["document_id"] for item in fixture["same_filename"]}) == 2
    assert len({item["document_id"] for item in fixture["two_editions"]}) == 2
    assert len({item["source_pdf_sha256"] for item in fixture["two_editions"]}) == 2
    assert fixture["active_edition_selected"] is False
