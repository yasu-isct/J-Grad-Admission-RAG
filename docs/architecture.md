# Architecture

J-Grad Admission RAG separates admission guideline ingestion from applicant-specific retrieval.

```text
Offline build
reviewed identity + exact PDF -> extracted pages -> chunks -> scoped facts -> document_kb.json

Online query
query/profile -> vector/hybrid retrieval -> reasoning chains -> applicant-aware answer/report
```

`DocumentIdentity` v1 is the reviewed authority for document identity and exact source version. The
KB manifest embeds it and exposes compatibility views for `document_id` and `pdf_sha256`; those
values are not duplicated in serialized output. The builder validates the actual PDF hash before
extraction. See [Document Identity v1](document-identity-v1.md).

`CorpusManifest` v1 is the explicit multi-document inventory above those individual KBs. Its
builder accepts only caller-named relative KB and optional index paths, validates KB identity and
quality, reuses local-index integrity and freshness gates, and enforces corpus-wide uniqueness. A
pure structural loader never opens artifacts; an explicit audit operation does. The catalog does
not scan directories, choose a current edition, or perform retrieval. See
[Corpus Manifest v1](corpus-manifest-v1.md).

Incremental corpus activation changes only that canonical manifest file. One explicit add or
replacement is validated in memory, written to a same-directory staging file, audited, guarded by a
final exact-byte comparison, and activated with an atomic file replace. Candidate indexes must
already exist in new validated directories; old, candidate, and unrelated artifacts are never
rewritten or deleted. See
[ADR 0004: Atomic Corpus Manifest Activation](decisions/0004-atomic-corpus-manifest-activation.md).

`CorpusVersionPolicy` keeps reviewed active/historical intent outside the inventory. Compatibility
validation requires complete exact family/document coverage of the current manifest. The pure
selector then applies explicit identity constraints, defaults to one active ready document, and
requires opt-in for historical, all-version, or multi-document selection. It reads no index files
and performs no retrieval; COR-02 audit remains the artifact gate before COR-05 consumes selected
entries. See [Corpus Version Policy v1](corpus-version-policy-v1.md).

`CorpusSearchContext` is the audited, immutable bridge from reviewed selection to cross-document
retrieval. It retains only selected ready/fresh indexes with one compatible embedding and cosine
contract. Each query embeds once, filters document-qualified rows, creates one global vector rank
and one union-corpus BM25 rank, then applies the existing RRF and scope preference policy once.
Evidence identity is `(document_id, local row, Unit ID, Fact ID)`, so repeated local IDs cannot
collide. Results are retrieval candidates, not applicant conclusions, and current-state result
revalidation is separate from structural JSON loading. See
[Corpus Retrieval v1](corpus-retrieval-v1.md).

The optional APP-01 FastAPI boundary is a thin local transport over the same contracts. Multipart
build requests stream to invocation-owned temporary storage and return a detached complete KB;
query requests reload server-owned manifest/policy state and run COR-04 then COR-05. Provider setup
belongs to lifespan, query embedding is serialized at the provider boundary, and imports remain
free of file/model/server activity. The API returns evidence candidates rather than applicant
conclusions. See [Service API v1](service-api-v1.md).

APP-02A adds a separate durable build-job boundary beneath the future asynchronous API. Strict job
records and transition history live in SQLite, while canonical identity/options, the identity-bound
PDF, and validated complete results live in UUID-derived owned directories. Explicit open acquires
one OS owner lock and performs deterministic recovery; repository transactions serialize claim,
cancel, publication, retry, and exact terminal deletion. This layer invokes neither HTTP nor the
builder. See [Durable Build Job Storage v1](service-job-storage-v1.md).

APP-02B adds an explicit bounded worker over that repository. Fixed claim loops run all repository
and builder calls off the event loop, share APP-01's response assembly, and publish only through the
repository state machine. Event-driven wakeup, deterministic cancellation checks, bounded shutdown,
and privacy-safe health are defined in [Durable Build Worker v1](service-build-worker-v1.md).

APP-02C exposes that accepted repository/worker pair through thin versioned build-job routes.
Multipart ingestion is shared with APP-01; handlers perform repository calls off-loop and translate
only typed durable outcomes. Server-owned job storage is optional and opens only during lifespan.

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

Reference expansion is a read-only, one-hop evidence layer after hybrid ranking. Freshness freezes
the validated KB into an immutable serialized snapshot; public access reparses detached copies, so
caller mutation cannot change expansion authority. Expansion validates complete
Fact/Unit/payload/diagnostic alignment before exposing any link. Only authoritative `resolved`
claims attach target evidence;
`ambiguous` and `unresolved` claims remain visible without a selected target. Attached targets are
deduplicated, preserve every incoming relation, and never alter primary ranks or scores. See
[Reference Expansion](evaluation/reference-expansion.md).

`EvidencePack` v1 is the strict boundary between retrieval and future reasoning. It validates and
canonically packages the exact request, runtime/source bindings, ordered primary evidence, resolved
one-hop attachments, and authoritative ambiguity warnings. It is a derived request snapshot, never
an answer: it contains no applicant profile, eligibility conclusion, override decision, summary, or
rendered citation. See [EvidencePack v1](evaluation/evidence-pack-v1.md).

