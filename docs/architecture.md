# Architecture

J-Grad Admission RAG separates admission guideline ingestion from applicant-specific retrieval.

```text
Offline build
PDF -> extracted pages -> chunks -> document index -> scoped facts -> diagnostics/gates -> document_kb.json

Online query
query/profile -> vector/hybrid retrieval -> reasoning chains -> applicant-aware answer/report
```

The M1-to-M2 handoff is a versioned, derived index manifest plus ordered payload rows. Payload row
`N` is the identity and provenance record for future vector row `N`; the index never replaces the
authoritative Fact. See
[ADR 0001: Derived Vector Index Contract](decisions/0001-derived-vector-index-contract.md).
The synchronous `EmbeddingProvider` boundary validates text and fixed-width vectors without a model
dependency. Its immutable `EmbeddingIdentity` maps provider, model, revision, and dimension directly
to the corresponding IDX-01 manifest fields.

Canonical embedding text is a pure, versioned projection of each authoritative `ScopedFact`.
Version `1` emits fact type, scope, section path, title, then the complete Fact text after a `text:`
marker. New Facts and RetrievalUnits record `embedding_text_version` in metadata and share the same
projection; the projection adds retrieval context but is never evidence or a replacement for Fact
text and source pages.

The local vector index is a derived three-file directory: `manifest.json`, deterministic ordered
`payloads.jsonl`, and normalized little-endian float32 `embeddings.npy`. A build writes and validates
a temporary sibling directory before one atomic rename to a new target. Loading checks the current
files' schemas, hashes, payload alignment, NumPy safety, shape, finiteness, and row norms; comparison
against a separately supplied current KB or provider belongs to the subsequent freshness gate.

`jgrad-build-index` is a thin operator boundary over that library contract. It validates one explicit
provider configuration, constructs the existing adapter, invokes the atomic builder, and reports the
validated manifest as one JSON object. It has no independent embedding, serialization, overwrite,
search, or stale-index logic. The deterministic fake option is pipeline-only and non-semantic;
Sentence Transformers remains pinned, CPU-only, and offline unless download is explicitly enabled.

Vector search loads that validated index read-only, checks the complete provider identity, obtains a
checked query embedding, and performs exhaustive NumPy cosine ranking. Scores descend and exact ties
use ascending payload row index, so repeated runs are deterministic. Returned hits are immutable,
detached views of the aligned payload row, including scope and official page provenance. This layer
retrieves evidence candidates only; the freshness gate owns stale-input checks, while applicant
applicability and answer composition remain later reasoning layers.

Lexical retrieval is a parallel candidate generator over the same ordered payload rows. A versioned,
dependency-free tokenizer applies Unicode normalization, preserves numeric and Latin identifiers,
and emits overlapping Japanese 2/3-grams. Fixed-constant BM25 scoring sorts by descending score and
ascending row index, excludes zero-score rows, and returns detached evidence with Fact identity and
page provenance. It does not fuse vector results or decide applicant applicability. See
[Lexical Retrieval](evaluation/lexical-retrieval.md).

Hybrid retrieval runs vector and lexical candidate generation over one validated index, then uses
equal-weight Reciprocal Rank Fusion over their ranks. Version `rrf-v1` never compares or combines the
raw cosine and BM25 scores. The union remains auditable through per-channel rank and score fields,
while final evidence is rebuilt from the aligned payload row. Vector mode remains the public CLI
default until semantic evaluation establishes a quality gate. See
[Hybrid Retrieval](evaluation/hybrid-retrieval.md).

Metadata-aware retrieval is an explicit opt-in layer around hybrid retrieval. Exact hard filters
derive eligible payload rows before either channel truncates candidates; exact target/college
preferences then add fixed, named bonuses to the complete fused candidate union. It never parses
scope from the query or infers fields absent from the durable payload. See
[Metadata Retrieval](evaluation/metadata-retrieval.md).

Freshness is a separate read-only gate after self-integrity and before model activity. It hashes the
exact current KB bytes once, validates that KB, then compares the KB hash, document/PDF provenance,
and declared provider/model/revision/dimension with the index manifest. Only a fresh comparison may
construct the runtime provider; vector search still rechecks the actual runtime identity. See
[ADR 0002: Index Freshness And Replacement Policy](decisions/0002-index-freshness-and-replacement.md).
Stale indexes are rebuilt to a new absent directory and activated by switching the caller path;
automatic overwrite, deletion, and directory swapping are outside the supported safety contract.

## Current MVP

The first migrated slice builds `document_kb.json` from a source PDF. It reuses the stable extraction,
chunking, lightweight document index, reference resolver, and recursive retrieval primitives from
`flie-extract`, but wraps them in a RAG-oriented schema.

## Main Boundaries

- `builder`: PDF extraction, chunking, index construction, reference links, and KB building.
- `schemas`: durable JSON contracts such as `DocumentKnowledgeBase`.
- `retrieval`: embedding provider contracts plus future vector and hybrid retrieval services.
- `reasoning`: future applicant-aware reasoning chains and report generation.
- `cli`: command-line entry points.

## Knowledge And Diagnostics

`ScopedFact` is the authoritative extracted knowledge. `BuildDiagnostics` is a deterministic
observation of the completed build: it lists structural problems by Fact ID, classifies each unique
reference claim, records the active thresholds, and stores the resulting quality gate. Diagnostics
never rewrite Fact text, source pages, section paths, or scope.

Reference links are emitted only for `resolved` claims. `ambiguous` and `unresolved` claims remain
in diagnostics with their candidate Fact IDs and scores, so uncertainty is visible rather than
hidden behind a sorting tie-break.

## Why This Split

The old profile-guided pipeline is useful for single-applicant extraction. This repository is for a
maintainable admission knowledge base: build once per guideline PDF, index the facts, and answer many
different student queries against the same prepared knowledge.
