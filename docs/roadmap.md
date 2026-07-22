# Project Roadmap

This document is the planning source of truth for J-Grad Admission RAG. GitHub Issues represent
work that is ready or active; future work stays here until the preceding milestone is close to
completion.

## Product Goal

Given a Japanese graduate admission guideline PDF, the system should build a maintainable knowledge
base, retrieve applicable evidence for a query and applicant profile, and produce an answer whose
claims can be traced to source pages.

```text
PDF -> document_kb.json -> local indexes -> evidence pack -> applicability reasoning -> answer
```

## Engineering Boundaries

- `ScopedFact` is the authoritative domain fact and must remain source-traceable.
- `RetrievalUnit` is a rebuildable search projection, not the source of truth.
- Index artifacts are derived from `document_kb.json` and may be deleted and rebuilt safely.
- Retrieval returns evidence; reasoning determines applicability; output code formats the result.
- External embedding and storage implementations sit behind small interfaces.
- Complexity is added only after a regression test or evaluation demonstrates the need.

## Milestones

| Milestone | Release | Demonstrable outcome | Exit gate |
| --- | --- | --- | --- |
| M1 Trusted knowledge base | v0.2 | A real guideline builds into inspectable, traceable facts | All facts have pages; chunk and reference problems are diagnosed |
| M2 Local vector retrieval | v0.3 | A CLI query returns relevant text, scope, and pages | Deterministic index build and search tests pass |
| M3 Evaluated hybrid retrieval | v0.4 | Retrieval quality is measured and regression-tested | Curated queries meet agreed Recall@K and MRR thresholds |
| M4 Applicant-aware reasoning | v0.5 | The system explains whether a rule applies to a profile | Conclusions include status, evidence, and missing information |
| M5 Multi-document corpus | v0.6 | Multiple schools, years, and programs can coexist safely | Version and document filters prevent accidental mixing |
| M6 Usable service | v1.0 | API and report output expose the complete workflow | End-to-end scenarios are reproducible and observable |

## Current Sprint: M1 Trusted Knowledge Base

The first real-PDF review produced 382 facts and 382 retrieval units from an 85-page guideline. It
also found missing page metadata on 216 facts, chunks ranging from nearly empty to 8,754 characters,
and reference links that can confuse repeated numbering across sections.

| ID | Task | Acceptance signal | Size | Dependency |
| --- | --- | --- | --- | --- |
| KB-01 | Add a real admission PDF regression fixture | Offline test covers headings, tables, scopes, and references | M | None |
| KB-02 | Preserve source pages across chunk boundaries | Zero non-synthetic facts without source pages | M | KB-01 |
| KB-03 | Add hierarchical section paths | Facts and retrieval units retain parent and child headings | M | KB-02 |
| KB-04 | Remove empty and non-informative chunks | No page-only or heading-only facts; drops are diagnosed | S | KB-01 |
| KB-05 | Enforce explainable chunk size limits | Normal chunks obey limits; exceptions are explicit | M | KB-03, KB-04 |
| KB-11 | Add knowledge-build quality diagnostics | CLI and JSON report structural quality counts | M | KB-02, KB-04, KB-05 |

M1 is complete when:

- Every non-synthetic fact has a source page and section path.
- No fact consists only of a page marker, whitespace, or an isolated heading.
- Oversized chunks are split or explicitly reported.
- References are classified as `resolved`, `unresolved`, or `ambiguous`.
- Rebuilding the same fixture produces stable identifiers and counts.
- `pytest`, `ruff check . --no-cache`, and `compileall` pass.

## Planned Backlog

### M2 Local Vector Retrieval

| ID | Task | Output |
| --- | --- | --- |
| IDX-01 | Define index schemas and compatibility manifest | Versioned `IndexManifest` and payload schema |
| IDX-02 | Define the embedding provider interface | Real and deterministic fake providers |
| IDX-03 | Build retrieval-unit embedding text | Documented, testable projection rules |
| IDX-04 | Implement a multilingual embedding adapter | Configurable Japanese-capable embeddings |
| IDX-05 | Implement the local NumPy index | `embeddings.npy`, `payloads.jsonl`, and manifest |
| IDX-06 | Add `build_index` CLI | Rebuildable index artifact from `document_kb.json` |
| IDX-07 | Add vector search and `search` CLI | Top-k evidence with scores, scopes, and pages |
| IDX-08 | Add stale-index detection and tests | Clear failure when KB or model configuration changes |

