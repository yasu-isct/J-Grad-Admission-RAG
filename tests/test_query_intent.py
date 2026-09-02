from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.reasoning import (
    DiagnosticCode,
    QueryIntent,
    QueryIntentCatalog,
    QueryIntentError,
    canonical_query_intent_bytes,
    canonical_query_intent_catalog_bytes,
    load_query_intent_bytes,
    load_query_intent_catalog,
    parse_query_intent,
    to_metadata_request,
)
from jgrad_admission_rag.retrieval.metadata_search import derive_eligible_rows
from jgrad_admission_rag.schemas.index import IndexPayload

ROOT = Path(__file__).parents[1]
CATALOG_PATH = ROOT / "config" / "query_intent_catalog_v1.json"
ANNOTATION_PATH = Path(__file__).parent / "fixtures" / "query_intent_annotations_v1.json"


def _catalog() -> QueryIntentCatalog:
    return load_query_intent_catalog(CATALOG_PATH)


def _annotations() -> tuple[dict[str, object], ...]:
    return tuple(json.loads(ANNOTATION_PATH.read_text("utf-8"))["cases"])


def test_reviewed_annotation_fixture_parses_exact_categories_scope_and_diagnostics() -> None:
    catalog = _catalog()
    for annotation in _annotations():
        intent = parse_query_intent(annotation["query"], catalog)

        assert [category.value for category in intent.requested_categories] == annotation[
            "requested_categories"
        ]
        assert (
            list(intent.requested_scope.department_or_program_targets)
            == annotation["scope_targets"]
        )
        assert (
            list(intent.requested_scope.parent_college_values)
            == annotation["parent_college_values"]
        )
        assert intent.requested_scope.target_degree_level == annotation["target_degree_level"]
        assert intent.requested_scope.intake_year == annotation["intake_year"]
        assert intent.requested_scope.intake_month == annotation["intake_month"]
        assert [diagnostic.value for diagnostic in intent.diagnostics] == annotation["diagnostics"]
        assert [
            [
                mention.mention_kind.value,
                mention.canonical_value,
                mention.surface,
                mention.start_offset,
                mention.end_offset,
            ]
            for mention in intent.matched_mentions
        ] == annotation["mentions"]


def test_alias_unicode_longest_match_repeated_mentions_and_stable_canonical_bytes() -> None:
    catalog = _catalog()
    intent = parse_query_intent("情報工学系と情報工学の英語スコア", catalog)

    assert intent.requested_scope.department_or_program_targets == ("情報工学系",)
    assert [mention.surface for mention in intent.matched_mentions] == [
        "情報工学系",
        "情報工学",
        "英語スコア",
    ]
    assert DiagnosticCode.OVERLAPPING_MATCH not in intent.diagnostics
    assert canonical_query_intent_bytes(intent) == canonical_query_intent_bytes(
        parse_query_intent("情報工学系と情報工学の英語スコア", catalog)
    )
    module = importlib.import_module("jgrad_admission_rag.reasoning.query_intent")
    assert module._normalize_with_offsets("ガ") == module._normalize_with_offsets("カ\u3099")
    assert module._normalize_with_offsets("ＴＯＥＦＬ") == module._normalize_with_offsets("toefl")


def test_scope_is_soft_only_and_global_candidates_remain_eligible() -> None:
    intent = parse_query_intent("情報工学系の出願資格", _catalog())

    request = to_metadata_request(intent)
    payloads = (
        IndexPayload(
            row_index=0,
            document_id="doc",
            unit_id="unit:0",
            fact_id="fact:0",
            text="global",
            source_pages=[1],
            section_path=["root"],
            fact_type="eligibility",
            scope_type="global",
        ),
        IndexPayload(
            row_index=1,
            document_id="doc",
            unit_id="unit:1",
            fact_id="fact:1",
            text="department",
            source_pages=[2],
            section_path=["root"],
            fact_type="eligibility",
            scope_type="department",
            scope_targets=["情報工学系"],
        ),
    )

    assert request.metadata_filter.active is False
    assert request.scope_preference.preferred_scope_targets == ("情報工学系",)
    assert derive_eligible_rows(payloads, request.metadata_filter) == (0, 1)


