"""Non-production, manually reviewed source evidence. No parser or retrieval imports.

Loading is pure. Inspection audits explicit local PDF bytes on every call; a hash
proves source identity, never the factual correctness of a transcription.
"""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import Annotated, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)


Text = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
Identifier = Annotated[Text, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[int, Field(strict=True, gt=0)]


class EvidenceError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Intake(Model):
    year: Positive
    month: Annotated[int, Field(strict=True, ge=1, le=12)]


class Target(Model):
    target_id: Identifier
    institution_id: Identifier
    organization_id: Identifier
    program_id: Identifier
    degree_level: Identifier
    admission_cycle: Positive
    selection_route_id: Identifier
    examination_schedule_id: Identifier
    intake: Intake


class SourceSet(Model):
    source_set_id: Identifier
    revision: Positive


class FileReference(Model):
    file: Text  # descriptive only: never resolved or opened by the loader
    sha256: Digest


class Fragment(Model):
    fragment_id: Identifier
    role: Literal[
        "context",
        "clause",
        "cross_reference",
        "table_group_header",
        "table_group_note",
        "table_column_header",
        "table_row_label",
        "table_cell",
    ]
    text: Text


class Record(Model):
    record_id: Identifier
    revision: Positive
    topic_id: Identifier
    source_id: Identifier
    source_pdf_sha256: Digest
    physical_page: Positive
    printed_page_label: Text | None
    manual_anchor: Text
    fragments: tuple[Fragment, ...] = Field(min_length=1)
    required_fragment_ids: tuple[Identifier, ...] = Field(min_length=1)
    review_note_zh: Text
    review_record_id: Identifier
    capture_method: Literal["manual_transcription"]
    parser_locator: None
    bbox: None
    fact_id: None
    source_kb_sha256: None


class Relation(Model):
    from_id: Identifier = Field(alias="from")
    kind: Identifier
    to: Identifier


class ReviewRecord(Model):
    review_record_id: Identifier
    reviewer_kind: Literal["agent", "human"]
    reviewer_id: Identifier
    reviewed_on: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    method: Text
    status: Text

    @field_validator("reviewed_on")
    @classmethod
    def check_date(cls, value):
        date.fromisoformat(value)
        return value


class Topic(Model):
    topic_id: Identifier
    title_zh: Text
    record_ids: tuple[Identifier, ...] = Field(min_length=1)


def _unique(values, label):
    values = tuple(values)
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {label}")
    return set(values)


class Bundle(Model):
    schema_version: Literal["1.0"]
    artifact_role: Literal["reviewed-source-evidence-design-seed"]
    production_enabled: Literal[False]
    bundle_id: Identifier
    revision: Positive
    normalization_policy: Text
    limitations_zh: tuple[Text, ...] = Field(min_length=1)
    target: Target
    source_set: SourceSet
    source_manifest: FileReference
    target_contract: FileReference
    required_source_ids: tuple[Identifier, ...] = Field(min_length=1)
    topics: tuple[Topic, ...] = Field(min_length=1)
    records: tuple[Record, ...] = Field(min_length=1)
    relations: tuple[Relation, ...]
    review_records: tuple[ReviewRecord, ...] = Field(min_length=1)

    @field_validator("production_enabled", mode="before")
    @classmethod
    def require_false(cls, value):
        if value is not False:
            raise ValueError("production_enabled must be false")
        return value

    @model_validator(mode="after")
    def check_graph(self):
        records = {r.record_id: r for r in self.records}
        _unique((r.record_id for r in self.records), "record ID")
        topics = _unique((t.topic_id for t in self.topics), "topic ID")
        reviews = _unique((r.review_record_id for r in self.review_records), "review ID")
        sources = _unique(self.required_source_ids, "required source ID")
        _unique((f.fragment_id for r in self.records for f in r.fragments), "fragment ID")
        assigned = []
        for topic in self.topics:
            _unique(topic.record_ids, "topic record reference")
            for rid in topic.record_ids:
                if rid not in records or records[rid].topic_id != topic.topic_id:
                    raise ValueError("topic membership mismatch")
            assigned.extend(topic.record_ids)
        if _unique(assigned, "topic assignment") != set(records):
            raise ValueError("orphan record")
        for record in self.records:
            if record.topic_id not in topics or record.source_id not in sources:
                raise ValueError("unbound topic/source")
            if record.review_record_id not in reviews:
                raise ValueError("missing review record")
            required = _unique(record.required_fragment_ids, "required fragment reference")
            if required != {f.fragment_id for f in record.fragments}:
                raise ValueError("missing required context or unbound fragment")
        _unique(((r.from_id, r.kind, r.to) for r in self.relations), "relation")
        for relation in self.relations:
            if relation.from_id not in records or relation.to not in records:
                raise ValueError("dangling relation")
            if records[relation.from_id].topic_id != records[relation.to].topic_id:
                raise ValueError("relation crosses topic coverage")
        return self


class Trust(Model):
    """Explicit repository review pin; never synthesized from the input's status."""

    bundle_id: Identifier
    revision: Positive
    bundle_sha256: Digest


class Source(Model):
    source_id: Identifier
    sha256: Digest
    physical_page_count: Positive
    official_url: Text

    @model_validator(mode="after")
    def check_url(self):
        url = urlsplit(self.official_url)
        if url.scheme != "https" or not url.netloc or url.username or url.password:
            raise ValueError("invalid official HTTPS URL")
        return self


class LoadedEvidence(Model):
    bundle: Bundle
    bundle_sha256: Digest
    canonical_sha256: Digest
    sources: tuple[Source, ...]


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def canonical_bundle_bytes(bundle: Bundle) -> bytes:
    return canonical_json_bytes(bundle.model_dump(mode="json", by_alias=True))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"non-finite JSON value: {value}")


