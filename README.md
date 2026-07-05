# J-Grad Admission RAG

RAG-ready knowledge engine for Japanese graduate admission guidelines: full-document extraction,
scoped facts, vector indexing, and applicant-aware retrieval.

## What This Is

This repository is the RAG-first successor path to the profile-guided extractor experiments in
[`yasu-isct/flie-extract`](https://github.com/yasu-isct/flie-extract).

The goal is to turn Japanese graduate admission PDFs into a maintainable knowledge base that can be
queried many times by different applicants:

```text
Offline build:
PDF -> chunks -> document index -> scoped facts -> retrieval units -> document_kb.json

Online query:
student query/profile -> vector/hybrid retrieval -> reasoning chains -> answer/report
```

## Current MVP

The current implementation focuses on the offline builder:

- PyMuPDF + pdfplumber PDF extraction.
- Markdown chunking.
- Lightweight category routing.
- Document index with anchors and references.
- Reference link resolution.
- RAG-facing `document_kb.json` schema with scoped facts and retrieval units.

## Quickstart

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]

python -m jgrad_admission_rag.cli.build_kb samples\admission.pdf `
  --output outputs\kb\sample\document_kb.json
```

The generated `document_kb.json` is the handoff artifact for vector indexing and query-time
retrieval.

## Repository Layout

```text
src/jgrad_admission_rag/
  builder/      PDF extraction, chunking, document index, reference links, KB builder
  schemas/      Durable JSON contracts such as DocumentKnowledgeBase
  retrieval/    Future vector and hybrid retrieval services
  reasoning/    Future applicant-aware reasoning chains and report generation
  cli/          Command-line entry points
docs/           Architecture and migration notes
tests/          Focused unit tests
```

## Relationship To Other Repositories

- `flie-extract`: profile-guided long-document extractor for one applicant and one PDF.
- `J-Grad-Admission-RAG`: reusable admission knowledge-base builder and retrieval system.
- `Lab-Radar`: future research lab matching can consume this project's admissions knowledge layer.

## Roadmap

- Build a persistent vector index from `retrieval_units`.
- Add scoped retrieval for ambiguous queries such as "情報系" or "環境系".
- Add reasoning chains for references like "下記(1)" and conditional applicability.
- Add applicant-aware answer/report generation on top of retrieved facts.
