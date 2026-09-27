"""BUILD-01 explicit guard and legacy compatibility tests; synthetic PDFs only."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import fitz
import pytest

import jgrad_admission_rag.builder.kb_builder as builder
import jgrad_admission_rag.builder.legacy_isct_v1 as policy
from jgrad_admission_rag.schemas.document_identity import DocumentIdentity
from jgrad_admission_rag.schemas.document_kb import canonical_document_kb_bytes


ROOT = Path(__file__).resolve().parents[1]
REVIEWED_IDENTITY = json.loads(
    (ROOT / "src/jgrad_admission_rag/demo_config/document_identity.json").read_bytes()
)


def identity(**changes):
    return DocumentIdentity.model_validate({**REVIEWED_IDENTITY, **changes})


def forbid_pdf_io(monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append("pdf_io")
        pytest.fail("profile rejection happened after PDF I/O")

    monkeypatch.setattr(builder, "sha256_file", fail)
    monkeypatch.setattr(builder, "extract_pdf", fail)
    monkeypatch.setattr(Path, "open", fail)
    return calls


@pytest.mark.parametrize("profile", ["unknown", "", None, 1, "legacy-isct-v2"])
def test_unknown_profile_refused_before_pdf_io(monkeypatch, profile):
    calls = forbid_pdf_io(monkeypatch)
    with pytest.raises(builder.DocumentBuildProfileError) as error:
        builder.build_document_kb_with_profile("not-found.pdf", identity(), profile_id=profile)
    assert error.value.code == "unknown_profile"
    assert not calls


def test_profile_argument_is_required(monkeypatch):
    calls = forbid_pdf_io(monkeypatch)
    with pytest.raises(TypeError, match="profile_id"):
        builder.build_document_kb_with_profile("not-found.pdf", identity())
    assert not calls


@pytest.mark.parametrize(
    "changes",
    [
        {"institution_id": "utokyo"},
        {"document_family_id": "utokyo-gsfs-master-guidelines"},
        {"edition_id": "2028-april-2027-september"},
        {"document_id": "isct-other-document"},
        {"degree_levels": ["doctoral"]},
        {"intake_terms": [{"year": 2027, "month": 10}]},
    ],
)
def test_every_structured_identity_dimension_guarded_before_io(monkeypatch, changes):
    calls = forbid_pdf_io(monkeypatch)
    with pytest.raises(builder.DocumentBuildProfileError) as error:
        builder.build_document_kb_with_profile(
            "isct_2027_4_2026_9_master.pdf",
            identity(**changes),
            profile_id=builder.LEGACY_ISCT_PROFILE_ID,
        )
    assert error.value.code == "profile_identity_mismatch"
    assert not calls


def test_real_gsfs_source_binding_is_only_a_guard_fixture(monkeypatch):
    """Use #202 fixed source ID/hash/URL; this grants no GSFS document coverage."""
    sources = json.loads(
        (ROOT / "docs/onboarding/utokyo-gsfs-complex-2027.sources.json").read_bytes()
    )["sources"]
    source = next(s for s in sources if s["source_id"] == "gsfs-master-2027")
    calls = forbid_pdf_io(monkeypatch)
    gsfs = identity(
        institution_id="utokyo",
        institution_name="Institute of Science Tokyo",  # display spoof must not authorize
        document_family_id="utokyo-gsfs-master-guidelines",
        edition_id="2027",
        document_id="gsfs-master-2027",
        official_source_url=source["official_url"],
        source_pdf_sha256=source["sha256"],
    )
    with pytest.raises(builder.DocumentBuildProfileError) as error:
        builder.build_document_kb_with_profile(
            "isct_2027_4_2026_9_master.pdf",
            gsfs,
            profile_id=builder.LEGACY_ISCT_PROFILE_ID,
        )
    assert error.value.code == "profile_identity_mismatch"
    assert not calls


def test_second_synthetic_school_and_swapped_labels_are_rejected(monkeypatch):
    calls = forbid_pdf_io(monkeypatch)
    other = identity(institution_id="fictional-grad", institution_name="Institute of Science Tokyo")
    for path, label in (
        ("isct_2027_4_2026_9_master.pdf", "isct_2027_4_2026_9_master.pdf"),
        ("somewhere/renamed.pdf", "isct_2027_4_2026_9_master.pdf"),
    ):
        with pytest.raises(builder.DocumentBuildProfileError) as error:
            builder.build_document_kb_with_profile(
                path, other, profile_id=builder.LEGACY_ISCT_PROFILE_ID, source_pdf_label=label
            )
        assert error.value.code == "profile_identity_mismatch"
    assert not calls


@pytest.mark.parametrize("invalid", [None, {}, "identity"])
def test_invalid_identity_refused_before_io(monkeypatch, invalid):
    calls = forbid_pdf_io(monkeypatch)
    with pytest.raises(builder.DocumentBuildProfileError) as error:
        builder.build_document_kb_with_profile(
            "not-found.pdf", invalid, profile_id=builder.LEGACY_ISCT_PROFILE_ID
        )
    assert error.value.code == "invalid_identity"
    assert not calls


def test_mutated_identity_is_revalidated_before_io(monkeypatch):
    calls = forbid_pdf_io(monkeypatch)
    damaged = identity().model_copy(update={"document_family_id": "../invalid"})
    with pytest.raises(builder.DocumentBuildProfileError) as error:
        builder.build_document_kb_with_profile(
            "not-found.pdf", damaged, profile_id=builder.LEGACY_ISCT_PROFILE_ID
        )
    assert error.value.code == "invalid_identity"
    assert not calls


def test_supported_profile_keeps_hash_validation_before_extraction(tmp_path, monkeypatch):
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"wrong source bytes")

    def fail(*args, **kwargs):
        pytest.fail("extractor called before source hash validation")

    monkeypatch.setattr(builder, "extract_pdf", fail)
    with pytest.raises(
        builder.DocumentBuildError, match="source PDF and reviewed document identity"
    ):
        builder.build_document_kb_with_profile(
            pdf, identity(), profile_id=builder.LEGACY_ISCT_PROFILE_ID
        )


def test_synthetic_isct_old_and_explicit_entries_are_byte_identical(tmp_path):
    pdf = tmp_path / "synthetic.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 72), "Synthetic ordinary admission guideline")
    document.save(pdf)
    document.close()
    synthetic_identity = identity(source_pdf_sha256=sha256(pdf.read_bytes()).hexdigest())
    args = {"source_pdf_label": "stable-synthetic.pdf", "max_chars": 6000}
    old = builder.build_document_kb(pdf, synthetic_identity, **args)
    explicit = builder.build_document_kb_with_profile(
        pdf, synthetic_identity, profile_id=builder.LEGACY_ISCT_PROFILE_ID, **args
    )
    assert canonical_document_kb_bytes(old) == canonical_document_kb_bytes(explicit)


def test_policy_has_one_authoritative_implementation():
    for name in (
        "build_entities",
        "infer_scope",
        "propagate_department_context",
        "_is_tsinghua_program_cover",
    ):
        assert getattr(builder, name) is getattr(policy, name)
    assert builder.COLLEGE_DEPARTMENTS is policy.COLLEGE_DEPARTMENTS
    assert len(builder.build_entities([])) == 25  # historical legacy limitation
