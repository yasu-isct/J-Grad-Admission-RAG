"""Explicit, non-production import of pinned reviewed fragments into candidate KBs.

Mapping is pure. PDF auditing and immutable publication are separate operations.
"""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from typing import Annotated, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .builder.kb_builder import evaluate_quality_gates, fact_to_retrieval_unit
from .retrieval.embedding_text import EMBEDDING_TEXT_VERSION, build_embedding_text
from .reviewed_source_evidence import (
    Digest,
    Identifier,
    LoadedEvidence,
    SourceSet,
    Target,
    Trust,
    audit_sources,
    canonical_json_bytes,
    load_evidence_bytes,
    parse_json,
)
from .schemas.document_identity import DocumentIdentity
from .schemas.document_kb import (
    BuildDiagnostics,
    BuildQualityThresholds,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    ScopedFact,
    canonical_document_kb_bytes,
    load_document_kb_bytes,
)


class ImportError(ValueError):
    """A candidate input or immutable artifact failed validation."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImportTrust(StrictModel):
    bundle_id: Identifier
    revision: Annotated[int, Field(strict=True, gt=0)]
    bundle_sha256: Digest
    import_config_sha256: Digest

    def evidence_trust(self) -> Trust:
        return Trust(
            bundle_id=self.bundle_id, revision=self.revision, bundle_sha256=self.bundle_sha256
        )


class ConfigDocument(StrictModel):
    source_id: Identifier
    identity: DocumentIdentity


class ImportConfig(StrictModel):
    schema_version: Literal["1.0"]
    artifact_role: Literal["reviewed-fragment-import-config"]
    production_enabled: Literal[False]
    profile_id: Literal["reviewed-source-v1"]
    profile_version: Literal["1"]
    mapper_version: Literal["1"]
    bundle_id: Identifier
    bundle_revision: Annotated[int, Field(strict=True, gt=0)]
    bundle_sha256: Digest
    target: Target
    source_set: SourceSet
    documents: tuple[ConfigDocument, ...] = Field(min_length=1)

    @field_validator("production_enabled", mode="before")
    @classmethod
    def require_false(cls, value):
        if value is not False:
            raise ValueError("production_enabled must be false")
        return value

    @model_validator(mode="after")
    def unique_documents(self):
        ids = [row.source_id for row in self.documents]
        if len(ids) != len(set(ids)) or len(ids) != len(
            {row.identity.document_id for row in self.documents}
        ):
            raise ValueError("duplicate source or document ID")
        if any(row.source_id != row.identity.document_id for row in self.documents):
            raise ValueError("document_id must equal source_id")
        return self


class QualifiedFact(StrictModel):
    document_id: Identifier
    kb_sha256: Digest
    fact_id: str = Field(min_length=1)


class LineageFragment(StrictModel):
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
    qualified_fact: QualifiedFact


class LineageRecord(StrictModel):
    record_id: Identifier
    revision: Annotated[int, Field(strict=True, gt=0)]
    topic_id: Identifier
    source_id: Identifier
    source_pdf_sha256: Digest
    physical_page: Annotated[int, Field(strict=True, gt=0)]
    printed_page_label: str | None
    manual_anchor: str = Field(min_length=1)
    capture_method: Literal["manual_transcription"]
    review_record_id: Identifier
    fragments: tuple[LineageFragment, ...] = Field(min_length=1)
    required_fragment_ids: tuple[Identifier, ...] = Field(min_length=1)


class LineageRelation(StrictModel):
    from_id: Identifier = Field(alias="from")
    kind: Identifier
    to: Identifier
    from_facts: tuple[QualifiedFact, ...] = Field(min_length=1)
    to_facts: tuple[QualifiedFact, ...] = Field(min_length=1)


class LineageDocument(StrictModel):
    source_id: Identifier
    identity: DocumentIdentity
    kb_sha256: Digest
    fact_count: Annotated[int, Field(strict=True, ge=0)]


class BundleBinding(StrictModel):
    bundle_id: Identifier
    revision: Annotated[int, Field(strict=True, gt=0)]
    sha256: Digest


class Lineage(StrictModel):
    schema_version: Literal["1.0"]
    artifact_role: Literal["reviewed-fragment-lineage"]
    production_enabled: Literal[False]
    build_id: Digest
    bundle: BundleBinding
    source_manifest_sha256: Digest
    target_contract_sha256: Digest
    import_config_sha256: Digest
    target: Target
    source_set: SourceSet
    documents: tuple[LineageDocument, ...] = Field(min_length=1)
    records: tuple[LineageRecord, ...] = Field(min_length=1)
    relations: tuple[LineageRelation, ...]

    @field_validator("production_enabled", mode="before")
    @classmethod
    def require_false(cls, value):
        if value is not False:
            raise ValueError("production_enabled must be false")
        return value

    @model_validator(mode="after")
    def check_ids_and_context(self):
        docs = [row.identity.document_id for row in self.documents]
        sources = [row.source_id for row in self.documents]
        records = {row.record_id: row for row in self.records}
        if (
            len(docs) != len(set(docs))
            or len(sources) != len(set(sources))
            or len(records) != len(self.records)
        ):
            raise ValueError("duplicate lineage document or record")
        all_facts = []
        all_fragments = []
        by_source = {row.source_id: row for row in self.documents}
        for record in self.records:
            document = by_source.get(record.source_id)
            if document is None or record.source_pdf_sha256 != document.identity.source_pdf_sha256:
                raise ValueError("lineage record has wrong source document")
            fragments = {f.fragment_id: f for f in record.fragments}
            if len(fragments) != len(record.fragments):
                raise ValueError("duplicate lineage fragment")
            if len(set(record.required_fragment_ids)) != len(record.required_fragment_ids) or set(
                record.required_fragment_ids
            ) != set(fragments):
                raise ValueError("incomplete required context")
            all_facts.extend(f.qualified_fact.fact_id for f in record.fragments)
            all_fragments.extend(fragments)
            for fragment in record.fragments:
                ref = fragment.qualified_fact
                if (
                    ref.document_id != document.identity.document_id
                    or ref.kb_sha256 != document.kb_sha256
                    or ref.fact_id
                    != f"fact:reviewed:{record.source_id}:{record.record_id}:r{record.revision}:{fragment.fragment_id}"
                ):
                    raise ValueError("lineage fragment has wrong qualified fact")
        if len(all_facts) != len(set(all_facts)) or len(all_fragments) != len(set(all_fragments)):
            raise ValueError("duplicate mapped fact or fragment")
        keys = [(r.from_id, r.kind, r.to) for r in self.relations]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate relation")
        for relation in self.relations:
            if relation.from_id not in records or relation.to not in records:
                raise ValueError("dangling relation")
            left, right = records[relation.from_id], records[relation.to]
            if left.topic_id != right.topic_id:
                raise ValueError("cross-topic relation")
            for actual, record in ((relation.from_facts, left), (relation.to_facts, right)):
                by_id = {f.fragment_id: f.qualified_fact for f in record.fragments}
                if actual != tuple(by_id[fid] for fid in record.required_fragment_ids):
                    raise ValueError("relation omits required context")
        return self


class CandidateDocument(StrictModel):
    document_id: Identifier
    relative_path: str
    kb_sha256: Digest


class Candidate(StrictModel):
    schema_version: Literal["1.0"]
    artifact_role: Literal["reviewed-kb-candidate"]
    production_enabled: Literal[False]
    coverage: Literal["reviewed_fragments_only"]
    pdf_reference_resolution: Literal["not_run"]
    build_id: Digest
    input_descriptor: dict
    documents: tuple[CandidateDocument, ...] = Field(min_length=1)
    lineage_sha256: Digest

    @field_validator("production_enabled", mode="before")
    @classmethod
    def require_false(cls, value):
        if value is not False:
            raise ValueError("production_enabled must be false")
        return value

    @model_validator(mode="after")
    def fixed_paths(self):
        ids = [row.document_id for row in self.documents]
        if len(ids) != len(set(ids)) or ids != sorted(ids):
            raise ValueError("candidate documents must be unique and sorted")
        for row in self.documents:
            if row.relative_path != f"documents/{row.document_id}/document_kb.json":
                raise ValueError("candidate path is not the fixed relative path")
        return self


def _digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def load_inputs(
    bundle_raw: bytes,
    manifest_raw: bytes,
    contract_raw: bytes,
    config_raw: bytes,
    trust: ImportTrust,
) -> tuple[LoadedEvidence, ImportConfig]:
    """Pure exact-byte loading. Trust is repository-reviewed input, never derived from config."""
    if _digest(config_raw) != trust.import_config_sha256:
        raise ImportError("import config bytes differ from reviewed pin")
    evidence = load_evidence_bytes(
        bundle_raw,
        manifest_bytes=manifest_raw,
        target_contract_bytes=contract_raw,
        trust=trust.evidence_trust(),
    )
    try:
        config = ImportConfig.model_validate(parse_json(config_raw))
        bundle = evidence.bundle
        if (config.bundle_id, config.bundle_revision, config.bundle_sha256) != (
            bundle.bundle_id,
            bundle.revision,
            evidence.bundle_sha256,
        ):
            raise ValueError("config bundle binding mismatch")
        if config.target != bundle.target or config.source_set != bundle.source_set:
            raise ValueError("config target/source-set mismatch")
        sources = {source.source_id: source for source in evidence.sources}
        members = {
            member["source_id"]: member
            for member in parse_json(contract_raw)["source_set"]["members"]
        }
        if set(row.source_id for row in config.documents) != set(bundle.required_source_ids):
            raise ValueError("config documents must match exactly the reviewed core sources")
        for row in config.documents:
            source = sources[row.source_id]
            identity = row.identity
            member = members[row.source_id]
            if (
                identity.source_pdf_sha256 != source.sha256
                or identity.official_source_url != source.official_url
                or identity.institution_id != bundle.target.institution_id
                or identity.document_family_id != member["document_family_id"]
                or identity.edition_id != member["edition_id"]
                or identity.model_dump(mode="json")["revision_date"] != member["revision_date"]
            ):
                raise ValueError("document identity/source mismatch")
        return evidence, config
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        raise ImportError("invalid import config or source identity") from exc


def input_descriptor(
    evidence: LoadedEvidence,
    config: ImportConfig,
    manifest_raw: bytes,
    contract_raw: bytes,
    config_raw: bytes,
) -> dict:
    return {
        "profile_id": config.profile_id,
        "profile_version": config.profile_version,
        "mapper_version": config.mapper_version,
        "bundle_id": evidence.bundle.bundle_id,
        "bundle_revision": evidence.bundle.revision,
        "bundle_sha256": evidence.bundle_sha256,
        "source_manifest_sha256": _digest(manifest_raw),
        "target_contract_sha256": _digest(contract_raw),
        "import_config_sha256": _digest(config_raw),
        "target": config.target.model_dump(mode="json"),
        "source_set": config.source_set.model_dump(mode="json"),
        "documents": [
            dict(source_id=row.source_id, identity=row.identity.model_dump(mode="json"))
            for row in sorted(config.documents, key=lambda item: item.source_id)
        ],
        "kb_schema_version": "0.6",
        "document_identity_schema_version": "1.0",
        "embedding_text_version": EMBEDDING_TEXT_VERSION,
        "lineage_schema_version": "1.0",
        "candidate_schema_version": "1.0",
    }


def map_candidate(
    evidence: LoadedEvidence,
    config: ImportConfig,
    manifest_raw: bytes,
    contract_raw: bytes,
    config_raw: bytes,
) -> dict[str, bytes]:
    """Map exact fragments into five canonical files without filesystem or PDF access."""
    descriptor = input_descriptor(evidence, config, manifest_raw, contract_raw, config_raw)
    build_id = _digest(canonical_json_bytes(descriptor))
    records = sorted(evidence.bundle.records, key=lambda row: row.record_id)
    by_source = {row.source_id: row for row in config.documents}
    files: dict[str, bytes] = {}
    document_rows = []
    candidate_rows = []
    facts_by_fragment: dict[str, QualifiedFact] = {}
    for source_id in sorted(by_source):
        identity = by_source[source_id].identity
        pieces = sorted(
            (
                (record, fragment)
                for record in records
                if record.source_id == source_id
                for fragment in record.fragments
            ),
            key=lambda pair: (pair[0].record_id, pair[1].fragment_id),
        )
        facts = []
        for record, fragment in pieces:
            if not fragment.text.strip() or len(fragment.text) > 6000:
                raise ImportError("blank or oversized reviewed fragment")
            fact = ScopedFact(
                fact_id=f"fact:reviewed:{source_id}:{record.record_id}:r{record.revision}:{fragment.fragment_id}",
                fact_type="reviewed_source_fragment",
                scope_type="unknown",
                scope_targets=[],
                parent_college=None,
                title=f"reviewed fragment {fragment.fragment_id}",
                text=fragment.text,
                source_pages=[record.physical_page],
                section_path=[],
                evidence=[],
                confidence=0.5,
                embedding_text="",
                metadata={
                    "capture_method": record.capture_method,
                    "record_id": record.record_id,
                    "record_revision": record.revision,
                    "fragment_id": fragment.fragment_id,
                    "fragment_role": fragment.role,
                    "source_id": source_id,
                    "review_record_id": record.review_record_id,
                    "title_kind": "technical_label",
                },
            )
            facts.append(fact.model_copy(update={"embedding_text": build_embedding_text(fact)}))
        ids = [fact.fact_id for fact in facts]
        if len(ids) != len(set(ids)):
            raise ImportError("duplicate mapped fact ID")
        thresholds = BuildQualityThresholds(max_missing_section_paths=0, max_unknown_scope_facts=0)
        diagnostics = BuildDiagnostics(
            input_chunk_count=len(facts),
            emitted_chunk_count=len(facts),
            missing_section_path_fact_ids=ids,
            unknown_scope_fact_ids=ids,
            short_fact_ids=[fact.fact_id for fact in facts if len(fact.text) < 100],
            max_chunk_chars=max((len(fact.text) for fact in facts), default=0),
            quality_thresholds=thresholds,
        )
        diagnostics.quality_gate = evaluate_quality_gates(diagnostics, thresholds)
        if diagnostics.quality_gate.passed:
            raise ImportError("candidate cannot pass production quality gates")
        kb = DocumentKnowledgeBase(
            manifest=KnowledgeManifest(
                identity=identity,
                source_pdf=f"{identity.source_pdf_sha256}.pdf",
                builder_version="reviewed-source-v1.1",
                input_chunk_count=len(facts),
                chunk_count=len(facts),
                max_chunk_chars=diagnostics.max_chunk_chars,
            ),
            entities=[],
            facts=facts,
            retrieval_units=[fact_to_retrieval_unit(fact) for fact in facts],
            diagnostics=diagnostics,
        )
        relative = f"documents/{identity.document_id}/document_kb.json"
        raw = canonical_document_kb_bytes(kb)
        files[relative] = raw
        kb_hash = _digest(raw)
        document_rows.append(
            LineageDocument(
                source_id=source_id, identity=identity, kb_sha256=kb_hash, fact_count=len(facts)
            )
        )
        candidate_rows.append(
            CandidateDocument(
                document_id=identity.document_id, relative_path=relative, kb_sha256=kb_hash
            )
        )
        for (record, fragment), fact in zip(pieces, facts, strict=True):
            facts_by_fragment[fragment.fragment_id] = QualifiedFact(
                document_id=identity.document_id, kb_sha256=kb_hash, fact_id=fact.fact_id
            )
    record_rows = [
        LineageRecord(
            record_id=record.record_id,
            revision=record.revision,
            topic_id=record.topic_id,
            source_id=record.source_id,
            source_pdf_sha256=record.source_pdf_sha256,
            physical_page=record.physical_page,
            printed_page_label=record.printed_page_label,
            manual_anchor=record.manual_anchor,
            capture_method=record.capture_method,
            review_record_id=record.review_record_id,
            fragments=tuple(
                LineageFragment(
                    fragment_id=f.fragment_id,
                    role=f.role,
                    qualified_fact=facts_by_fragment[f.fragment_id],
                )
                for f in record.fragments
            ),
            required_fragment_ids=record.required_fragment_ids,
        )
        for record in records
    ]
    record_by_id = {row.record_id: row for row in record_rows}

    def required(rid: str) -> tuple[QualifiedFact, ...]:
        row = record_by_id[rid]
        fragments = {f.fragment_id: f.qualified_fact for f in row.fragments}
        return tuple(fragments[fid] for fid in row.required_fragment_ids)

    relations = [
        LineageRelation.model_validate(
            {
                "from": relation.from_id,
                "kind": relation.kind,
                "to": relation.to,
                "from_facts": required(relation.from_id),
                "to_facts": required(relation.to),
            }
        )
        for relation in sorted(
            evidence.bundle.relations, key=lambda row: (row.from_id, row.kind, row.to)
        )
    ]
    lineage = Lineage(
        schema_version="1.0",
        artifact_role="reviewed-fragment-lineage",
        production_enabled=False,
        build_id=build_id,
        bundle=BundleBinding(
            bundle_id=evidence.bundle.bundle_id,
            revision=evidence.bundle.revision,
            sha256=evidence.bundle_sha256,
        ),
        source_manifest_sha256=_digest(manifest_raw),
        target_contract_sha256=_digest(contract_raw),
        import_config_sha256=_digest(config_raw),
        target=config.target,
        source_set=config.source_set,
        documents=tuple(document_rows),
        records=tuple(record_rows),
        relations=tuple(relations),
    )
    lineage_raw = canonical_json_bytes(lineage.model_dump(mode="json", by_alias=True))
    files["lineage.json"] = lineage_raw
    candidate = Candidate(
        schema_version="1.0",
        artifact_role="reviewed-kb-candidate",
        production_enabled=False,
        coverage="reviewed_fragments_only",
        pdf_reference_resolution="not_run",
        build_id=build_id,
        input_descriptor=descriptor,
        documents=tuple(candidate_rows),
        lineage_sha256=_digest(lineage_raw),
    )
    files["candidate.json"] = canonical_json_bytes(candidate.model_dump(mode="json"))
    if len(files) != len(config.documents) + 2 or sum(map(len, files.values())) > 8 * 1024 * 1024:
        raise ImportError("candidate exceeds fixed file count or 8 MiB limit")
    return files


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _check_existing_ancestors(path: Path) -> None:
    current = path.absolute()
    while True:
        if current.exists() and _is_reparse(current):
            raise ImportError("candidate path traverses link or junction")
        if current == current.parent:
            break
        current = current.parent


def _read_exact_tree(root: Path, expected: Mapping[str, bytes]) -> None:
    """Validate the complete fixed tree, including bytes, without following links/junctions."""
    _check_existing_ancestors(root)
    if _is_reparse(root) or not root.is_dir():
        raise ImportError("candidate root is unsafe")
    wanted_files = set(expected)
    wanted_dirs = {""}
    for relative in wanted_files:
        parts = Path(relative).parts
        if Path(relative).is_absolute() or ".." in parts or not parts:
            raise ImportError("unsafe candidate relative path")
        wanted_dirs.update(Path(*parts[:index]).as_posix() for index in range(1, len(parts)))
    found_files = set()
    found_dirs = {""}
    stack = [(root, "")]
    while stack:
        folder, prefix = stack.pop()
        for entry in os.scandir(folder):
            path = Path(entry.path)
            if _is_reparse(path):
                raise ImportError("candidate contains link or junction")
            relative = f"{prefix}/{entry.name}".lstrip("/")
            if entry.is_dir(follow_symlinks=False):
                found_dirs.add(relative)
                stack.append((path, relative))
            elif entry.is_file(follow_symlinks=False):
                found_files.add(relative)
            else:
                raise ImportError("candidate contains unsupported filesystem entry")
    if found_files != wanted_files or found_dirs != wanted_dirs:
        raise ImportError("candidate has missing or extra files")
    for relative, raw in expected.items():
        if (root / relative).read_bytes() != raw:
            raise ImportError(f"candidate bytes differ: {relative}")
    candidate = Candidate.model_validate(parse_json((root / "candidate.json").read_bytes()))
    lineage = Lineage.model_validate(parse_json((root / "lineage.json").read_bytes()))
    if candidate.build_id != lineage.build_id or candidate.lineage_sha256 != _digest(
        expected["lineage.json"]
    ):
        raise ImportError("candidate lineage binding mismatch")
    if _digest(canonical_json_bytes(candidate.input_descriptor)) != candidate.build_id:
        raise ImportError("candidate build identity mismatch")
    by_id = {row.identity.document_id: row for row in lineage.documents}
    for row in candidate.documents:
        kb_raw = expected[row.relative_path]
        kb = load_document_kb_bytes(kb_raw)
        if (
            row.document_id not in by_id
            or row.kb_sha256 != _digest(kb_raw)
            or by_id[row.document_id].kb_sha256 != row.kb_sha256
            or kb.manifest.identity != by_id[row.document_id].identity
            or canonical_document_kb_bytes(kb) != kb_raw
        ):
            raise ImportError("candidate KB binding mismatch")


def validate_candidate(
    root: Path,
    evidence: LoadedEvidence,
    config: ImportConfig,
    manifest_raw: bytes,
    contract_raw: bytes,
    config_raw: bytes,
) -> dict[str, str]:
    """Recompute the complete mapping and compare immutable bytes, not only self-reported hashes."""
    expected = map_candidate(evidence, config, manifest_raw, contract_raw, config_raw)
    try:
        _read_exact_tree(root, expected)
    except (OSError, ValidationError, ValueError, KeyError) as exc:
        raise ImportError("candidate validation failed") from exc
    return {name: _digest(raw) for name, raw in sorted(expected.items())}


def publish_candidate(
    candidate_root: Path,
    evidence: LoadedEvidence,
    config: ImportConfig,
    manifest_raw: bytes,
    contract_raw: bytes,
    config_raw: bytes,
    source_paths: Mapping[str, Path],
) -> tuple[Path, str, dict[str, str]]:
    """Audit three explicit PDFs, then atomically publish or reuse one immutable candidate."""
    if set(source_paths) != set(evidence.bundle.required_source_ids):
        raise ImportError("exactly the required source paths must be explicit")
    audit_sources(evidence, source_paths)
    expected = map_candidate(evidence, config, manifest_raw, contract_raw, config_raw)
    candidate = Candidate.model_validate(parse_json(expected["candidate.json"]))
    root = Path(candidate_root)
    _check_existing_ancestors(root)
    if root.exists() and (_is_reparse(root) or not root.is_dir()):
        raise ImportError("candidate parent is unsafe")
    root.mkdir(parents=True, exist_ok=True)
    final = root / candidate.build_id
    if final.exists() or final.is_symlink():
        return (
            final,
            "reused",
            validate_candidate(final, evidence, config, manifest_raw, contract_raw, config_raw),
        )
    with TemporaryDirectory(prefix=f".{candidate.build_id}.", dir=root) as staging_name:
        staging = Path(staging_name)
        for relative, raw in expected.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        _read_exact_tree(staging, expected)
        try:
            os.rename(staging, final)
        except OSError:
            if not final.exists():
                raise
            return (
                final,
                "reused",
                validate_candidate(final, evidence, config, manifest_raw, contract_raw, config_raw),
            )
    return (
        final,
        "generated",
        validate_candidate(final, evidence, config, manifest_raw, contract_raw, config_raw),
    )


def read_context(
    root: Path, lineage: Lineage, start: str | QualifiedFact
) -> tuple[ScopedFact, ...]:
    """Read complete required context over relation edges in both directions."""
    records = {record.record_id: record for record in lineage.records}
    if isinstance(start, QualifiedFact):
        matches = [
            record.record_id
            for record in lineage.records
            if any(fragment.qualified_fact == start for fragment in record.fragments)
        ]
        if len(matches) != 1:
            raise ImportError("qualified fact is not in lineage")
        start_id = matches[0]
    else:
        start_id = start
    if start_id not in records:
        raise ImportError("record is not in lineage")
    neighbors: dict[str, set[str]] = {rid: set() for rid in records}
    for relation in lineage.relations:
        neighbors[relation.from_id].add(relation.to)
        neighbors[relation.to].add(relation.from_id)
    visited = set()
    pending = [start_id]
    qualified = []
    while pending:
        rid = pending.pop()
        if rid in visited:
            continue
        visited.add(rid)
        record = records[rid]
        by_id = {f.fragment_id: f.qualified_fact for f in record.fragments}
        qualified.extend(by_id[fid] for fid in record.required_fragment_ids)
        pending.extend(sorted(neighbors[rid] - visited, reverse=True))
    kb_by_id = {}
    for document in lineage.documents:
        document_id = document.identity.document_id
        path = root / "documents" / document_id / "document_kb.json"
        try:
            if _is_reparse(path) or not path.is_file():
                raise OSError
            raw = path.read_bytes()
        except OSError as exc:
            raise ImportError("context KB unavailable") from exc
        if _digest(raw) != document.kb_sha256:
            raise ImportError("context KB digest mismatch")
        kb = load_document_kb_bytes(raw)
        kb_by_id[document_id] = {fact.fact_id: fact for fact in kb.facts}
    result = []
    for ref in qualified:
        document = next(
            (d for d in lineage.documents if d.identity.document_id == ref.document_id), None
        )
        if document is None or ref.kb_sha256 != document.kb_sha256:
            raise ImportError("context fact has wrong document binding")
        fact = kb_by_id[ref.document_id].get(ref.fact_id)
        if fact is None:
            raise ImportError("context fact missing")
        result.append(fact)
    return tuple(result)
