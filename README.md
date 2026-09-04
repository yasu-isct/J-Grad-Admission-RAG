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
reviewed identity + exact PDF -> chunks -> scoped facts -> diagnostics/gates -> document_kb.json

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
  --identity samples\admission.identity.json `
  --output outputs\kb\sample\document_kb.json
```

The generated `document_kb.json` is the handoff artifact for vector indexing and query-time
retrieval. It also contains a `diagnostics` section with traceable Fact IDs, reference claims,
the active quality thresholds, and their gate result. A failed enabled gate still writes the
artifact and makes the CLI exit with code `2` so the evidence can be inspected.

The required identity file is reviewed metadata, not extracted data. It binds one exact PDF hash to
an institution, document family, edition, degree coverage, and intake terms. The builder verifies
the hash before extraction and never infers these fields from a filename or title. See
[Document Identity v1](docs/document-identity-v1.md).

Multiple validated KBs can be assembled through the explicit `CorpusManifest` API. The manifest is
an immutable inventory of exact document identities, KB-byte hashes, and optional validated fresh
indexes; it does not scan folders or choose a current edition. See
[Corpus Manifest v1](docs/corpus-manifest-v1.md).

Reviewed active/historical policy can select one or several exact ready editions, after which the
library-level corpus search path audits those artifacts and builds an immutable in-memory context.
Each query uses one embedding plus corpus-global vector, BM25, RRF, and scope-preference ranking;
every candidate remains qualified by document identity and official page provenance. It does not
merge index files or make eligibility decisions. See
[Corpus Retrieval v1](docs/corpus-retrieval-v1.md).

## Run The Local API

The optional APP-01 service exposes the accepted build and corpus-query workflows without adding a
second implementation:

```powershell
python -m pip install -e ".[service]"
jgrad-serve `
  --corpus-root D:\corpus `
  --manifest D:\corpus\corpus.json `
  --policy D:\corpus\policy.json `
  --provider deterministic-fake `
  --dimension 8
```

OpenAPI is served at `http://127.0.0.1:8000/openapi.json`, with local interactive docs at
`http://127.0.0.1:8000/docs`. The API provides `/v1/health/live`, `/v1/health/ready`, synchronous
multipart KB build, and strict reviewed-corpus query routes. See [Service API v1](docs/service-api-v1.md).

The default bind is loopback and real model loading is cache-only unless download is explicitly
authorized. The service has no authentication, TLS, rate limiting, or public-deployment hardening;
do not expose it directly to a network. Use an authenticated reverse proxy and a separate
operational review before any non-loopback deployment.

After initializing a canonical manifest through the library builder, activate one prepared KB/index
registration without touching other artifacts:

```powershell
jgrad-update-corpus D:\corpus\corpus.json `
  --corpus-root D:\corpus `
  --action add `
  --kb isct/2028/document_kb.json `
  --index indexes/isct-2028
```

Registration paths are POSIX relative paths, so use `/` inside `--kb` and `--index` even on Windows.
`replace` additionally requires `--replace-document-id`. The command validates and audits before
atomically replacing only the manifest file; it never builds or deletes an index. See
[ADR 0004](docs/decisions/0004-atomic-corpus-manifest-activation.md).

Before cross-document retrieval, a separate reviewed `CorpusVersionPolicy` must classify every
manifest document as active or historical. Selection requires a positive identity constraint and
defaults to one active, ready document; historical, all-version, and multi-document use are explicit
opt-ins. The selector reads no index files and performs no ranking. See
[Corpus Version Policy v1](docs/corpus-version-policy-v1.md).

## Build A Local Index

The deterministic fake provider verifies the indexing pipeline without downloading a model. Its
vectors are reproducible but non-semantic and must not be used to judge retrieval quality:

```powershell
python -m pip install -e .
jgrad-build-index outputs\kb\sample\document_kb.json `
  --output outputs\index\sample-fake `
  --provider deterministic-fake `
  --dimension 8
