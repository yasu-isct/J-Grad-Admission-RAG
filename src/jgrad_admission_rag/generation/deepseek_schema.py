"""Bounded projection of Pydantic JSON Schema into DeepSeek's strict subset."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

DEEPSEEK_SCHEMA_PROJECTION_VERSION = "1.0"

_MAX_INPUT_BYTES = 100_000
_MAX_OUTPUT_BYTES = 100_000
_MAX_DEPTH = 32
_MAX_NODES = 1_024
_SUPPORTED_TYPES = frozenset({"object", "string", "number", "integer", "boolean", "array", "null"})
_STRIPPED_KEYS = frozenset(
    {
        "title",
        "default",
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
)
_SUPPORTED_KEYS = frozenset(
    {
        "$ref",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "anyOf",
        "const",
        "description",
    }
)


class DeepSeekSchemaProjectionErrorCode(str, Enum):
    """Privacy-safe reasons why a schema cannot be projected."""

    INVALID_SCHEMA = "invalid_schema"
    UNSUPPORTED_KEYWORD = "unsupported_keyword"
    INVALID_REFERENCE = "invalid_reference"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    CYCLIC_REFERENCE = "cyclic_reference"
    CONFLICTING_CONSTRAINT = "conflicting_constraint"
    DEPTH_EXCEEDED = "depth_exceeded"
    SIZE_EXCEEDED = "size_exceeded"


_SAFE_MESSAGES = {
    DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA: "DeepSeek schema is invalid",
    DeepSeekSchemaProjectionErrorCode.UNSUPPORTED_KEYWORD: "DeepSeek schema has an unsupported keyword",
    DeepSeekSchemaProjectionErrorCode.INVALID_REFERENCE: "DeepSeek schema has an invalid reference",
    DeepSeekSchemaProjectionErrorCode.UNRESOLVED_REFERENCE: "DeepSeek schema has an unresolved reference",
    DeepSeekSchemaProjectionErrorCode.CYCLIC_REFERENCE: "DeepSeek schema has a cyclic reference",
    DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT: "DeepSeek schema has conflicting constraints",
    DeepSeekSchemaProjectionErrorCode.DEPTH_EXCEEDED: "DeepSeek schema exceeds the depth limit",
    DeepSeekSchemaProjectionErrorCode.SIZE_EXCEEDED: "DeepSeek schema exceeds the size limit",
}


class DeepSeekSchemaProjectionError(ValueError):
    """Fail-closed error that never includes schema content or a reference path."""

    def __init__(self, code: DeepSeekSchemaProjectionErrorCode) -> None:
        self.code = code
        super().__init__(_SAFE_MESSAGES[code])


@dataclass(frozen=True, slots=True)
class DeepSeekSchemaProjection:
    """A projected wire schema and its stable, non-sensitive identity."""

    schema: dict[str, Any]
    version: str
    sha256: str


@dataclass(slots=True)
class _ProjectionState:
    definitions: Mapping[str, Any]
    nodes: int = 0

    def enter(self, depth: int) -> None:
        if depth > _MAX_DEPTH:
            raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.DEPTH_EXCEEDED)
        self.nodes += 1
        if self.nodes > _MAX_NODES:
            raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.SIZE_EXCEEDED)


def project_deepseek_strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic DeepSeek wire schema without mutating ``schema``."""

    try:
        source = copy.deepcopy(dict(schema))
        encoded = _canonical_json(source)
    except Exception:
        raise DeepSeekSchemaProjectionError(
            DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA
        ) from None
    if len(encoded) > _MAX_INPUT_BYTES:
        raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.SIZE_EXCEEDED)

    definitions = source.pop("$defs", {})
    if not isinstance(definitions, dict) or any(not isinstance(key, str) for key in definitions):
        raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)
    state = _ProjectionState(definitions=definitions)
    projected = _project_node(source, state=state, depth=0, reference_stack=())
    if len(_canonical_json(projected)) > _MAX_OUTPUT_BYTES:
        raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.SIZE_EXCEEDED)
    return projected


