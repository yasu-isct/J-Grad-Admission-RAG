from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import fitz
import pytest
from pydantic import ValidationError

import jgrad_admission_rag.parsing.legacy_adapter as legacy_adapter
from jgrad_admission_rag.builder.extractor import extract_pdf
from jgrad_admission_rag.parsing.cli import (
    _load_source_lock_entry,
    _publish_new_file,
    main as cli_main,
)
from jgrad_admission_rag.parsing import (
    ExactSource,
    LegacyAdapterError,
    ParseRequest,
    canonical_normalized_document_bytes,
    load_normalized_document_bytes,
    parse_legacy_pdf,
)


def _write_pdf(path: Path, page_texts: list[str]) -> ExactSource:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    document.save(path)
    document.close()
    digest = sha256(path.read_bytes()).hexdigest()
    return ExactSource(
        path=path,
        source_id="synthetic-source",
        expected_sha256=digest,
        expected_physical_page_count=len(page_texts),
    )


def test_adapter_preserves_direct_legacy_payloads_and_physical_pages(tmp_path: Path) -> None:
    source = _write_pdf(
        tmp_path / "source.pdf",
        ["ordinary first page", "## Page 999 misleading marker", "marker-free final page"],
    )

    direct = extract_pdf(source.path)
    wrapped = parse_legacy_pdf(source, ParseRequest(selection="all"))

    assert tuple(page.physical_page for page in wrapped.pages) == (1, 2, 3)
    assert [page.blocks[0].text for page in wrapped.pages] == [page.markdown for page in direct]
    assert [page.blocks[0].diagnostics.legacy_char_count for page in wrapped.pages] == [
        page.char_count for page in direct
    ]
    assert [page.blocks[0].diagnostics.legacy_table_count for page in wrapped.pages] == [
        page.table_count for page in direct
    ]
    assert [page.blocks[0].diagnostics.legacy_scanned for page in wrapped.pages] == [
        page.scanned for page in direct
    ]
    assert wrapped.pages[1].physical_page == 2
    assert wrapped.pages[1].printed_page_label is None
    assert wrapped.capabilities.clause_locator == "unsupported"


def test_same_bytes_and_request_are_path_independent_and_deterministic(tmp_path: Path) -> None:
    original = _write_pdf(tmp_path / "a.pdf", ["alpha", "beta"])
    copied_path = tmp_path / "elsewhere.pdf"
    copied_path.write_bytes(original.path.read_bytes())
    copied = original.model_copy(update={"path": copied_path})

    first = parse_legacy_pdf(original, ParseRequest(selection="all"))
    second = parse_legacy_pdf(copied, ParseRequest(selection="all"))

    assert first.run_id == second.run_id
    assert first.output_digest == second.output_digest
    assert canonical_normalized_document_bytes(first) == canonical_normalized_document_bytes(second)
    assert str(original.path) not in canonical_normalized_document_bytes(first).decode("utf-8")


def test_changed_valid_source_bytes_change_run_identity(tmp_path: Path) -> None:
    first_source = _write_pdf(tmp_path / "first.pdf", ["alpha"])
    second_source = _write_pdf(tmp_path / "second.pdf", ["beta"])

    first = parse_legacy_pdf(first_source, ParseRequest(selection="all"))
    second = parse_legacy_pdf(second_source, ParseRequest(selection="all"))

    assert first.source.source_pdf_sha256 != second.source.source_pdf_sha256
    assert first.run_id != second.run_id
    assert first.output_digest != second.output_digest


def test_full_and_equivalent_subset_have_distinct_context_identity(tmp_path: Path) -> None:
    source = _write_pdf(tmp_path / "source.pdf", ["alpha", "beta"])

    complete = parse_legacy_pdf(source, ParseRequest(selection="all"))
    subset_context = parse_legacy_pdf(source, ParseRequest(selection="pages", pages=(1, 2)))

    assert complete.run_id != subset_context.run_id
    assert complete.output_digest != subset_context.output_digest
    assert complete.selection.context == "all"
    assert subset_context.selection.context == "subset"


def test_relevant_adapter_configuration_changes_run_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write_pdf(tmp_path / "source.pdf", ["content"])
    first = parse_legacy_pdf(source, ParseRequest(selection="all"))

    monkeypatch.setitem(
        legacy_adapter._CONFIGURATION,
        "text_format",
        "markdown-test-revision",
    )
    second = parse_legacy_pdf(source, ParseRequest(selection="all"))

    assert first.provenance.configuration_digest != second.provenance.configuration_digest
    assert first.run_id != second.run_id


def test_blank_page_has_honest_non_success_diagnostics(tmp_path: Path) -> None:
    source = _write_pdf(tmp_path / "blank.pdf", [""])

    document = parse_legacy_pdf(source, ParseRequest(selection="all"))

    assert document.pages[0].extraction_status == "blank_or_unreadable"
    assert document.coverage.successful_text_pages == 0
    assert document.coverage.blank_or_unreadable_pages == (1,)
    assert document.pages[0].blocks[0].text == "## Page 1"


