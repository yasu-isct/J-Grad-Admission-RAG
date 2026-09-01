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
against a separately supplied current KB or provider remains a later stale-index concern.

`jgrad-build-index` is a thin operator boundary over that library contract. It validates one explicit
provider configuration, constructs the existing adapter, invokes the atomic builder, and reports the
validated manifest as one JSON object. It has no independent embedding, serialization, overwrite,
search, or stale-index logic. The deterministic fake option is pipeline-only and non-semantic;
Sentence Transformers remains pinned, CPU-only, and offline unless download is explicitly enabled.

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
