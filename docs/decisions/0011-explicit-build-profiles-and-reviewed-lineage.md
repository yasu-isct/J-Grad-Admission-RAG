# ADR 0011: Explicit build profiles and reviewed excerpt lineage

Status: Accepted design boundary on merge. Only BUILD-01 is released by this ADR;
reviewed import, artifact publication and report integration require later Specs.
Owner: [#191](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/191).
Baseline: main `e46721a31f642564536a6c1d92a58417335f2364`, after accepted EVID-01 #202 / PR #204.

## Evidence and problem

`builder/kb_builder.py` always invokes `propagate_department_context`, `infer_scope`
and `build_entities`. Even an empty index emits 25 ISCT entities. The scope rules include
fixed pages 7/8/75, 2027 clauses, college names and the Tsinghua program. Identity/hash
validation does not stop another institution from entering this pipeline.

The extractor and chunker also contain reviewed ISCT-era banner, heading and table heuristics.
Moving only the college dictionary would not make the whole pipeline school-neutral.
Existing callers include the CLI, Demo, synchronous service build and build jobs. Some
synthetic tests intentionally use a non-ISCT identity with this historical pipeline.

EVID-01's unchanged revision-1 seed contains eight records / 23 separate fragments:
common guideline 1/2, department guide 5/12, additional sheet 2/9 (records/fragments).
The exact source inspection is accepted, but there are no GSFS production KBs or rules.
Existing `DocumentKnowledgeBase` 0.6 supports Facts, RetrievalUnits and canonical bytes;
`ReviewedReportEvidenceBundle` 1.0 still binds exactly one document and one KB.

## Decision 1: an explicit route, alongside bounded legacy compatibility

Isolate the existing entity catalog, context propagation and scope inference in one named
`legacy-isct-v1` profile. Preserve rule order, confidence, entity IDs, Fact IDs and every
serialized output field. Shared Fact assembly, embedding text, diagnostics and serialization
remain reusable. Do not invent a generic fallback, a GSFS dictionary or a dynamic plugin system.

Add a Python build entry whose profile argument is required. The only implemented PDF profile
in BUILD-01 is `legacy-isct-v1`. Its declared compatibility is the current ISCT institution,
document family and edition (from the existing reviewed identity); other institutions,
families/editions, missing/unknown profiles and incompatible input kinds fail before PDF I/O,
extraction or output creation. This is explicit compatibility validation, not school-name
dispatch. Selecting a profile never substitutes the caller's identity or bypasses PDF hashing.

Retain `build_document_kb(...)` and existing low-level helper import paths as compatibility
wrappers with unchanged behavior, including current synthetic uses. Existing CLI/HTTP contracts
and Demo remain on that path in this issue. **Omitting a profile on this old function still
runs the legacy pipeline; this ADR does not claim all existing build routes reject new schools.**
New onboarding/import code must use an explicit reviewed profile and must not use these wrappers.
Retiring or changing the old public routes is a separate product/API decision.

Extractor/chunker behavior remains unchanged and belongs to the legacy PDF pipeline in this
design. It is not automatically shared with reviewed-source ingestion. BUILD-01 isolates the
three policy seams and guards the new entry; it does not certify a universal PDF builder.

No new manifest field, schema version or builder-version churn is needed for this behavior-
preserving refactor. Record the selected profile and code revision in the implementation's
external acceptance report, without changing existing KB bytes or runtime pointers.

## Decision 2: destination and granularity of the later reviewed import

This is the next design boundary, not an executable import Spec yet:

- Keep one `DocumentKnowledgeBase` 0.6 per exact source document; never merge the three PDFs
  under one synthetic document identity. Future import builds only the reviewed subset and
  never presents it as full-document or complete materials coverage.
- Preserve each fragment as one Fact with `text` exactly equal to the reviewed fragment text.
  The current seed therefore implies 23 Facts distributed 2/12/9, subject to the later Spec's
  explicit review. Reuse canonical KB serialization and the existing embedding-text projection;
  constructing a RetrievalUnit string does not authorize model loading or embedding.
- IDs must derive from versioned source/record/fragment identity, not loop position. A reference
  outside one KB must include document ID, exact KB hash and Fact ID. Define the precise ID
  format and ordering in the import Spec before implementation.
- A record's required fragments and reviewed relations remain explicit. A single table cell,
  negation or clause must not be materialized as authoritative evidence without its required
  context. Duplicate wording in different records must not be silently deduplicated.
- Bind a versioned lineage sidecar to the accepted bundle bytes/revision, source manifest and
  target contract hashes, source-set identity, full target, exact per-document KB hashes,
  record/fragment-to-Fact mapping, fragment roles, required context and document-qualified
  relations. The sidecar contains provenance and mappings, not a second store of official text.
  Review notes remain commentary in the original bundle, not official Fact text.
- Keep manual capture and Agent review explicit. No parser locator, bbox, source character
  offset, inferred official heading or fabricated parser version may be supplied. Original
  seed `fact_id`/`source_kb_sha256` remain null; derived lineage lives outside the frozen seed.
- The reviewed target indicates **coverage of the inspected slice**, not that every quoted
  clause applies identically to that target. Do not turn target membership into `global` or
  program applicability. Until separately reviewed, retain `scope_type=unknown` and empty
  targets in the derived Facts; the importer must preserve the full target in bound lineage.
  Never relabel a mixed-degree source PDF as a master's-only document.

Unknown scope and partial coverage cannot authorize public retrieval or rule execution. The
later import Spec must define truthful diagnostics for manually captured fragments (including
headers), source identities with genuine document coverage, deterministic labels/sections,
context-closure validation, and canonical bytes. A default quality pass is not production approval.
These unresolved implementation details block import release, not BUILD-01.

## Decision 3: artifact and downstream boundaries

A future build identity includes profile ID/version, mapper version, accepted bundle digest,
source/identity bindings, target/source-set contract and output schema/projection versions.
Changed input creates a distinct candidate, never an in-place replacement. Identical input must
reuse or verify the same candidate, not produce milestone-specific duplicates. The later Spec
must resolve publication layout and immutable identity before any artifact is written.

No GSFS artifact enters the current corpus/index registry in BUILD-01. Existing report validation
of document, KB hash, Fact text, pages and scope remains mandatory; a multi-source wrapper will
need its own reviewed contract. Do not concatenate source previews and call them an authoritative
report, and do not route these records through the five-item ISCT material policy.

## Sequence, consequences and rollback

1. [BUILD-01 #206](../onboarding/build-profile-isolation-spec.md): isolate the legacy profile, add the
   explicit guard and prove canonical ISCT parity. The sole released implementation.
2. Design and accept a reviewed-source import Spec, then implement the bounded 23-fragment
   candidate KB/lineage conversion. No new parser or full-document reconstruction is implied.
3. Reviewed material applicability and multi-source report evidence.
4. Bounded API/UI materials journey and real user acceptance. M15 closes only then.

This split keeps the next issue small enough for one milestone chat and two checkpoints.
It adds one explicit build boundary while deliberately retaining a documented compatibility
escape hatch. It does not promise complete multi-school support after a refactor.

Rollback BUILD-01's new module/entry and restore the old delegation; no existing asset requires
rollback or migration because none is overwritten. Preserve the 334 frozen / 391 product roles,
EVID-01 pin, MS02 parser contract, closed MinerU experiment, reference-only assistant and paused M13.
