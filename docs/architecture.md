# Architecture

J-Grad Admission RAG separates admission guideline ingestion from applicant-specific retrieval.

```text
Offline build
PDF -> extracted pages -> chunks -> document index -> scoped facts -> retrieval units -> document_kb.json

Online query
query/profile -> vector/hybrid retrieval -> reasoning chains -> applicant-aware answer/report
```

## Current MVP

The first migrated slice builds `document_kb.json` from a source PDF. It reuses the stable extraction,
chunking, lightweight document index, reference resolver, and recursive retrieval primitives from
`flie-extract`, but wraps them in a RAG-oriented schema.

## Main Boundaries

- `builder`: PDF extraction, chunking, index construction, reference links, and KB building.
- `schemas`: durable JSON contracts such as `DocumentKnowledgeBase`.
- `retrieval`: future vector and hybrid retrieval services.
- `reasoning`: future applicant-aware reasoning chains and report generation.
- `cli`: command-line entry points.

## Why This Split

The old profile-guided pipeline is useful for single-applicant extraction. This repository is for a
maintainable admission knowledge base: build once per guideline PDF, index the facts, and answer many
different student queries against the same prepared knowledge.