```

For real multilingual embeddings, install the optional runtime and name an exact model revision.
The default is offline/cache-only; `--allow-model-download` is an explicit network and disk-use
permission and should be used only after reviewing the model and revision:

```powershell
python -m pip install -e .[embedding]
jgrad-build-index outputs\kb\sample\document_kb.json `
  --output outputs\index\sample-bge-m3 `
  --provider sentence-transformers `
  --model BAAI/bge-m3 `
  --revision <40-character-commit-sha> `
  --dimension 1024 `
  --batch-size 8 `
  --cache-folder .cache\models
```

The output directory must not already exist; the command never overwrites or deletes an index. A
successful build contains `manifest.json`, `payloads.jsonl`, and `embeddings.npy`, then prints one
JSON summary with counts, provider identity, and artifact hashes. The `jgrad-search` command below
queries the index after the IDX-08 freshness checks and safe replacement policy described below.

## Search A Local Index

Search uses exhaustive NumPy cosine similarity over the validated, normalized index. Higher scores
rank first; exact ties use the lower payload `row_index`. `--top-k` defaults to `5`, and requesting
more rows than exist simply returns every row. The command is read-only and emits one JSON object
whose results retain the payload text, Fact/Unit IDs, scope, section path, and official PDF pages.

Use the exact provider identity that built the index. This fake example is deterministic and useful
only for checking ranking and provenance plumbing, not semantic relevance:

```powershell
jgrad-search outputs\index\sample-fake `
  --current-kb outputs\kb\sample\document_kb.json `
  --query "出願資格" `
  --top-k 5 `
  --provider deterministic-fake `
  --dimension 8
```

A real index built with Sentence Transformers must be searched with the same model, pinned revision,
and dimension. Loading is cache-only unless download is explicitly authorized:

```powershell
jgrad-search outputs\index\sample-bge-m3 `
  --current-kb outputs\kb\sample\document_kb.json `
  --query "情報工学系の出願資格" `
  --provider sentence-transformers `
  --model BAAI/bge-m3 `
  --revision <same-40-character-commit-sha> `
  --dimension 1024 `
  --cache-folder .cache\models
```

`--current-kb` is required. Search first validates index integrity, then compares the exact current KB
bytes, document/PDF provenance, and declared provider/model/revision/dimension with the manifest. A
fresh result includes the current KB SHA-256 and checked fields. `stale_index` means the index is
internally valid but no longer matches one or more current inputs; `current_kb_error` means the
current KB itself is missing, symlinked, malformed, unsupported, or failed its quality gate.

Stale indexes are never replaced automatically. Build a replacement into a new absent directory,
validate it, switch the caller/configuration to that path, and retire the old directory separately.
Automatic overwrite, delete, or directory swapping is deliberately absent because portable atomic
replacement and crash recovery require a separate design. See
[ADR 0002](docs/decisions/0002-index-freshness-and-replacement.md).

Returned rows are retrieval candidates, not applicant-specific decisions or final answers. Later
milestones add profile-aware reasoning and reporting.

The benchmark evaluator produces a strict diagnostic report over the exact declared queries:

```powershell
jgrad-evaluate-retrieval outputs\index\sample-bge-m3 `
  --current-kb outputs\kb\sample\document_kb.json `
  --benchmark tests\fixtures\retrieval_queries_v1.json `
  --provider sentence-transformers `
  --model BAAI/bge-m3 `
  --revision <same-40-character-commit-sha> `
  --dimension 1024 `
  --cache-folder .cache\models
```

It runs cache-only hybrid retrieval with empty filters and preferences, then reports primary-only
Recall@1/3/5/10, MRR, breakdowns, and missing-gold diagnostics. Fake embeddings validate plumbing
but are never quality-eligible. See
[Retrieval Evaluation v1](docs/evaluation/retrieval-evaluation-v1.md).

## Semantic Regression Gate

The checked-in semantic gate verifies the reviewed RET-08 baseline without loading a model, KB, or
vector index. It binds the compact report, frozen benchmark, BGE-M3 identity, retrieval metrics,
and signed retrieval-affecting source set. It is the CI guard for retrieval changes, not a replacement
for a new semantic evaluation when the benchmark or intended behavior changes:

```powershell
jgrad-check-retrieval-gate `
  --report tests\fixtures\semantic_retrieval_baseline_v1.json `
  --policy config\semantic_retrieval_gate_v1.json `
  --manifest config\semantic_retrieval_gate_manifest_v1.json `
  --repository-root .
