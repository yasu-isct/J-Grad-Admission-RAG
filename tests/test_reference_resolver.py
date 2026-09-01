from jgrad_admission_rag.builder import reference_resolver
from jgrad_admission_rag.builder.document_index import Anchor, IndexedChunk, Reference


def _indexed_chunk(
    chunk_id: int,
    *,
    anchors: list[Anchor] | None = None,
    references: list[Reference] | None = None,
) -> IndexedChunk:
    return IndexedChunk(
        chunk_id=chunk_id,
        pdf_name="sample.pdf",
        pages=[1],
        title="",
        category="general",
        text="text",
        text_preview="text",
        anchors=anchors or [],
        references=references or [],
    )


def test_reference_claims_deduplicate_occurrences_candidates_and_ids(monkeypatch) -> None:
    reference = Reference(
        label="下記（1）", kind="item", key="item:1", direction="forward", position=0
    )
    anchor = Anchor(label="(1)", kind="item", key="item:1", position=0)
    index = [
        _indexed_chunk(0, references=[reference, reference]),
        _indexed_chunk(1, anchors=[anchor, anchor]),
        _indexed_chunk(2, anchors=[anchor]),
    ]

    monkeypatch.setattr(
        reference_resolver,
        "_candidate_score",
        lambda _source, target, _reference, _label: (
            (0.9, "first") if target.chunk_id == 1 else (0.7, "second")
        ),
    )
    result = reference_resolver.classify_reference_claims(index)

    assert result.raw_occurrence_count == 2
    assert len(result.claims) == 1
    assert result.claims[0].candidate_target_fact_ids == ["fact:00001", "fact:00002"]
    assert result.claims[0].status == "resolved"
    assert result.claims[0].selected_target_fact_id == "fact:00001"
    assert len(result.links) == 1


def test_reference_ambiguity_margin_includes_exact_boundary(monkeypatch) -> None:
    reference = Reference(
        label="下記（1）", kind="item", key="item:1", direction="forward", position=0
    )
    anchor = Anchor(label="(1)", kind="item", key="item:1", position=0)
    index = [
        _indexed_chunk(0, references=[reference]),
        _indexed_chunk(1, anchors=[anchor]),
        _indexed_chunk(2, anchors=[anchor]),
    ]
    scores = {1: 0.9, 2: 0.8}
    monkeypatch.setattr(
        reference_resolver,
        "_candidate_score",
        lambda _source, target, _reference, _label: (scores[target.chunk_id], "score"),
    )

    boundary = reference_resolver.classify_reference_claims(index, ambiguity_margin=0.1)
    above_boundary = reference_resolver.classify_reference_claims(index, ambiguity_margin=0.099)

    assert boundary.claims[0].score_margin == 0.1
    assert boundary.claims[0].status == "ambiguous"
    assert boundary.links == []
    assert above_boundary.claims[0].status == "resolved"
    assert len(above_boundary.links) == 1


def test_reference_without_positive_candidate_is_unresolved(monkeypatch) -> None:
    reference = Reference(
        label="上記（1）", kind="item", key="item:1", direction="backward", position=0
    )
    anchor = Anchor(label="(1)", kind="item", key="item:1", position=0)
    index = [_indexed_chunk(0, anchors=[anchor]), _indexed_chunk(1, references=[reference])]
    monkeypatch.setattr(
        reference_resolver,
        "_candidate_score",
        lambda *_args: (0.0, "not-positive"),
    )

    result = reference_resolver.classify_reference_claims(index)

    assert result.claims[0].status == "unresolved"
    assert result.claims[0].candidate_target_fact_ids == []
    assert result.claims[0].top_score is None
    assert result.links == []