`ApplicantProfile` v1 is the parallel, caller-supplied boundary in the `reasoning` package for M4. It models explicit target,
citizenship/residence, academic, eligibility-review, and language-result facts with required nulls
for unknowns. It has no dependency on retrieval or official evidence and cannot carry conclusions,
Fact IDs, pages, or reasoning traces. Later applicability code will compare this immutable profile
with an `EvidencePack`; neither artifact replaces the other. See
[ApplicantProfile v1](reasoning/applicant-profile-v1.md).

`QueryIntent` v1 is the other M4 input boundary. Its pure Japanese lexical parser records only
reviewed intent terms and explicit scope mentions with original offsets. The adapter maps department
and parent-college mentions to soft retrieval preferences, never parser-derived hard filters, so
global clauses remain candidates. It does not create an `ApplicantProfile`, decide applicability,
or alter retrieval ranking behavior. See [QueryIntent v1](reasoning/query-intent-v1.md).

`ApplicabilityRule` and `ApplicabilityDecision` v1 form the first deterministic M4 reasoning layer.
A small human-reviewed rule binds allowlisted typed profile predicates and explicit scope to exact
EvidencePack document/KB/PDF identity, Fact IDs, pages, and an offline-audited authoritative Fact
text hash. Online evaluation uses the validated KB identity plus Fact ID/pages; it never mistakes
the derived embedding projection for `ScopedFact.text`. Evaluation fully revalidates all inputs and
returns only `confirmed`, `not_applicable`, or `needs_information`; missing evidence and conflicting
profile/query scope fail closed. It does not infer rules from Japanese text, use retrieval scores,
order competing rules, or decide eligibility. See
[Applicability v1](reasoning/applicability-v1.md).

`RulePrecedencePolicy` and `RuleResolution` v1 add deterministic multi-rule ordering after
applicability. Specificity is a frozen validation order (`global < college < department < program`),
not an implicit winner: suppression requires a reviewed direct edge between rules assigned to the
same subject. Edges activate only when both decisions are confirmed; pending and not-applicable
rules remain visible, evidence is preserved, and ambiguous multiple overriders fail closed. This
layer neither re-evaluates predicates nor synthesizes conflicts or eligibility. See
[Rule Resolution v1](reasoning/rule-resolution-v1.md).

`RuleInteractionPolicy` and `RuleInteractionReport` v1 add reviewed interaction coverage over the
RSN-04 rules that remain active or pending. Every live same-subject pair is either reviewed as
compatible, conflict, or ambiguous, or is exposed as `unreviewed_interaction`; absence of policy is
never silently treated as compatibility. Confirmed warnings require two active endpoints, while any
pending endpoint makes the warning potential. The report embeds the validated resolution and
preserves per-rule Fact/page evidence, but neither changes dispositions nor decides eligibility.
See [Rule Interaction v1](reasoning/rule-interaction-v1.md).

`ReasoningTrace` v1 is the deterministic audit projection over those three M4 layers. It emits one
typed applicability and resolution step per reviewed rule plus one interaction step per live or
inactive reviewed pair. Explicit backward dependencies, terminal step IDs, coverage counts, and
per-rule Fact/page evidence make the path independently inspectable. The loader rebuilds the graph
from embedded, privacy-safe source snapshots and fails closed on any mismatch. It does not expose
applicant values, annotation prose, official text, hidden chain-of-thought, or final eligibility.
See [Reasoning Trace v1](reasoning/reasoning-trace-v1.md).

`CitedAnswer` v1 is the final M4 presentation projection. It converts a validated trace into
evidence-required rule findings, missing-information entries, interaction warnings, process
notices, and one canonical citation inventory, then renders fixed Japanese Markdown. Report status
means presentation readiness rather than eligibility. Every factual finding and review warning
retains exact Fact/page provenance; evidence gaps suppress the unsupported sentence. Hashes remain
machine metadata and never enter Markdown. See [Cited Answer v1](reasoning/cited-answer-v1.md).

Retrieval evaluation consumes validated EvidencePacks only after retrieval completes. It scores
exact benchmark Fact IDs against ranked primary evidence with Recall@1/3/5/10 and MRR; attached
reference-only gold is reported separately and never changes ranked credit. Empty filters and scope
preferences prevent benchmark annotations from influencing retrieval. Fake embeddings provide a
deterministic plumbing baseline but are explicitly ineligible for quality gates. See
[Retrieval Evaluation v1](evaluation/retrieval-evaluation-v1.md).

The first semantic baseline uses one externally cached, pinned BGE-M3 revision to characterize the
frozen benchmark with three byte-identical cache-only runs. It records model and artifact bindings,
primary-only metrics, and diagnostic Fact IDs without committing the model, index, PDF, or reports.
Its `quality_eligible` result is evidence for a later threshold decision, never a threshold by
itself. See [BGE-M3 Semantic Baseline](evaluation/semantic-baseline-bge-m3.md).

The semantic regression gate is a separate pure verifier over a compact report, approved policy,
and signed retrieval-affecting implementation set. It never loads a model, KB, or vector index in
CI; model-dependent re-evaluation remains an explicit offline operation. See
[ADR 0003: Semantic Retrieval Regression Gate](decisions/0003-semantic-retrieval-regression-gate.md).

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
- `reasoning`: strict applicant/query inputs, reviewed-rule applicability, and later reasoning chains.
- `cli`: command-line entry points.
- `service`: optional versioned HTTP transport, lifecycle, and runtime configuration.

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
