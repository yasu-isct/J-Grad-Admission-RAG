from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.generation import (
    DEEPSEEK_SCHEMA_PROJECTION_VERSION,
    GenerationDraft,
    QuestionAnalysis,
    build_deepseek_schema_projection,
    project_deepseek_strict_schema,
)
from jgrad_admission_rag.generation.deepseek_schema import (
    DeepSeekSchemaProjectionError,
    DeepSeekSchemaProjectionErrorCode,
)
from jgrad_admission_rag.generation.question_analysis import QuestionCorrection


_WIRE_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "anyOf",
    "description",
}
_REMOVED_CONSTRAINTS = {
    "default",
    "const",
    "title",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
    "uniqueItems",
}


def _walk_schema(node: object) -> None:
    assert isinstance(node, dict)
    assert set(node) <= _WIRE_KEYS
    assert not (set(node) & _REMOVED_CONSTRAINTS)
    if "properties" in node:
        properties = node["properties"]
        assert isinstance(properties, dict)
        assert node["required"] == list(properties)
        assert node["additionalProperties"] is False
        for child in properties.values():
            _walk_schema(child)
    if "items" in node:
        _walk_schema(node["items"])
    for child in node.get("anyOf", []):
        _walk_schema(child)


@pytest.mark.parametrize("model", [QuestionAnalysis, GenerationDraft])
def test_production_schemas_project_to_closed_deepseek_subset(model: object) -> None:
    original = model.model_json_schema()  # type: ignore[attr-defined]
    untouched = copy.deepcopy(original)

    first = build_deepseek_schema_projection(original)
    second = build_deepseek_schema_projection(original)

    assert original == untouched
    assert first == second
    assert first.version == DEEPSEEK_SCHEMA_PROJECTION_VERSION
    assert len(first.sha256) == 64
    assert "$defs" not in first.schema
    _walk_schema(first.schema)