```

Exit code `0` means the frozen baseline satisfies policy, `1` means a measured policy failure, and
`2` means an unsafe or malformed input/contract. The command is cache-free and CI sets Hugging Face
and Transformers to offline mode. See
[ADR 0003](docs/decisions/0003-semantic-retrieval-regression-gate.md).

Hybrid retrieval is opt-in while evaluation thresholds are still being established. It combines
vector and lexical ranks with fixed Reciprocal Rank Fusion and leaves the default vector response
unchanged:

```powershell
jgrad-search outputs\index\sample-bge-m3 `
  --current-kb outputs\kb\sample\document_kb.json `
  --query "情報工学系のTOEFL提出条件" `
  --retrieval-mode hybrid `
  --candidate-k 50 `
  --provider sentence-transformers `
  --model BAAI/bge-m3 `
  --revision <same-40-character-commit-sha> `
  --dimension 1024 `
  --cache-folder .cache\models
```

Hybrid output reports `rrf-v1`, `RRF_K=60`, candidate depths, channel counts, and each hit's vector
and lexical provenance. See [the hybrid retrieval contract](docs/evaluation/hybrid-retrieval.md).

Explicit metadata constraints and scope preferences are available only in hybrid mode. For example,
this request keeps exact `english` Facts and then prefers exact Information Engineering scope:

```powershell
jgrad-search outputs\index\sample-bge-m3 `
  --current-kb outputs\kb\sample\document_kb.json `
  --query "英語スコアの提出条件" `
  --retrieval-mode hybrid `
  --filter-fact-type english `
  --prefer-scope-target 情報工学系 `
  --prefer-parent-college 情報理工学院 `
  --provider sentence-transformers `
  --model BAAI/bge-m3 `
  --revision <same-40-character-commit-sha> `
  --dimension 1024 `
  --cache-folder .cache\models
```

Matching is exact and caller-supplied; the command does not infer department, college, degree, year,
or intake from the question. See [the metadata retrieval contract](docs/evaluation/metadata-retrieval.md).

Authoritative one-hop references can also be expanded in hybrid mode. This preserves the ranked
`results` array and adds a separate `reference_expansion` object containing resolved target evidence
plus visible ambiguous and unresolved diagnostics:

```powershell
jgrad-search outputs\index\sample-bge-m3 `
  --current-kb outputs\kb\sample\document_kb.json `
  --query "主な出願資格の下記（3）の条件" `
  --retrieval-mode hybrid `
  --expand-references `
  --provider sentence-transformers `
  --model BAAI/bge-m3 `
  --revision <same-40-character-commit-sha> `
  --dimension 1024 `
  --cache-folder .cache\models
```

Only builder-resolved targets become evidence. Ambiguous and unresolved claims are reported without
guessing, and expansion never changes primary ranks or recursively follows the attached target. See
[the reference expansion contract](docs/evaluation/reference-expansion.md).

For a stable downstream handoff, hybrid search can emit a canonical `EvidencePack` v1 instead of the
operator-oriented search summary. Reference expansion is included automatically:

```powershell
jgrad-search outputs\index\sample-bge-m3 `
  --current-kb outputs\kb\sample\document_kb.json `
  --query "情報工学系の出願資格" `
  --retrieval-mode hybrid `
  --output-format evidence-pack `
  --provider sentence-transformers `
  --model BAAI/bge-m3 `
  --revision <same-40-character-commit-sha> `
  --dimension 1024 `
  --cache-folder .cache\models
```

The pack preserves full official evidence and retrieval diagnostics, but makes no applicant-specific
decision and generates no answer. See [the EvidencePack v1 contract](docs/evaluation/evidence-pack-v1.md).

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
  retrieval/    Embedding providers, local vector indexes, and future retrieval services
  reasoning/    Applicant/query contracts, reviewed applicability rules, later reasoning
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