Start with NumPy cosine search. Introduce FAISS or a service-backed vector store only when corpus
size or measured latency requires it.

### M3 Evaluated Hybrid Retrieval

| ID | Task | Output |
| --- | --- | --- |
| RET-01 | Curate admission retrieval queries | At least 30 questions with relevant fact IDs |
| RET-02 | Add lexical retrieval | Exact matching for names, dates, tests, and form numbers |
| RET-03 | Fuse vector and lexical results | Deterministic ranked candidate list |
| RET-04 | Add metadata filters and scope boosts | Degree, college, department, year, and fact-type controls |
| RET-05 | Expand references from candidates | Related clauses included with link status |
| RET-06 | Define `EvidencePack` | Stable retrieval-to-reasoning contract |
| RET-07 | Add evaluation CLI and CI thresholds | Recall@K, MRR, and readable failure cases |

### M4 Applicant-Aware Reasoning

| ID | Task | Output |
| --- | --- | --- |
| RSN-01 | Define `ApplicantProfile` | Structured profile with explicit unknown values |
| RSN-02 | Parse query intent and requested scope | Query model consumed by retrieval |
| RSN-03 | Check fact applicability | `confirmed`, `not_applicable`, or `needs_information` |
| RSN-04 | Apply specificity and override rules | Department rules can override general rules transparently |
| RSN-05 | Detect conflicts and ambiguity | Structured warnings with supporting facts |
| RSN-06 | Record reasoning traces | Each conclusion links to facts and pages |
| RSN-07 | Build cited answers and scenario tests | Applicant-aware answers over representative cases |

### M5 Multi-Document Corpus

| ID | Task | Output |
| --- | --- | --- |
| COR-01 | Define document identity and versioning | School, year, degree, intake, and source hash |
| COR-02 | Add a corpus manifest | Inventory of all knowledge bases and index state |
| COR-03 | Build incremental indexing | Add or replace one document without a full rebuild |
| COR-04 | Filter active and historical versions | Queries do not mix incompatible guidelines by default |
| COR-05 | Add cross-document retrieval tests | Safe comparison across schools and programs |

### M6 Usable Service

| ID | Task | Output |
| --- | --- | --- |
| APP-01 | Expose build and query APIs | Stable request, response, and error contracts |
| APP-02 | Add job status and operational diagnostics | Observable long-running document builds |
| APP-03 | Generate cited applicant reports | Natural-language output derived from reasoning results |
| APP-04 | Add a focused evidence-review interface | Search, profile input, evidence, and report views |

## GitHub Workflow

Use the project states `Backlog`, `Ready`, `In Progress`, `Review`, and `Done`.

- Keep no more than two implementation issues in `In Progress`.
- Split work larger than two focused development days before moving it to `Ready`.
- Create issues for the next milestone only when the current milestone approaches its exit gate.
- Use dependencies in issue bodies instead of relying on issue order.
- Close an issue only after its verification commands and documentation updates are complete.
- Record material architecture decisions in `docs/` and link them from the relevant issue.

Recommended labels:

```text
area:builder     area:schema       area:indexing
area:retrieval   area:reasoning    area:docs        area:tests
priority:p0      priority:p1       priority:p2
size:S           size:M            size:L
type:feature     type:bug          type:quality     type:research
```

## Definition of Done

Every implementation issue must satisfy all applicable items:

- Acceptance criteria are checked and observable.
- Focused tests cover the changed behavior and relevant failure modes.
- Existing tests and lint checks pass.
- Public schemas, CLI behavior, and generated artifacts are documented.
- Generated data remains traceable to its input document.
- No unrelated refactor or dependency is included.
- The pull request links the issue and explains validation performed.

## Planning Policy

The roadmap describes direction, while Issues describe executable work. Milestones are reviewed at
their exit gate; priorities may change based on real-PDF diagnostics and retrieval evaluation, but
the layer boundaries above should remain stable unless an architecture decision documents why.