def test_optional_properties_become_required_with_original_default_semantics() -> None:
    projected = project_deepseek_strict_schema(
        {
            "type": "object",
            "properties": {
                "required_value": {"type": "string"},
                "defaulted_value": {"type": "array", "items": {"type": "string"}, "default": []},
                "nullable_value": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "default": None,
                },
            },
            "required": ["required_value"],
            "additionalProperties": False,
        }
    )

    assert projected["required"] == ["required_value", "defaulted_value", "nullable_value"]
    assert projected["properties"]["defaulted_value"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert projected["properties"]["nullable_value"] == {
        "anyOf": [{"type": "integer"}, {"type": "null"}]
    }


def test_empty_object_is_closed() -> None:
    assert project_deepseek_strict_schema({"type": "object"}) == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


def test_generation_defaults_are_non_nullable_but_optional_value_remains_nullable() -> None:
    projected = project_deepseek_strict_schema(GenerationDraft.model_json_schema())
    properties = projected["properties"]

    assert properties["claims"]["type"] == "array"
    assert "anyOf" not in properties["claims"]
    assert properties["missing_information"]["type"] == "array"
    assert "anyOf" not in properties["missing_information"]
    claim_properties = properties["claims"]["items"]["properties"]
    assert claim_properties["finding_ids"]["type"] == "array"
    assert "anyOf" not in claim_properties["finding_ids"]
    assert claim_properties["applicant_fact_paths"]["type"] == "array"
    assert "anyOf" not in claim_properties["applicant_fact_paths"]
    assert properties["refusal_reason"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]


def test_projection_strips_wire_constraints_but_preserves_shape() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "minLength": 2,
                "maxLength": 10,
                "pattern": "^[a-z]+$",
                "title": "Name",
            },
            "score": {"type": "integer", "minimum": 0, "maximum": 1000},
            "values": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
            },
            "version": {"type": "string", "const": "1.0", "default": "1.0"},
        },
        "required": ["name", "score", "values"],
        "additionalProperties": False,
    }

    projected = project_deepseek_strict_schema(schema)

    assert projected["properties"]["name"] == {"type": "string"}
    assert projected["properties"]["score"] == {"type": "integer"}
    assert projected["properties"]["values"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert projected["properties"]["version"] == {"type": "string", "enum": ["1.0"]}


def test_local_references_are_inlined() -> None:
    projected = project_deepseek_strict_schema(
        {
            "$defs": {
                "Leaf": {"type": "string", "enum": ["safe"]},
                "Box": {
                    "type": "object",
                    "properties": {"leaf": {"$ref": "#/$defs/Leaf"}},
                    "required": ["leaf"],
                    "additionalProperties": False,
                },
            },
            "$ref": "#/$defs/Box",
        }
    )
    assert projected == {
        "type": "object",
        "properties": {"leaf": {"type": "string", "enum": ["safe"]}},
        "required": ["leaf"],
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    ("schema", "code"),
    [
        (
            {"$ref": "https://attacker.invalid/schema.json"},
            DeepSeekSchemaProjectionErrorCode.INVALID_REFERENCE,
        ),
        (
            {"$ref": "#/$defs/Missing"},
            DeepSeekSchemaProjectionErrorCode.UNRESOLVED_REFERENCE,
        ),
        (
            {"$defs": {"~2bad": {"type": "string"}}, "$ref": "#/$defs/~2bad"},
            DeepSeekSchemaProjectionErrorCode.INVALID_REFERENCE,
        ),
        (
            {"$defs": {"bad~": {"type": "string"}}, "$ref": "#/$defs/bad~"},
            DeepSeekSchemaProjectionErrorCode.INVALID_REFERENCE,
        ),
        (
            {"$defs": {"Loop": {"$ref": "#/$defs/Loop"}}, "$ref": "#/$defs/Loop"},
            DeepSeekSchemaProjectionErrorCode.CYCLIC_REFERENCE,
        ),
        (
            {"type": "string", "oneOf": [{"type": "string"}]},
            DeepSeekSchemaProjectionErrorCode.UNSUPPORTED_KEYWORD,
        ),
        (
            {"type": "string", "const": "a", "enum": ["b"]},
            DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT,
        ),
        (
            {"type": "string", "anyOf": [{"type": "string"}]},
            DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT,
        ),
        (
            {"type": "object", "properties": {}, "additionalProperties": True},
            DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT,
        ),
        (
            {"properties": {"value": {"type": "string"}}},
            DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT,
        ),
        (
            {"items": {"type": "string"}},
            DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT,
        ),
        (
            {"description": "unconstrained"},
            DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA,
        ),
    ],
)
def test_unsafe_or_unsupported_schema_fails_closed(
    schema: dict[str, object], code: DeepSeekSchemaProjectionErrorCode
) -> None:
    with pytest.raises(DeepSeekSchemaProjectionError) as caught:
        project_deepseek_strict_schema(schema)
    assert caught.value.code is code
    assert caught.value.__cause__ is None
    assert "attacker.invalid" not in str(caught.value)


def test_invalid_mapping_exception_context_is_detached() -> None:
    secret = "PRIVATE-SCHEMA-PAYLOAD"

    class SensitiveMapping(Mapping[str, object]):
        def __getitem__(self, key: str) -> object:
            raise KeyError(key)

        def __iter__(self) -> Iterator[str]:
            raise RuntimeError(secret)

        def __len__(self) -> int:
            return 1

    with pytest.raises(DeepSeekSchemaProjectionError) as caught:
        project_deepseek_strict_schema(SensitiveMapping())
    assert caught.value.code is DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA
    assert caught.value.args == ("DeepSeek schema is invalid",)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in str(caught.value)


def test_projection_depth_and_size_are_bounded() -> None:
    nested: dict[str, object] = {"type": "string"}
    for _ in range(40):
        nested = {"anyOf": [nested, {"type": "null"}]}
    with pytest.raises(DeepSeekSchemaProjectionError) as depth_error:
        project_deepseek_strict_schema(nested)
    assert depth_error.value.code is DeepSeekSchemaProjectionErrorCode.DEPTH_EXCEEDED

    with pytest.raises(DeepSeekSchemaProjectionError) as size_error:
        project_deepseek_strict_schema({"type": "string", "description": "x" * 100_001})
    assert size_error.value.code is DeepSeekSchemaProjectionErrorCode.SIZE_EXCEEDED


def test_original_pydantic_constraints_remain_authoritative() -> None:
    with pytest.raises(ValidationError):
        QuestionCorrection(original="", normalized="TOEIC L&R")
    with pytest.raises(ValidationError):
        QuestionCorrection(original="x" * 201, normalized="TOEIC L&R")

    base = {
        "detected_language": "zh",
        "normalized_question": "TOEIC 840",
        "requested_intents": ["score_conversion"],
        "subquestions": [
            {
                "subquestion_id": "subquestion:01",
                "question": "TOEIC 840",
                "retrieval_query": "TOEIC 840",
                "requested_intent": "score_conversion",
                "needs_clarification": False,
            }
        ],
    }
    with pytest.raises(ValidationError):
        QuestionAnalysis.model_validate({**base, "subquestions": []})
    with pytest.raises(ValidationError):
        QuestionAnalysis.model_validate(
            {
                **base,
                "subquestions": [
                    {
                        "subquestion_id": f"subquestion:{index:02d}",
                        "question": "q",
                        "retrieval_query": "q",
                        "requested_intent": "score_conversion",
                        "needs_clarification": False,
                    }
                    for index in range(1, 10)
                ],
            }
        )

    valid_abstention = {
        "answer": "",
        "claims": [],
        "missing_information": ["missing_rule"],
        "limitations": [],
        "needs_review": True,
        "refused": False,
        "refusal_reason": None,
    }
    with pytest.raises(ValidationError):
        GenerationDraft.model_validate({**valid_abstention, "answer": "x" * 200_001})
    with pytest.raises(ValidationError):
        GenerationDraft.model_validate({**valid_abstention, "unexpected": "forbidden"})
