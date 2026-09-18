from __future__ import annotations

import json
from pathlib import Path

import pytest

from jgrad_admission_rag.schemas.page_scope_manifest import (
    PageScopeCategory,
    PageScopeEntry,
    PageScopeManifest,
    PageScopeManifestError,
    canonical_page_scope_manifest_bytes,
    load_page_scope_manifest,
    load_page_scope_manifest_bytes,
)
from tests.test_corpus_manifest import _identity


FIXTURE = Path(__file__).parent / "fixtures/page_scope_manifest_isct_master_v1.json"


def _manifest() -> PageScopeManifest:
    return PageScopeManifest(
        manifest_id="sample-page-scope-v1",
        document_identity=_identity("sample-2027", family="sample", institution="sample-u"),
        page_count=5,
        entries=(
            PageScopeEntry(
                pages=(1, 2),
                category=PageScopeCategory.CORE_ADMISSION,
                review_note="Ordinary admission rules.",
            ),
            PageScopeEntry(
                pages=(3,),
                category=PageScopeCategory.CONDITIONAL_PROGRAM,
                conditional_routes=("joint_program",),
                review_note="Explicit joint-program route only.",
            ),
            PageScopeEntry(
                pages=(4,),
                category=PageScopeCategory.FACULTY_DIRECTORY,
                review_note="Faculty directory.",
            ),
            PageScopeEntry(
                pages=(5,),
                category=PageScopeCategory.GENERAL_REFERENCE,
                review_note="General reference.",
            ),
        ),
    )


def test_manifest_round_trip_is_canonical_and_exact() -> None:
    manifest = _manifest()
    raw = canonical_page_scope_manifest_bytes(manifest)

    assert load_page_scope_manifest_bytes(raw) == manifest
    assert canonical_page_scope_manifest_bytes(load_page_scope_manifest_bytes(raw)) == raw
    assert manifest.entry_for_pages((1, 2)).category is PageScopeCategory.CORE_ADMISSION
    assert manifest.entry_for_pages((3,)).conditional_routes == ("joint_program",)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload["entries"][0]["pages"].append(3),
        lambda payload: payload["entries"][0]["pages"].remove(2),
        lambda payload: payload["entries"][0].update({"category": "unknown"}),
        lambda payload: payload["entries"][0].update({"conditional_routes": ["wrongly-gated"]}),
        lambda payload: payload["entries"][1].update({"conditional_routes": []}),
    ),
)
def test_manifest_rejects_overlap_missing_invalid_category_and_bad_gates(mutation) -> None:
    payload = _manifest().model_dump(mode="json")
    mutation(payload)

    with pytest.raises(PageScopeManifestError):
        load_page_scope_manifest_bytes(json.dumps(payload).encode())


def test_real_manifest_covers_all_pages_with_reviewed_distribution() -> None:
    manifest = load_page_scope_manifest(FIXTURE)
    counts = {
        category: sum(len(entry.pages) for entry in manifest.entries if entry.category is category)
        for category in PageScopeCategory
    }

    assert manifest.page_count == 85
    assert counts == {
        PageScopeCategory.CORE_ADMISSION: 35,
        PageScopeCategory.CONDITIONAL_PROGRAM: 4,
        PageScopeCategory.FACULTY_DIRECTORY: 34,
        PageScopeCategory.GENERAL_REFERENCE: 9,
        PageScopeCategory.IRRELEVANT_OR_APPENDIX: 3,
    }
    assert manifest.entry_for_pages((76,)).conditional_routes == ("tsinghua_joint_program",)
    assert manifest.entry_for_pages((20,)).category is PageScopeCategory.FACULTY_DIRECTORY
    assert manifest.entry_for_pages((79,)).category is PageScopeCategory.GENERAL_REFERENCE


def test_loader_rejects_missing_or_symlinked_manifest(tmp_path: Path) -> None:
    with pytest.raises(PageScopeManifestError, match="unavailable or unsafe"):
        load_page_scope_manifest(tmp_path / "missing.json")

    target = tmp_path / "manifest.json"
    target.write_bytes(canonical_page_scope_manifest_bytes(_manifest()))
    link = tmp_path / "manifest-link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(PageScopeManifestError, match="unavailable or unsafe"):
        load_page_scope_manifest(link)