@pytest.mark.parametrize(
    "pages",
    [(), (0,), (-1,), (2, 1), (1, 1)],
)
def test_invalid_page_selections_are_rejected(pages: tuple[int, ...]) -> None:
    with pytest.raises(ValidationError):
        ParseRequest(selection="pages", pages=pages)


def test_out_of_range_page_fails_before_extractor_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write_pdf(tmp_path / "source.pdf", ["one page"])

    def unexpected_extraction(*args: object, **kwargs: object) -> None:
        pytest.fail("extractor must not run for an invalid selection")

    monkeypatch.setattr(
        "jgrad_admission_rag.parsing.legacy_adapter.extract_pdf", unexpected_extraction
    )
    with pytest.raises(LegacyAdapterError, match="outside") as raised:
        parse_legacy_pdf(source, ParseRequest(selection="pages", pages=(2,)))
    assert raised.value.code == "page_out_of_range"


@pytest.mark.parametrize(
    ("source_update", "code"),
    [
        ({"expected_sha256": "0" * 64}, "source_hash_mismatch"),
        ({"expected_physical_page_count": 2}, "source_page_count_mismatch"),
    ],
)
def test_source_identity_mismatch_fails_before_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_update: dict[str, object],
    code: str,
) -> None:
    source = _write_pdf(tmp_path / "source.pdf", ["one page"]).model_copy(update=source_update)

    monkeypatch.setattr(
        "jgrad_admission_rag.parsing.legacy_adapter.extract_pdf",
        lambda *args, **kwargs: pytest.fail(
            "extractor must not run for mismatched source identity"
        ),
    )
    with pytest.raises(LegacyAdapterError) as raised:
        parse_legacy_pdf(source, ParseRequest(selection="all"))
    assert raised.value.code == code


def test_missing_source_is_a_bounded_error(tmp_path: Path) -> None:
    source = ExactSource(
        path=tmp_path / "missing.pdf",
        source_id="missing",
        expected_sha256="0" * 64,
        expected_physical_page_count=1,
    )

    with pytest.raises(LegacyAdapterError) as raised:
        parse_legacy_pdf(source, ParseRequest(selection="all"))
    assert raised.value.code == "source_unavailable"


def test_output_digest_detects_content_tampering(tmp_path: Path) -> None:
    source = _write_pdf(tmp_path / "source.pdf", ["original"])
    document = parse_legacy_pdf(source, ParseRequest(selection="all"))
    changed_block = document.pages[0].blocks[0].model_copy(update={"text": "changed"})
    changed_page = document.pages[0].model_copy(update={"blocks": (changed_block,)})
    tampered = document.model_copy(update={"pages": (changed_page,)})

    with pytest.raises(ValueError, match="digest"):
        canonical_normalized_document_bytes(tampered)


def test_canonical_output_round_trips_and_rejects_noncanonical_bytes(tmp_path: Path) -> None:
    source = _write_pdf(tmp_path / "source.pdf", ["content"])
    document = parse_legacy_pdf(source, ParseRequest(selection="all"))
    canonical = canonical_normalized_document_bytes(document)

    assert load_normalized_document_bytes(canonical) == document
    with pytest.raises(ValueError, match="non-canonical"):
        load_normalized_document_bytes(b" " + canonical)


def test_publish_is_complete_and_never_overwrites(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    _publish_new_file(output, b"complete\n")
    assert output.read_bytes() == b"complete\n"

    with pytest.raises(FileExistsError, match="refusing"):
        _publish_new_file(output, b"replacement\n")
    assert output.read_bytes() == b"complete\n"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_publish_rejects_missing_parent_without_partial_output(tmp_path: Path) -> None:
    output = tmp_path / "not-created" / "result.json"
    with pytest.raises(FileNotFoundError, match="parent"):
        _publish_new_file(output, b"payload")
    assert not output.exists()


@pytest.mark.parametrize("conflict", [True, False])
def test_cli_rejects_unpublishable_output_before_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conflict: bool,
) -> None:
    source = _write_pdf(tmp_path / "source.pdf", ["content"])
    lock = tmp_path / "sources.json"
    lock.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": source.source_id,
                        "sha256": source.expected_sha256,
                        "physical_page_count": source.expected_physical_page_count,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "result.json" if conflict else tmp_path / "missing" / "result.json"
    if conflict:
        output.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(
        "jgrad_admission_rag.parsing.cli.parse_legacy_pdf",
        lambda *args, **kwargs: pytest.fail("extractor must not run for an unpublishable output"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parse-legacy-pilot",
            "--source-lock",
            str(lock),
            "--source-id",
            source.source_id,
            "--pdf",
            str(source.path),
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit) as raised:
        cli_main()
    assert raised.value.code == 2


def test_source_lock_requires_one_well_formed_matching_entry(tmp_path: Path) -> None:
    lock = tmp_path / "sources.json"
    lock.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "source-a",
                        "sha256": "a" * 64,
                        "physical_page_count": 3,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert _load_source_lock_entry(lock, "source-a")["physical_page_count"] == 3
    with pytest.raises(ValueError, match="exactly one"):
        _load_source_lock_entry(lock, "unknown")