def test_empty_ambiguous_and_context_only_queries_fail_open_to_empty_constraints() -> None:
    catalog = _catalog()
    for query in ("応募について", "情報系について", "修士4月"):
        request = to_metadata_request(parse_query_intent(query, catalog))
        assert request.metadata_filter.active is False
        assert request.scope_preference.active is False

    context = parse_query_intent("2027年度修士4月の出願資格", catalog)
    assert context.requested_scope.target_degree_level == "master"
    assert context.requested_scope.intake_year == 2027
    assert context.requested_scope.intake_month == 4
    assert DiagnosticCode.UNMAPPED_RETRIEVAL_CONTEXT in context.diagnostics


def test_parser_never_constructs_or_mutates_an_applicant_profile() -> None:
    profile_module = importlib.import_module("jgrad_admission_rag.reasoning.applicant_profile")
    before = set(profile_module.__dict__)

    parse_query_intent("私は中国国籍でTOEFL100点です", _catalog())

    assert set(profile_module.__dict__) == before


def test_durable_contracts_fail_closed_and_keep_query_values_private(tmp_path: Path) -> None:
    catalog = _catalog()
    valid = parse_query_intent("出願資格", catalog)
    secret = "private-query@example.test"
    with pytest.raises(QueryIntentError) as error:
        load_query_intent_bytes(secret)
    assert secret not in str(error.value)

    with pytest.raises(QueryIntentError):
        canonical_query_intent_bytes(QueryIntent.model_construct(schema_version="1.0"))
    with pytest.raises(QueryIntentError):
        canonical_query_intent_bytes(valid.model_copy(update={"parser_version": "other"}))
    with pytest.raises(QueryIntentError):
        canonical_query_intent_catalog_bytes(
            catalog.model_copy(update={"catalog_version": " invalid "})
        )
    with pytest.raises(QueryIntentError):
        parse_query_intent("出願資格", QueryIntentCatalog.model_construct())
    with pytest.raises(QueryIntentError):
        to_metadata_request(QueryIntent.model_construct())
    with pytest.raises(QueryIntentError):
        load_query_intent_catalog(tmp_path / "missing.json")

    source = tmp_path / "catalog.json"
    source.write_bytes(canonical_query_intent_catalog_bytes(catalog))
    symlink = tmp_path / "catalog-link.json"
    try:
        symlink.symlink_to(source)
    except OSError:
        pytest.skip("symlink creation is unavailable in this environment")
    with pytest.raises(QueryIntentError):
        load_query_intent_catalog(symlink)


def test_catalog_validation_rejects_extra_wrong_version_duplicates_and_bad_offsets() -> None:
    catalog_payload = json.loads(CATALOG_PATH.read_text("utf-8"))
    catalog_payload["extra"] = True
    with pytest.raises(ValidationError):
        QueryIntentCatalog.model_validate(catalog_payload)

    catalog_payload = json.loads(CATALOG_PATH.read_text("utf-8"))
    catalog_payload["intent_lexicon"][1]["aliases"] = ["出願期間"]
    with pytest.raises(ValidationError):
        QueryIntentCatalog.model_validate(catalog_payload)

    catalog_payload = json.loads(CATALOG_PATH.read_text("utf-8"))
    catalog_payload["schema_version"] = "2.0"
    with pytest.raises(ValidationError):
        QueryIntentCatalog.model_validate(catalog_payload)

    catalog_payload = json.loads(CATALOG_PATH.read_text("utf-8"))
    catalog_payload["entities"][0]["aliases"] = ["修士", "修士"]
    with pytest.raises(ValidationError):
        QueryIntentCatalog.model_validate(catalog_payload)

    payload = parse_query_intent("出願資格", _catalog()).model_dump(mode="json")
    payload["matched_mentions"][0]["end_offset"] = 1
    with pytest.raises(ValidationError):
        QueryIntent.model_validate(payload)

    payload = parse_query_intent("出願資格", _catalog()).model_dump(mode="json")
    payload["requested_categories"] = []
    with pytest.raises(ValidationError):
        QueryIntent.model_validate(payload)


def test_public_parser_source_has_no_model_or_network_import() -> None:
    module = importlib.import_module("jgrad_admission_rag.reasoning.query_intent")
    source = inspect.getsource(module)

    assert "sentence_transformers" not in source
    assert "requests" not in source
    assert "httpx" not in source
