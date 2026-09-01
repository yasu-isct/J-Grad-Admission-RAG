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
PDF -> chunks -> document index -> scoped facts -> diagnostics/gates -> document_kb.json

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
- Claim-level reference diagnostics and optional structural quality gates.

## Quickstart

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]

python -m jgrad_admission_rag.cli.build_kb samples\admission.pdf `
  --output outputs\kb\sample\document_kb.json
```

The generated `document_kb.json` is the handoff artifact for vector indexing and query-time
retrieval. It also contains a `diagnostics` section with traceable Fact IDs, reference claims,
the active quality thresholds, and their gate result. A failed enabled gate still writes the
artifact and makes the CLI exit with code `2` so the evidence can be inspected.

## Sentence Transformers Adapter

Install the optional model runtime separately with `python -m pip install -e .[embedding]`. The
adapter requires an explicit model name, an exact 40-character revision commit, and expected output
dimension. It is CPU-only, uses `trust_remote_code=False`, and defaults to cache-only loading; model
downloads occur only when a caller explicitly sets `allow_download=True`.

`BAAI/bge-m3` is the provisional M2 baseline because its official model card describes multilingual
1,024-dimensional embeddings and an 8,192-token input length. It is comparatively resource-heavy
and has not yet been proven best for Japanese admission retrieval; M3 evaluation will revisit the
choice. BGE-M3 receives the canonical text unchanged, with no query/document prefix or prompt.

Sentence Transformers normally truncates text beyond the model limit. This adapter tokenizes every
input with truncation disabled before encoding and raises `EmbeddingInputError` if any row is too
long. It never silently truncates, summarizes, or splits official content. See the
[BGE-M3 model card](https://huggingface.co/BAAI/bge-m3) and
[Sentence Transformers embedding documentation](https://www.sbert.net/examples/sentence_transformer/applications/computing-embeddings/README.html).
Constructor and encode options are documented in the
[SentenceTransformer API reference](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).

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

Development is organized as small, verifiable GitHub issues grouped by milestones. The current
priority is to make `document_kb.json` traceable and diagnostically reliable before adding vector
indexing.

See [docs/roadmap.md](docs/roadmap.md) for milestones, task IDs, acceptance gates, and the project
workflow.