def build_deepseek_schema_projection(schema: Mapping[str, Any]) -> DeepSeekSchemaProjection:
    """Project a schema and attach a canonical SHA-256 identity."""

    projected = project_deepseek_strict_schema(schema)
    digest = hashlib.sha256(_canonical_json(projected)).hexdigest()
    return DeepSeekSchemaProjection(
        schema=projected,
        version=DEEPSEEK_SCHEMA_PROJECTION_VERSION,
        sha256=digest,
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _project_node(
    node: object,
    *,
    state: _ProjectionState,
    depth: int,
    reference_stack: tuple[str, ...],
) -> dict[str, Any]:
    state.enter(depth)
    if not isinstance(node, dict) or any(not isinstance(key, str) for key in node):
        raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)

    unknown = set(node) - _SUPPORTED_KEYS - _STRIPPED_KEYS
    if unknown:
        raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.UNSUPPORTED_KEYWORD)

    if "$ref" in node:
        meaningful_siblings = set(node) - {"$ref"} - _STRIPPED_KEYS
        if meaningful_siblings:
            raise DeepSeekSchemaProjectionError(
                DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT
            )
        reference = node["$ref"]
        name = _local_definition_name(reference)
        if name in reference_stack:
            raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.CYCLIC_REFERENCE)
        target = state.definitions.get(name)
        if target is None:
            raise DeepSeekSchemaProjectionError(
                DeepSeekSchemaProjectionErrorCode.UNRESOLVED_REFERENCE
            )
        return _project_node(
            target,
            state=state,
            depth=depth + 1,
            reference_stack=(*reference_stack, name),
        )

    projected: dict[str, Any] = {}
    description = node.get("description")
    if description is not None:
        if not isinstance(description, str):
            raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)
        projected["description"] = description

    node_type = node.get("type")
    if node_type is not None:
        if not isinstance(node_type, str) or node_type not in _SUPPORTED_TYPES:
            raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)
        projected["type"] = node_type

    if "const" in node:
        const = copy.deepcopy(node["const"])
        existing_enum = node.get("enum")
        if existing_enum is not None and existing_enum != [const]:
            raise DeepSeekSchemaProjectionError(
                DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT
            )
        projected["enum"] = [const]
    elif "enum" in node:
        enum = node["enum"]
        if not isinstance(enum, list) or not enum:
            raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)
        projected["enum"] = copy.deepcopy(enum)

    if "anyOf" in node:
        if set(node) & {"type", "properties", "items", "enum", "const"}:
            raise DeepSeekSchemaProjectionError(
                DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT
            )
        choices = node["anyOf"]
        if not isinstance(choices, list) or not choices:
            raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)
        projected["anyOf"] = [
            _project_node(
                choice,
                state=state,
                depth=depth + 1,
                reference_stack=reference_stack,
            )
            for choice in choices
        ]

    if "items" in node:
        if node_type not in {None, "array"}:
            raise DeepSeekSchemaProjectionError(
                DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT
            )
        projected["items"] = _project_node(
            node["items"],
            state=state,
            depth=depth + 1,
            reference_stack=reference_stack,
        )

    if "properties" in node:
        if node_type not in {None, "object"}:
            raise DeepSeekSchemaProjectionError(
                DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT
            )
        properties = node["properties"]
        required = node.get("required", [])
        if (
            not isinstance(properties, dict)
            or any(not isinstance(key, str) for key in properties)
            or not isinstance(required, list)
            or any(not isinstance(key, str) for key in required)
            or len(required) != len(set(required))
            or set(required) - set(properties)
        ):
            raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)
        if "additionalProperties" in node and node["additionalProperties"] is not False:
            raise DeepSeekSchemaProjectionError(
                DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT
            )
        required_set = set(required)
        projected_properties: dict[str, Any] = {}
        for key, value in properties.items():
            child = _project_node(
                value,
                state=state,
                depth=depth + 1,
                reference_stack=reference_stack,
            )
            if key not in required_set and not _allows_null(child):
                child = {"anyOf": [child, {"type": "null"}]}
            projected_properties[key] = child
        projected["properties"] = projected_properties
        projected["required"] = list(properties)
        projected["additionalProperties"] = False
    elif node_type == "object":
        empty_required = node.get("required")
        if empty_required is not None and empty_required != []:
            raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)
        if "additionalProperties" in node and node["additionalProperties"] is not False:
            raise DeepSeekSchemaProjectionError(
                DeepSeekSchemaProjectionErrorCode.CONFLICTING_CONSTRAINT
            )
        projected["properties"] = {}
        projected["required"] = []
        projected["additionalProperties"] = False
    elif "required" in node or "additionalProperties" in node:
        raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)

    if not projected:
        raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)
    return projected


def _local_definition_name(reference: object) -> str:
    if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
        raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_REFERENCE)
    encoded = reference.removeprefix("#/$defs/")
    if not encoded or "/" in encoded:
        raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_REFERENCE)
    return encoded.replace("~1", "/").replace("~0", "~")


def _allows_null(schema: Mapping[str, Any]) -> bool:
    if schema.get("type") == "null":
        return True
    choices = schema.get("anyOf")
    return isinstance(choices, list) and any(
        isinstance(choice, dict) and choice.get("type") == "null" for choice in choices
    )


__all__ = [
    "DEEPSEEK_SCHEMA_PROJECTION_VERSION",
    "DeepSeekSchemaProjection",
    "DeepSeekSchemaProjectionError",
    "DeepSeekSchemaProjectionErrorCode",
    "build_deepseek_schema_projection",
    "project_deepseek_strict_schema",
]