def parse_json(raw: bytes):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)


def load_evidence_bytes(
    raw: bytes, *, manifest_bytes: bytes, target_contract_bytes: bytes, trust: Trust
) -> LoadedEvidence:
    """Pure exact-byte loading. Does not read files, resolve paths or audit PDFs."""
    if sha256(raw).hexdigest() != trust.bundle_sha256:
        raise EvidenceError("digest_mismatch", "bundle bytes do not match repository review pin")
    try:
        bundle = Bundle.model_validate(parse_json(raw))
        if (bundle.bundle_id, bundle.revision) != (trust.bundle_id, trust.revision):
            raise EvidenceError("revision_mismatch", "bundle identity/revision does not match pin")
        for data, reference in (
            (manifest_bytes, bundle.source_manifest),
            (target_contract_bytes, bundle.target_contract),
        ):
            if sha256(data).hexdigest() != reference.sha256:
                raise EvidenceError("binding_digest_mismatch", "source metadata bytes changed")
        manifest = parse_json(manifest_bytes)
        contract = parse_json(target_contract_bytes)
        if Target.model_validate(contract["target"]) != bundle.target:
            raise ValueError("target contract mismatch")
        source_set = contract["source_set"]
        if (
            SourceSet.model_validate({k: source_set[k] for k in ("source_set_id", "revision")})
            != bundle.source_set
            or source_set["target_id"] != bundle.target.target_id
        ):
            raise ValueError("source-set binding mismatch")
        sources = tuple(
            Source.model_validate({k: row[k] for k in Source.model_fields})
            for row in manifest["sources"]
        )
        source_ids = _unique((s.source_id for s in sources), "manifest source")
        members = source_set["members"]
        if _unique((m["source_id"] for m in members), "source-set member") != source_ids:
            raise ValueError("source-set membership mismatch")
        by_id = {s.source_id: s for s in sources}
        for member in members:
            source = by_id[member["source_id"]]
            if (
                member["source_pdf_sha256"] != source.sha256
                or type(member["physical_page_count"]) is not int
                or member["physical_page_count"] != source.physical_page_count
                or member["requirement"] not in ("core", "conditional")
            ):
                raise ValueError("source-set member identity mismatch")
        core = {m["source_id"] for m in members if m["requirement"] == "core"}
        if set(bundle.required_source_ids) != core:
            raise ValueError("required sources must equal core membership")
        for record in bundle.records:
            source = by_id[record.source_id]
            if record.source_pdf_sha256 != source.sha256:
                raise ValueError("record source hash mismatch")
            if record.physical_page > source.physical_page_count:
                raise EvidenceError("page_out_of_range", "record physical page exceeds source")
        return LoadedEvidence(
            bundle=bundle,
            bundle_sha256=trust.bundle_sha256,
            canonical_sha256=sha256(canonical_bundle_bytes(bundle)).hexdigest(),
            sources=sources,
        )
    except EvidenceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise EvidenceError("invalid_schema", "invalid evidence schema or source binding") from exc


def audit_sources(evidence: LoadedEvidence, paths: Mapping[str, Path]) -> list[dict]:
    """Read only explicit core paths. Hash and metadata use the same in-memory bytes."""
    import pymupdf

    audited = []
    sources = {s.source_id: s for s in evidence.sources}
    for source_id in evidence.bundle.required_source_ids:
        if source_id not in paths:
            raise EvidenceError("missing_source", f"no explicit path for {source_id}")
        try:
            raw = Path(paths[source_id]).read_bytes()
        except OSError as exc:
            raise EvidenceError("missing_source", f"source unavailable: {source_id}") from exc
        source = sources[source_id]
        digest = sha256(raw).hexdigest()
        if digest != source.sha256:
            raise EvidenceError("source_hash_mismatch", f"source bytes changed: {source_id}")
        try:
            with pymupdf.open(stream=raw, filetype="pdf") as pdf:
                pages = pdf.page_count
                if not pdf.is_pdf or pdf.needs_pass:
                    raise ValueError("not a readable PDF")
        except Exception as exc:
            raise EvidenceError("invalid_pdf", f"PDF metadata unavailable: {source_id}") from exc
        if pages != source.physical_page_count:
            raise EvidenceError("page_count_mismatch", f"PDF page count mismatch: {source_id}")
        audited.append({"source_id": source_id, "sha256": digest, "physical_page_count": pages})
    return audited


