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
- `DocumentIdentity` is reviewed input and the sole authority for document and exact-PDF identity.
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

## Current Sprint: M5 Multi-Document Corpus

M1 through M4 are complete. M5 first gives every exact guideline edition reviewed identity, then
builds an explicit corpus inventory above those independently validated KBs and indexes. COR-02
records `ready` and `not_indexed` entries without scanning directories, mixing payload rows, or
selecting an active edition. COR-03 and COR-04 will add controlled updates and version selection on
top of that stable inventory.

### Completed M4 Summary

RSN-02 added the complementary query boundary: a reviewed, conservative Japanese lexical catalog
records explicit question intent and maps explicit scope only to existing soft retrieval
preferences. It deliberately does not extract applicant facts, hide global evidence with hard
filters, or decide rule applicability.

RSN-03 adds the first executable reasoning boundary. Human-reviewed, evidence-hash-bound rules can
now compare allowlisted profile fields and explicit scope with retrieved primary or attached
evidence. The result is deliberately limited to three-valued rule applicability; rule priority,
conflict synthesis, eligibility conclusions, and answer prose remain later tasks.

RSN-04 orders those independently evaluated rules with a reviewed precedence policy. A narrower
scope validates a direct override edge but never creates one; both endpoints must be confirmed,
pending and not-applicable results stay visible, and evidence survives unchanged. The output is a
deterministic resolution artifact, not a conflict or eligibility conclusion.

RSN-05 inspects every active/pending same-subject pair left by RSN-04 against an explicit reviewed
interaction policy. Compatible pairs are covered without warning; reviewed conflict/ambiguity and
unreviewed pairs remain structured, evidence-carrying results. This layer exposes incomplete review
and potential interactions without changing a rule or synthesizing final eligibility.

RSN-06 projects all three validated artifacts into one canonical audit graph. Every rule and policy
pair becomes a typed step with backward dependencies and exact Fact/page provenance; independent
loading recomputes graph topology, terminal steps, counts, and completeness. The trace deliberately
stops before answer prose or final eligibility, giving RSN-07 a narrow, inspectable input boundary.

RSN-07 renders that validated trace as strict cited rule findings and fixed Japanese Markdown.
`complete`, `needs_information`, and `needs_review` describe report readiness only. Every factual
sentence requires exact Fact/page evidence, while pending inputs, missing evidence, and unresolved
interactions remain explicit. This completes M4's reasoning-to-presentation slice without adding a
final eligibility verdict or model-generated prose.

The current 85-page real-PDF baseline produces 298 traceable, informative, size-bounded Facts and
RetrievalUnits. KB-11 observes 141 unique reference claims: 7 resolved, 6 ambiguous, and 128
unresolved. These known scope/reference debts are reported by default and can be promoted to
enforced thresholds when the project is ready to require them.

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
| RET-07 | Add deterministic retrieval evaluation | Recall@K, MRR, breakdowns, and readable diagnostics |
| RET-08 | Capture a pinned semantic baseline | Three cache-only BGE-M3 runs and reviewed failures |
| RET-09 | Define semantic threshold and CI policy | Approved tolerances, signed implementation contract, and offline regression gate |

RET-07 establishes a reproducible evaluator and report contract without inventing semantic quality
thresholds. RET-08 records one accepted semantic characterization. RET-09 may define regression
tolerances and CI policy only after reviewing that evidence.

### M4 Applicant-Aware Reasoning

| ID | Task | Output |
| --- | --- | --- |
| RSN-01 | Define `ApplicantProfile` | Structured profile with explicit unknown values |
| RSN-02 | Parse query intent and requested scope | Query model consumed by retrieval |
| RSN-03 | Check fact applicability | Reviewed, evidence-bound three-valued decision contract |
| RSN-04 | Apply specificity and override rules | Department rules can override general rules transparently |
| RSN-05 | Detect conflicts and ambiguity | Structured warnings with supporting facts |
| RSN-06 | Record reasoning traces | Each conclusion links to facts and pages |
| RSN-07 | Build cited answers and scenario tests | Applicant-aware answers over representative cases |

### M5 Multi-Document Corpus

| ID | Task | Output |
| --- | --- | --- |
| COR-01 | Define document identity and versioning | School, year, degree, intake, and source hash |
| COR-02 | Add a corpus manifest | Inventory of all knowledge bases and index state |
| COR-03 | Add atomic corpus updates | Add or replace one registration without rebuilding indexes |
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
