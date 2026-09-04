from __future__ import annotations

from copy import deepcopy

from jgrad_admission_rag.builder.document_index import IndexedChunk
from jgrad_admission_rag.builder.kb_builder import fact_to_retrieval_unit, indexed_chunk_to_fact
from jgrad_admission_rag.retrieval.embedding_text import (
    EMBEDDING_TEXT_VERSION,
    build_embedding_text,
)
from jgrad_admission_rag.schemas.document_kb import (
    DocumentKnowledgeBase,
    KnowledgeManifest,
    ScopedFact,
)
from tests.identity_helpers import make_document_identity
from jgrad_admission_rag.schemas.index import derive_index_payloads


def _fact(**changes) -> ScopedFact:
    values = {
        "fact_id": "fact:00001",
        "fact_type": "eligibility",
        "scope_type": "global",
        "scope_targets": [],
        "parent_college": None,
        "title": "出願資格",
        "text": "日本語の規則。",
        "source_pages": [3],
        "section_path": ["3. 出願資格"],
        "evidence": ["source evidence"],
        "confidence": 0.9,
        "embedding_text": "stale projection",
        "metadata": {"private": "not projected"},
    }
    values.update(changes)
    return ScopedFact(**values)


def test_global_projection_has_exact_golden_output() -> None:
    fact = _fact()

    assert build_embedding_text(fact) == (
        "fact_type: eligibility\n"
        "scope: global\n"
        "section_path: 3. 出願資格\n"
        "title: 出願資格\n"
        "text:\n"
        "日本語の規則。"
    )


def test_department_projection_preserves_target_order_and_parent() -> None:
    fact = _fact(
        scope_type="department",
        scope_targets=[" 情報工学系 ", " 数理・計算科学系 "],
        parent_college=" 情報理工学院 ",
        section_path=[" 2. 学院別 ", " 情報理工学院 "],
        title=" 試験科目 ",
    )

    assert build_embedding_text(fact) == (
        "fact_type: eligibility\n"
        "scope: department | targets: 情報工学系 / 数理・計算科学系 | "
        "parent_college: 情報理工学院\n"
        "section_path: 2. 学院別 > 情報理工学院\n"
        "title: 試験科目\n"
        "text:\n"
        "日本語の規則。"
    )


def test_unknown_scope_and_absent_path_and_title_have_explicit_placeholders() -> None:
    fact = _fact(scope_type="unknown", section_path=[], title="   ")

    assert build_embedding_text(fact) == (
        "fact_type: eligibility\n"
        "scope: unknown\n"
        "section_path: (none)\n"
        "title: (none)\n"
        "text:\n"
        "日本語の規則。"
    )


def test_multiline_unicode_and_markdown_table_are_exact_suffix() -> None:
    text = "句読点「、。」と全角記号（１）\n\n| 項目 | 条件 |\n| --- | --- |\n| 英語 | 必須 |\n"
    projection = build_embedding_text(_fact(text=text))

    assert projection.endswith(f"text:\n{text}")
    assert projection.encode("utf-8").endswith(("text:\n" + text).encode("utf-8"))


def test_long_text_is_complete_and_not_previewed() -> None:
    text = "前" + ("あ" * 600) + "後"
    projection = build_embedding_text(_fact(text=text))

    assert projection.endswith(f"text:\n{text}")
    assert projection[-1] == "後"
    assert len(text) == 602


def test_projection_has_one_header_and_excludes_non_contract_fields() -> None:
    projection = build_embedding_text(_fact())

    for label in ("fact_type:", "scope:", "section_path:", "title:", "text:"):
        assert projection.count(label) == 1
    for excluded in (
        "fact:00001",
        "unit:",
        "page",
        "0.9",
        "source evidence",
        "private",
        "stale projection",
    ):
        assert excluded not in projection
    assert not projection.startswith("[")


def test_projection_is_pure_and_does_not_mutate_fact() -> None:
    fact = _fact(
        scope_targets=["情報工学系"],
        section_path=[" 学院別 ", " 情報理工学院 "],
    )
    before = deepcopy(fact.model_dump(mode="json"))

    first = build_embedding_text(fact)
    second = build_embedding_text(fact)

    assert first == second
    assert fact.model_dump(mode="json") == before


def test_new_fact_and_unit_share_canonical_projection_and_independent_metadata() -> None:
    item = IndexedChunk(
        chunk_id=2,
        pdf_name="sample.pdf",
        pages=[15],
        title="英語外部試験",
        category="english_requirements",
        text="全系 TOEIC L&R のスコアを提出する。",
        text_preview="全系 TOEIC L&R のスコアを提出する。",
        anchors=[],
        references=[],
    )

    fact = indexed_chunk_to_fact(item)
    unit = fact_to_retrieval_unit(fact)

    assert EMBEDDING_TEXT_VERSION == "1"
    assert fact.embedding_text == unit.text == build_embedding_text(fact)
    assert fact.metadata["embedding_text_version"] == "1"
    assert unit.metadata["embedding_text_version"] == "1"
    assert unit.metadata is not fact.metadata
    assert unit.metadata["scope_targets"] is not fact.scope_targets
    unit.metadata["scope_targets"].append("変更")
    assert fact.scope_targets == []


def test_unit_reconstruction_repairs_stale_fact_projection() -> None:
    fact = _fact(embedding_text="STALE VALUE THAT MUST NOT PROPAGATE")

    unit = fact_to_retrieval_unit(fact)

    assert unit.text == build_embedding_text(fact)
    assert "STALE VALUE" not in unit.text
    assert fact.embedding_text == "STALE VALUE THAT MUST NOT PROPAGATE"


def test_index_payload_copies_rebuilt_unit_text_and_metadata_exactly() -> None:
    fact = _fact(embedding_text="ignored")
    unit = fact_to_retrieval_unit(fact)
    kb = DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            identity=make_document_identity(document_id="sample"),
            source_pdf="sample.pdf",
            chunk_count=1,
        ),
        facts=[fact],
        retrieval_units=[unit],
    )

    payload = derive_index_payloads(kb)[0]

    assert payload.text == unit.text
    assert payload.metadata == unit.metadata
    assert payload.metadata["embedding_text_version"] == "1"