def inspect_evidence(
    raw: bytes,
    *,
    manifest_bytes: bytes,
    target_contract_bytes: bytes,
    trust: Trust,
    target: dict,
    source_set: dict,
    topic_id: str,
    source_paths: Mapping[str, Path],
) -> dict:
    """No reusable success token: every successful preview reloads and freshly audits."""
    evidence = load_evidence_bytes(
        raw, manifest_bytes=manifest_bytes, target_contract_bytes=target_contract_bytes, trust=trust
    )
    bundle = evidence.bundle
    try:
        requested_target = Target.model_validate(target)
        requested_set = SourceSet.model_validate(source_set)
    except ValidationError as exc:
        raise EvidenceError("not_covered", "complete exact target and source-set required") from exc
    topic = next((t for t in bundle.topics if t.topic_id == topic_id), None)
    if requested_target != bundle.target or requested_set != bundle.source_set or topic is None:
        raise EvidenceError(
            "not_covered", "target, source-set or topic is outside reviewed coverage"
        )
    audit = audit_sources(evidence, source_paths)
    sources = {s.source_id: s for s in evidence.sources}
    by_id = {r.record_id: r for r in bundle.records}
    records = []
    for rid in topic.record_ids:
        record = by_id[rid]
        url = urlsplit(sources[record.source_id].official_url)
        records.append(
            {
                **record.model_dump(mode="json"),
                "official_url": urlunsplit(url._replace(fragment=f"page={record.physical_page}")),
            }
        )
    return {
        "status": "source_identity_verified",
        "production_enabled": False,
        "verification_note_zh": "仅核验文件身份与仓库审核摘要；不自动证明人工转录正确，须由设计主 Agent 独立验收。",
        "bundle_id": bundle.bundle_id,
        "revision": bundle.revision,
        "bundle_sha256": evidence.bundle_sha256,
        "canonical_sha256": evidence.canonical_sha256,
        "target": bundle.target.model_dump(mode="json"),
        "source_set": bundle.source_set.model_dump(mode="json"),
        "topic": topic.model_dump(mode="json"),
        "records": records,
        "relations": [
            r.model_dump(mode="json", by_alias=True)
            for r in bundle.relations
            if r.from_id in topic.record_ids
        ],
        "review_records": [r.model_dump(mode="json") for r in bundle.review_records],
        "limitations_zh": list(bundle.limitations_zh),
        "normalization_policy": bundle.normalization_policy,
        "source_audit": audit,
        "highlight_support": "unknown",
    }


def render_markdown(preview: dict) -> str:
    lines = [
        f"# {preview['topic']['title_zh']}",
        "",
        preview["verification_note_zh"],
        "",
        "完整历史目标：`" + canonical_json_bytes(preview["target"]).decode().strip() + "`",
        "",
        "来源集：`" + canonical_json_bytes(preview["source_set"]).decode().strip() + "`",
        "",
        f"证据 revision {preview['revision']} / SHA-256 `{preview['bundle_sha256']}`",
        "",
    ]
    lines.extend(f"- {note}" for note in preview["limitations_zh"])
    for record in preview["records"]:
        lines.extend(
            [
                "",
                f"## {record['record_id']} — {record['source_id']}",
                "",
                f"[官方文件，物理页 {record['physical_page']}]({record['official_url']})；"
                f"印刷页：{record['printed_page_label'] or '无'}",
                "",
                f"定位：{record['manual_anchor']}",
                "",
                "日文原文（独立分段）：",
                "",
            ]
        )
        for fragment in record["fragments"]:
            lines.extend(
                [
                    f"{fragment['fragment_id']} / {fragment['role']}",
                    "",
                    *[f"> {line}" for line in fragment["text"].splitlines()],
                    "",
                ]
            )
        lines.append(f"中文审核注释（非官方引文）：{record['review_note_zh']}")
    lines.extend(
        [
            "",
            "## 审核关系与来源身份",
            "",
            "```json",
            canonical_json_bytes(
                {k: preview[k] for k in ("relations", "review_records", "source_audit")}
            )
            .decode()
            .strip(),
            "```",
            "",
        ]
    )
    return "\n".join(lines)
