# MS-01: GSFS target, source-set and v1 compatibility contract

Status: accepted design boundary for the first slice; candidate additive implementation contracts.
Owner: design main under [#195](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/195).
Reviewed against main `01919c3aa53c02ea65d220bbe609125bc99a723b`, 2026-09-27.
This document enables no production target and changes no existing schema or artifact.

## 1. Concrete target and support boundary

The user confirmed 2027 master's ordinary general selection, examination A, April 2027 intake.
The repository-owned identifiers below are design identifiers, not identifiers issued by UTokyo.

| Dimension | Fixed value | Meaning |
| --- | --- | --- |
| institution_id | `utokyo` | 東京大学 |
| organization_id | `utokyo-gsfs` | 新領域創成科学研究科 |
| program_id | `utokyo-gsfs-complex` | 複雑理工学専攻 |
| degree_level | `master` | Master's, not doctoral |
| admission_cycle | `2027` | Admission edition, not the calendar year of every exam event |
| selection_route_id | `general-ordinary` | Department's ordinary general selection; excludes special oral selection |
| examination_schedule_id | `A` | Separate from route, citizenship and intake |
| intake | `{year: 2027, month: 4}` | Selected admission month |
| target_id | `utokyo-gsfs-complex-master-2027-general-a-202704` | Opaque catalog key for precisely this combination |

Display labels and translations can change without changing identity. Common documents group
special oral selection within general selection; that broad label must not erase the department's
separate workflow. `general-ordinary` is the reviewed application mapping, not an assertion that
the university has a universally shared route taxonomy. A future special-oral-to-general carryover
case needs its own reviewed workflow; the ordinary June application window must not be applied to
that case automatically. Optional program participation (for example fusion) is a separate scope.

The catalog initially contains exactly this one GSFS design target, disabled until downstream
acceptance. It does not generate a Cartesian product of PDF metadata. The 2026 examination is a
historical regression sample, even though its admission cycle is 2027. Personal nationality,
residence, employment and previous application history are applicant facts, not target IDs.

## 2. Exact multi-source binding

The companion [examples](gsfs-source-set-contract-v0.1.examples.json) bind the target to source-set
`utokyo-gsfs-complex-master-2027-general-a-202704-s1`. Each member repeats the exact SHA-256 from the
[source lock](utokyo-gsfs-complex-2027.sources.json); acquisition aliases alone are not immutable
identities. An exact document key is `(source_id, source_pdf_sha256)`. Future runtime document IDs
must resolve one-to-one to that key; do not attach a new PDF revision to an existing active ID.

| Acquisition source_id | Family / edition | Role and necessity |
| --- | --- | --- |
| `gsfs-master-2027` | `utokyo-gsfs-master-guidelines` / `2027` | Required common rules; 22 physical pages |
| `complex-guide-2027-revised` | `utokyo-gsfs-complex-guide` / `2027` | Required department details; 45 pages, also contains excluded routes/degrees |
| `complex-master-a-additional` | `utokyo-gsfs-complex-master-a-additional` / `2027` | Required complementary materials table; 1 page |
| `gsfs-overseas-intake-a-20260305` | `utokyo-gsfs-intake-a-flowchart` / `2027` | Conditional intake reference; 15 pages, not an eligibility rulebook |

All four sources are acquired and frozen. A source-set revision freezes membership, roles and
reviewed coverage as well as bytes. A corrected PDF or changed membership creates `s2` plus an
explicit review; it does not overwrite `s1`. Revision dates remain unknown unless explicitly
established from an official source; filename suffixes and HTTP Last-Modified are not proof.
The common and department guides are complementary families, not competing editions.

Required core member missing/unreadable/hash-mismatched: target bundle unavailable; do not silently
serve a partial admissions report. A missing conditional reference blocks conclusions depending
on it; unrelated core conclusions may remain available with explicit partial coverage. Unknown
applicant conditions must not be interpreted as making a conditional source unnecessary. The
complete declared `s1` source inventory is still reported, including unavailable members.

The intake FAQ is consulted for relevant intake questions, with the common guideline and department
intake clause. Its graph/footnotes are not converted into an immigration or eligibility decision in
this slice. Unreviewed branches, residence changes and externally referenced FAQ details yield
`not_covered` or `needs_information`. All documents are visible for evidence review; visibility is
not permission for every contained paragraph to enter ordinary-admission retrieval.

## 3. Rule coverage and conflict semantics

Scope is a reviewed relation among target, exact source, bound span/Fact, purpose and any applicant
predicate. It is external to legacy KB bytes. Common means common within the declared GSFS target
coverage, never across institutions. Ancestor coverage must be explicitly enumerated or bounded by
a reviewed organization relation; a missing scope is not an unrestricted wildcard.

Before **both** BM25 and vector ranking, resolve the source-set and identical document-qualified
eligible Fact IDs. Include reviewed common clauses and relevant appendices. A mixed Fact that also
contains excluded routes is withheld until a reviewed bound span or a new correctly segmented Fact
exists. Page allowlists alone cannot establish eligibility. Reference expansion obeys the same scope.

Relations between clauses are reviewed as `delegates_to`, `supplements`, `corroborates`,
`reference_only`, or an explicit evidence-bound `overrides` edge. No automatic department-wins or
newest-file-wins rule is introduced. Contradictory obligations for the same subject/scope without a
reviewed resolution yield `unresolved_conflict` with both citations; withhold the affected conclusion.
Independent, verified conclusions can still be shown with the conflict and coverage limitation.

The following are source-grounded design examples, not activated rules or a complete application
checklist. Physical-page references were checked against the exact PDFs, including page images.

| Case | Exact sources and physical pages | Interpretation / acceptance expectation |
| --- | --- | --- |
| Scope foundation | Common p.2; department p.28 (printed 26) | Common document directs readers to department details; selected normal intake is April 2027. October clause on the same department page is not part of the selected intake |
| Application dates | Common p.4; department p.27 (printed 25) | Ordinary June 4-10, 2026 window, closing 23:00 JST; May special-oral and doctoral rows on the same page stay excluded. Carryover from special oral is not covered by the ordinary application workflow |
| English score sheets | Common p.6 section 7; department p.28 final notes | Common rule delegates whether scores are required; department says score sheets such as TOEFL/TOEIC are unnecessary for master's ordinary general selection. This is a resolved delegation, not a contradiction or exemption from all English-related assessment |
| English footer | Additional p.1 footer, with the above pair | A reference to score-sending instructions does not independently impose submission |
| Materials | Additional p.1 rows; department p.28 | Questionnaire and essay are ordinary examples; work/study plan depends on continuing employment while enrolling. Missing employment facts yield needs-information for that item, not a universal requirement |
| Checklist | Department p.28 and p.40 (printed 38) | Refer to checklist; the checklist itself need not be submitted. Do not infer that listed documents need not be submitted |
| Route boundaries | Department pp.27,29,30 (printed 25,27,28) | General, special oral and doctoral procedures remain distinguishable even where clauses use similar words |
| Intake references | FAQ pp.1,5; common p.2 | Flowchart branches require linked footnotes; p.5 explicitly points eligibility back to the guideline. Other departments' exceptions do not govern this target |

The eligibility paragraphs on common p.2 refer to notes on subsequent pages; p.2 alone cannot prove
an applicant eligible. Complete notes and any referenced review process must be bound before that
rule is activated. Similarly, online essay forms, full materials coverage and residence advice are
not certified merely because these four PDFs were downloaded.

## 4. Evidence identity and one worked example

Design evidence uses exact document key + 1-based physical page + verified printed label when known
+ manual section anchor. A manual anchor is a reviewer aid, not a fabricated parser block ID.
Runtime evidence additionally requires exact KB hash, Fact ID and the adapter output/locator binding
when available. `(document_id, kb_sha256, fact_id)` is the Fact identity; `fact:00001` alone is unsafe.

Worked trace: selected target -> source-set `s1` -> department key
`(complex-guide-2027-revised, 6063571d2ea0318d9af038340da0e8568cdabf18b03f788d41be59bf96e16fab)`
-> physical p.28 / printed 26 -> final notes under master's general selection -> score-sheet
submission conclusion, supported by common p.6's delegation and qualified by this exact route.
The eventual viewer opens physical page 28, never page 26. The example JSON deliberately contains
no invented KB hash, Fact ID, parser locator or bounding box.

Known page but unknown block/bbox: page-level evidence remains possible after text/source audit;
show no precise highlight and label locator quality. Missing or invalid physical page, wrong source
hash, stale KB binding, or unverified text: no authoritative conclusion or evidence navigation built
from guesses. A multi-source conclusion carries all supporting references, each with its own source.

## 5. Minimum compatible extension

Introduce additive, server-owned target/source-set/coverage records and a versioned orchestration
envelope for new-school requests. These are candidate contracts, not new fields injected into v1.
Each source retains its own KB and index. Select one approved build per source; do not register A/B
variants or the ISCT 334/391 roles as extra source documents.

The proposed future report composition envelope binds target, source-set revision, exact component
plan/KB identities, coverage and reviewed cross-document relationships. Existing one-document plans
and evidence materialization run within their own bindings. Their text/results are not concatenated
and declared a final authoritative report: the envelope must resolve coverage and cross-source
relations first. Reuse typed predicate and evidence primitives. If their APIs cannot express a
required relation, specify an additive versioned wrapper; do not weaken single-document invariants.
The wire format and cross-plan executor remain Proposed for the later backend Issue, which must
provide focused tests before release. They are not prerequisites for the isolated parser pilot.

| Existing boundary | v1 unchanged | Additive candidate / implementation gate |
| --- | --- | --- |
| `DocumentIdentity` 1.0 | Exact institution/family/edition/PDF binding | External target and source-set records; mixed-degree department PDF retains truthful coverage |
| `DocumentKnowledgeBase` 0.6 | Existing bytes, Fact/entity IDs and hashes | Scope/provenance sidecars bound to exact KB hash; later new-school build must isolate ISCT assumptions |
| `ApplicantProfile` 1.0 | Existing names, routes and enum values | Envelope owns selected target; reviewed mapping into supported predicates, no inference from names alone |
| Degree vocabulary | Document `doctoral` / `professional_degree`; profile `doctorate` / `professional` | Explicit mapping, with `master -> master`; `bachelor`, `other` and unknown are not silently mapped |
| `ReviewedReportPlan` 1.0 | Exactly one document and one KB; validators remain strict | Versioned composition envelope with per-source plans; incompatible rewrite requires user decision |
| Corpus/index | Existing registration, immutable assets and exact evidence keys | External source/build role registry; no physical move, copy, deletion or vector rebuild |
| Query/report API and PDF serving | Existing ISCT endpoints and responses | New versioned target entry and exact-document PDF registry; no GSFS request silently falls back to ISCT |
| UI | Existing working ISCT journey | Supported-target catalog and target-change state reset, implemented later |
| Regression | 334-vector frozen and 391-vector product suites stay separate | New GSFS and cross-identity tests; never replace old gold to hide differences |

Existing `build_document_kb` takes a generic identity but calls ISCT entity/scope code. The next
adapter must not call it for GSFS. Before any new-school KB build, a separate bounded implementation
must isolate the legacy profile and reject unregistered build profiles. This remains a mandatory
gate, moved after the parser-only experiment so the first task does not become a builder rewrite.

## 6. Failure and mismatch matrix

These are expected future product outcomes; statuses are conceptual, not new v1 response enums.

| Input or failure | Required outcome |
| --- | --- |
| Exact selected tuple | Resolve `s1`; product remains disabled until accepted runtime exists |
| Special oral instead of ordinary, or transfer from special oral | Not covered by this workflow; no borrowed dates/forms |
| Doctoral degree, another program or same translated name at another school | Unsupported target; no fallback/name-only match |
| B schedule | Unsupported target; common p.4 separately supports no master's B recruitment for this program |
| October 2026 or October 2027 instead of April 2027 | Not covered, not a universal claim that October admission is prohibited |
| Missing route/intake/edition, or contradictory profile target | Needs selection / target mismatch before retrieval; do not choose a nearest match |
| Foreign citizenship with ordinary route | Citizenship alone does not select a foreign-special route |
| Unknown citizenship/employment/residence | Only dependent conclusions need information; unknown is not false |
| Synthetic same-name source or Fact ID | Compare full qualified keys; reject mismatched institution/source/build |
| Missing core PDF or source hash mismatch | Bundle unavailable; never auto-download/rebuild at query time |
| Missing conditional reference | Affected conclusion unavailable/needs information; display coverage limitation |
| Unresolved rule conflict | Withhold affected conclusion; show both exact sources and review requirement |
| Unknown scope / inseparable mixed Fact | Exclude from ordinary ranking; do not promote by semantic similarity |
| Unknown bbox but verified page/text | Page citation allowed, no fabricated highlight |
| Missing physical page or stale evidence | Evidence invalid; no authoritative conclusion |

## 7. Decision and handoff

Accepted now: target tuple, exact source-set ownership, explicit scope/unknown semantics,
document-qualified evidence, additive compatibility strategy, asset isolation and one-task release.
Candidate pilot details are in [parser contract v0.1](parser-pilot-contract-v0.1.md). Production
normalization schema, multi-source wire format/executor, registry storage layout and MinerU choice
remain Proposed. No incompatible schema or assistant-authority decision is made here.

MS-02 [baseline adapter](ms02-baseline-adapter-spec.md) is accepted in PR #198. The sole next
development task is [#177](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/177), with the
[M14 pinned resource/gold plan](mineru-4.0.7-pilot-plan.md), assigned by the user to a development
agent. Design main reviews the PR; it does not implement it. Its final result must be
adopt/hybrid/fallback/reject. Deployment stays paused. Documentation rollback changes no assets.
