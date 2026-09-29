# Project Roadmap

This document is the planning source of truth for J-Grad Admission RAG. GitHub Issues represent
executable tasks and explicitly blocked planning records; an open Issue is not permission to
start it. Future work stays here until its dependencies and acceptance scope are defined.

## Current M17 release: usability before the school presentation

2026-09-30 user requested a rollback point and a development plan for six usability findings.
The running online preview is frozen at [demo-before-usability-20260930](https://github.com/yasu-isct/J-Grad-Admission-RAG/tree/demo-before-usability-20260930),
commit `29a91ac9280349300c0d1890f48cf9e4244cd68c`; [restore record](checkpoints/demo-before-usability-20260930.md).
The saved code excludes paused QA Draft #236; enabling the provider does not import its behavior.

Only [UX-01 #247](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/247) becomes Ready with this design merge:
report-button feedback and clear school navigation, using the existing four-step page and report pipeline.
See the [complete Spec](onboarding/demo-usability-navigation-report-spec.md) and [six-point development direction](onboarding/demo-usability-development-plan.md).
M17 Main implements; design independently accepts. Typography, plain-language copy, material explanations and
QA presentation are planned as B after A acceptance, with no second Ready Issue. No coverage expansion or QA behavior repair.
After both usability steps, prepare the demonstration and school presentation. QA #233 / Draft #236 stays paused.
No new paid verification, indexes, downloads or M13 work. The prior no-Ready statement below is historical.

## Previous M17 release: readable reports and source relations

2026-09-29 latest user decision supersedes the QA-first ordering below: **pause QA-01 #233 /
Draft #236**, first improve reports for their readers, then show existing multi-document evidence
relationships with on-demand original-text dialogs. [REPORT-02 #239](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/239)
was independently accepted and merged through [PR #243](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/243)
at `37603cf7292f573eaf9f802421a0ea82fe22725f`; see [acceptance](onboarding/report02-design-acceptance.md).
[EVID-UI-01 #240](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/240) was independently
accepted through [PR #245](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/245), merge
`eb7eb89b9dc8f10df5c03c54c5ab08dc359d5c19`; see [acceptance](onboarding/evidui01-design-acceptance.md).
Both presentation tasks are complete. No new implementation task is Ready. The next responsibility
is demonstration and school-presentation preparation; QA remains paused and GSFS coverage stays fixed.
M17 as a whole is not declared complete by this acceptance.

Reports contain selected basic information and actionable preparation status, without citation chains
in their preview/copy. Unknown preparation is not a missing material. Existing backend provenance,
canonical reports, applicant rules, v1 page and two-school selectors remain authoritative and reused.
Source graphs project the existing reviewed relations. A button inside the existing four-step material
card opens the graph in a modal; original excerpts replace the graph inside that same modal with a
back action. No standalone evidence page or inline expanded graph; close restores the original card.
See [reader-centered design and local interaction prototype](onboarding/reader-report-and-evidence-design.md).
No model calls are needed; QA's remaining11/50 calls remain unused. After these presentation tasks,
polish the demonstration and school presentation; stop before ordinary-student GSFS expansion.

## Previous M17 QA-first decision and audit history

On 2026-09-29 the user set the sequence **QA recovery -> readable optional reports
-> demo polish and preparation for a presentation to the user's school**.
[M17](https://github.com/yasu-isct/J-Grad-Admission-RAG/milestone/17) now ends at that presentation
readiness checkpoint. **Stop before ordinary-student GSFS coverage**; resuming coverage requires a
new explicit user decision and a separately released Spec. M16 remains complete.
This explicit decision supersedes historical statements below that no M17 task is released.

Only [QA-01 #233](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/233) is released and has
been claimed by the developer. Follow the [complete Spec](onboarding/qa-experience-recovery-spec.md).
Reuse the existing M10 adaptive pipeline, exact cache, 391 runtime and v1 question area. The current
8002 preview runs reviewed-state-offline; raw retrieval concatenation and single-paragraph rendering
explain the observed poor answer. This is not evidence that all historical online capabilities vanished.
UI-02 did not revalidate real online QA. Compare equivalent modes and preserve M9 authority.

The user subsequently authorized 20 dialogue scenarios with a cumulative cap of 50 provider calls.
Design completed the [real online audit](evaluation/qa01-online20/report.md) at exact green-CI
implementation `b7c6b772c403ec838e31a032a6c9d205da8f2364`: 25 application requests, 39 provider calls,
9 scenarios meeting their goals, 5 needing refinement and 6 failing. PR #236 remains Draft /
**Changes requested**: incorrect late-material advice, missing existing date/material information,
and conflated Japanese/English exam questions block final online acceptance. Fix these in #233 first.
The remaining 11 calls are reserved for design's bounded verification of a repaired head; the developer
must not spend them concurrently. The former unapproved six-call proposal is superseded, not additive.
Existing assets remain unchanged; do not rebuild indexes or widen retrieval scope without a reviewed
design delta. Routine fixes belong to the independent developer; no report-improvement task is released.

Reports will later export readable key information without evidence chains or internal fields in
the body/copy, preserving backend provenance and main-page source access. Then polish the existing
demo journey and prepare a readable sample report, a short walkthrough and a cooperation/limited
trial proposal. Show current capabilities separately from future potential; do not invent measured
time savings, current-season coverage or complete UTokyo support. This checkpoint does not require
a page redesign, a new feature platform or sending a proposal externally.

GSFS ordinary-student expansion is deferred, not cancelled. Its current general-selection slice
covers three material topics, not a special working-person admission route. Retain the two-school
selector and truthful limits for the presentation. Report/presentation tasks need their own later
Spec; neither is Ready today. #163 stays Backlog; M13 paused, MinerU #177 closed, 334/391 protected.

## Completed M16 correction: v1 flow with both schools

After trying the delivered page on 2026-09-29, the user retained the two-school framework but
explicitly requested the original v1 four-step page, with prominent dates/materials, main-flow
personal details and clear action/readiness results. The bounded
[UI-02 Spec](onboarding/v1-flow-restoration-spec.md) under [ADR0016](decisions/0016-restore-v1-flow-with-multi-school-capabilities.md).
implementation [UI-02 #229](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/229) is accepted
and merged in PR #231: head `cd09bd43abbc276c2f5fb1bc2fdae40aa82eb166`, merge
`40cd25d84c15d4ccaace610d5158875632dd428c`. Actual v1 components and accepted report capabilities
are reused; no new admissions coverage. Independent 29 focused tests, 3 Node tests and six real
report scenarios passed, with all 25 protected file identities unchanged. See
[final evidence and cumulative ledger](onboarding/ui02-final-acceptance.md).
M16 is complete again after this user-requested correction. No implementation is Ready; no M17,
highlighting or coverage task is automatically released. Existing user previews remain on their
original source checkout until explicitly switched; old and UI-02 acceptance budgets stay closed.

## UI-01 completion record: unified admissions workspace

On2026-09-29 the user explicitly approved the [interactive page prototype](ui-prototypes/unified-workspace-v1.html)
and instructed implementation. This supersedes M15's separate-entry product design, not its
accepted evidence/report machinery. [ADR0015](decisions/0015-unified-admissions-workspace.md) and
[UI-01 Spec](onboarding/unified-workspace-spec.md) define one task with two checkpoints: map existing
capabilities/results/reports, then integrate the complete `/app` page and supply real visual proof.

Both schools share selectors, results/evidence and an optional report button. Retain every existing
supported ISCT target and comparison/search/QA feature; GSFS remains the three-topic fixed slice.
Main-page ISCT report is a cited presentation export of existing base/comparison responses; GSFS
uses its accepted report endpoint. No new rule engine, index, school coverage or paid generation.

[UI-01 #225](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/225) is independently accepted
and merged in PR #227: head `f1b7b5c7a3cded5749c49de38355364c2732114f`, merge
`fe83493ba1108167dd9de3a1a352714033f01e9b`. Four review findings were fixed before acceptance.
Independent 56 focused tests and 3 Node tests passed; exact-head CI passed. Final-head real browser
proof includes 6 reports, source/copy parity, both schools/intakes, desktop/mobile and one offline
query. All 25 protected input files stayed unchanged. See the [release boundary](releases/m16-unified-workspace.md)
and [independent evidence](onboarding/unified-workspace-acceptance.md).
No Ready implementation remains. Do not automatically start highlighting, new coverage or M17.
UI-01 cumulative starts 4/4 and searches 2/2 are exhausted; reports 14/20, base/comparison/detail
POSTs 8/40 do not authorize a new service session or reset old budgets.
Older paragraphs recording no M16 release describe the M15 closeout before this user decision.
M13 remains paused; #177 remains closed and334/391 remain protected.

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
- Index artifacts are derived from `document_kb.json`, but rebuildability does not authorize
  deletion or replacement. Protect the 334-vector frozen baseline and 391-vector product runtime;
  migration or cleanup requires a reference audit, dry run, and explicit approval.
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
| M7 Reviewed rule coverage | v1.1 | Reviewed dates, eligibility, language, page scope, and common materials cover the current guideline | Every enabled rule remains evidence-bound and conditional content fails closed |
| M8 Interactive applicant demo | v1.2 | A Chinese-speaking applicant can operate a local target-to-checklist workflow | Desktop and mobile flows preserve official evidence, unknowns, and conclusion boundaries |
| M9 Evidence-grounded End-to-End RAG | v1.3 | Chinese or Japanese questions produce structured answers over scoped evidence and reviewed rule results | Pinned semantic retrieval, citation validation, refusal behavior, and real end-to-end acceptance pass |
| M10 Natural-language RAG Productization | v1.4 | A reference-only assistant answers general questions and adaptively checks school-specific points against bounded local material | One- or two-call routing, explicit zero-hit disclosure, exact zero-call cache reuse, privacy boundaries, and real DeepSeek acceptance pass |

## Completed M10 Summary

M10 is complete. M10-01 established explicit online question understanding; M10-02 and M10-04–06
added and stabilized the first-party DeepSeek provider; M10-07 introduced the bounded exact cache;
M10-08 corrected the product boundary to a visibly lower-assurance `reference_only` assistant; and
M10-09 completed adaptive one- or two-call routing. A real DeepSeek acceptance run demonstrated one
call for general questions, two calls for school-specific questions, and zero calls for an identical
cached repeat.

The assistant never replaces the M9 grounded endpoint or the reviewed eligibility/report path.
Applicant Profile values are not sent to the provider, zero local hits are disclosed, and provider
failures are not cached. Missing JLPT, J.TEST, and score-conversion authority has moved to
[COVERAGE-01](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/163) as post-M10 knowledge
coverage work; absence from the current corpus must not be presented as a negative admission rule.

| ID | Task | Status |
| --- | --- | --- |
| M10-01 | Add explicit online question understanding | Complete |
| M10-02 | Add the first-party DeepSeek provider path | Complete |
| M10-04–06 | Stabilize provider configuration, failures, and product integration | Complete |
| M10-07 | Add bounded exact caching | Complete |
| M10-08 | Establish the simplified reference-only answer contract | Complete |
| M10-09 | Add adaptive local retrieval and one-/two-call routing | Complete |

## Completed M9 Summary

M9 is complete. It connects the accepted M1–M8 boundaries without allowing a model to replace
official Facts, reviewed applicability rules, or server-owned citations:

| ID | Task | Status |
| --- | --- | --- |
| M9-00 | Update public project positioning and status | Complete |
| M9-01 | Add the formal pinned BGE-M3 Demo path | Complete |
| M9-02 | Define the Generation provider and structured output contract | Complete |
| M9-03 | Orchestrate grounded RAG and validate citations | Complete |
| M9-04 | Add the natural-language RAG API and page experience | Complete |
| M9-05 | Evaluate and close the release gate | Complete |

Paid API calls are never part of default CI and require explicit per-run authorization. Model files,
official PDFs, API keys, raw personal profiles, and sensitive model responses are not committed.
M9-05 adds a 20-case human-reviewed grounded-answer suite, a 42-query Japanese/Chinese retrieval
benchmark, a deterministic offline release gate, a separately authorized manual paid-provider
workflow, and real PDF/BGE-M3/service/browser acceptance at 1440px and 390px.

## Completed M8 Summary

M1 through M8 are complete. M8 delivered the applicant-facing experience in three sequential
slices. DEMO-01 established a server-owned application-target catalog, profile-free base
requirements, and an accessible evidence drawer. DEMO-02 added grouped education, English,
Japanese, and material-preparation input plus server-side comparison. DEMO-03 completed the
interactive partial checklist, filters, server-derived next actions, and final desktop/mobile
acceptance. The browser does not persist Applicant Profile data.

The primary interface uses Simplified Chinese for navigation, explanations, and states; official
school/college/department names and evidence remain Japanese. Technical Fact/scope details stay
collapsed. M8 does not broaden low-frequency rules, add accounts, claim final eligibility, or move
rule inference into the browser. M9 preserves those boundaries while adding scoped natural-language
retrieval, replaceable generation, and deterministic citation validation in the sequence above.

## Completed M6 Summary

M1 through M5 are complete. M6 exposes the accepted engine boundaries as versioned local APIs,
adds observable durable build operations, then connects cited applicant reports and a focused
evidence-review interface. APP-01 is the first transport slice: synchronous build and reviewed
corpus query remain thin wrappers over the existing builder and COR-04/COR-05 contracts.

APP-03A adds the reviewed rulebook needed before applicant reporting can be orchestrated. One
server-owned plan binds one exact document identity to existing reviewed rules and policies and
declares only partial intent coverage. It does not run a profile, materialize official text, or
claim overall eligibility. APP-03B will consume that boundary only after APP-03A is accepted.

APP-03B audits one selected corpus document, matches its unique server-owned plan, and materializes
the exact bound official Facts into an in-memory evidence bundle. It performs no ranked retrieval or
applicant reasoning. APP-03C consumes that exact evidence with one profile and covered intent,
reuses the complete M4 public chain, and returns a strict self-auditing report plus safe fixed
Japanese Markdown. Its visible status remains report readiness under explicitly partial coverage.
APP-03D places that accepted chain behind one strict local HTTP route. Server-owned reviewed plans
are explicit lifespan configuration, and every request still selects exactly one corpus document;
the endpoint adds transport only, not retrieval, new rules, persistence, or broader conclusions.
APP-04A begins the focused UI with a safe reviewed-document catalog and an offline evidence-search
screen. It exposes exact query hits and diagnostics only; applicant profile and report presentation
remain a separate APP-04B slice. APP-04B adds that profile/report tab through a server-owned intent
parser and the frozen APP-03D contract, while preserving the partial-coverage boundary.

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

The historical M1/M4 85-page real-PDF baseline produced 298 Facts and RetrievalUnits, with 141
reference claims (7 resolved, 6 ambiguous, 128 unresolved). It is not the current product baseline.
The 2026-09-27 read-only product audit found 391 Facts, all with physical pages, and 130 reference
claims (10 resolved, 5 ambiguous, 115 unresolved). The distinct 334-vector semantic release
baseline remains frozen. See the [coupling audit](audits/single-school-coupling-2026-09-27.md).

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

### M13 Public Demo Deployment

M13 publishes the existing single-school Demo through a bounded HTTPS entry point. It preserves the
391-vector product runtime as a private read-only deployment asset, leaves the 334-vector semantic
release baseline frozen, and adds a public-only route surface, abuse/cost controls, reproducible
packaging, real staging acceptance, and operator recovery documentation.

| ID | Task | Output |
| --- | --- | --- |
| DEPLOY-01 | Establish deployment architecture and cost baseline | Measured asset/resource inventory, current provider comparison, recommendation, and approval gate |
| DEPLOY-02 | Build a reproducible production package | Non-root container and fail-closed read-only startup contract |
| DEPLOY-03 | Add public security and cost protection | Public route allowlist, proxy/origin policy, limits, budgets, redacted errors/logs |
| DEPLOY-04 | Deploy and accept public staging | HTTPS browser evidence, restart/runtime audit, cache and protection verification |
| DEPLOY-05 | Finalize access and operations | Domain decision, upgrade/rollback/recovery/key-rotation/runbook, final docs |

DEPLOY-02 starts only after the operator approves the provider and monthly ceiling recorded by
[Public Demo Deployment Architecture v1](deployment-architecture-v1.md). Paid resources and private
asset upload are not authorized by roadmap or issue creation.

**Current decision (2026-09-27): deferred after DEPLOY-01.** DEPLOY-02 through DEPLOY-05 remain
open planning records but are not Ready while the user completes external consultation. Do not
create cloud resources, upload private assets, or continue implementation until the user explicitly
resumes M13.

### Post-single-school Closeout And Design Handoff

REL-01 is complete (#192 closed by merged PR #193). It freezes the local single-school boundary in
[Single-school Portfolio Release v1](releases/single-school-portfolio-v1.md) and the compact
[Post-single-school Design Handoff](checkpoints/post-single-school-design-handoff.md). The long-lived
cross-milestone design authority is
[GitHub #191](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/191); it must begin with a
read-only audit of single-school coupling and a compatibility ADR. MinerU 4.x remains the bounded
Tokyo University experiment in
[#177](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/177), not an assumed replacement
parser.

The first new target is University of Tokyo / Graduate School of Frontier Sciences / Complexity
Science and Engineering, selected by the user on 2026-09-27. Source downloads are authorized.
The [source lock](onboarding/utokyo-gsfs-complex-2027.md) records the bounded acquired set;
downloads do not activate a school or authorize production artifact mutation.

The [compatibility ADR](decisions/0008-multi-school-compatibility.md) has partially accepted MS-01
boundaries under #191; production schema details and parser choice remain Proposed. The
[GSFS contract](onboarding/gsfs-source-set-contract-v0.1.md) is the #195 design deliverable.
MS-02 #197 is accepted in PR #198: the isolated legacy parser adapter preserves 83 real source
pages without creating a GSFS KB. Full legacy builder-profile isolation remains mandatory before
the later new-school KB task. Follow the [development lessons](development-lessons.md): deliver one
narrow user journey before expanding coverage. M13 remains paused.

### M14 Multi-school Foundations and Parser Pilot

[GitHub M14](https://github.com/yasu-isct/J-Grad-Admission-RAG/milestone/14) groups the bounded first
phase, previously unassigned to a milestone. It does not mean that the new school is product-ready.

| Issue | State | Exit evidence |
| --- | --- | --- |
| MS-01 #195 | Complete, PR #196 | Fixed GSFS target/source-set and additive v1 compatibility contract |
| MS-02 #197 | Complete, PR #198 | Isolated legacy adapter, 83-page real comparison and honest baseline weaknesses |
| PARSE-01 #177 | Closed, PR #200 | Accepted failed-experiment audit / reject decision; no parser activation |

The [pilot execution Spec](onboarding/mineru-4.0.7-pilot-plan.md) locks software/model/source/gold
identities and budgets before candidate outputs. M14 closes with an accepted
[reject decision](decisions/0009-mineru-4.0.7-pilot-fallback.md): 388 attempted page-passes exceeded
the shared 168-page budget; Basic timeout attribution is inconclusive because the historical
supervisor could block on undrained pipes. Flash gains are observations, not fallback approval.
The subsequent [evidence-gap assessment](onboarding/gsfs-evidence-gaps-and-next-slice.md) defines
M15 below. The reject decision still authorizes no parser rerun or production activation.
The following stage covers GSFS KB/profile isolation, rule/retrieval integration and then user-facing
acceptance; its Issues are released later, not concurrently. #191 remains cross-milestone governance.
Reuse one development chat through M14, one active Issue at a time. Replace it with a checkpoint only
when context quality or scope requires; there is no one-new-chat-per-Issue requirement.

### M15 Reviewed GSFS Materials Slice

Completed on2026-09-28 after independent acceptance of PR #223 at `67e5727`.
The bounded journey is reviewed excerpts -> candidate Facts -> scoped conditions -> cited report ->
local optional presentation. This does not complete general multi-school admissions support.

[M15](https://github.com/yasu-isct/J-Grad-Admission-RAG/milestone/15) targets a bounded materials
journey, starting with English score sheets, checklist submission and employment-related plan
context. [ADR 0010](decisions/0010-reviewed-source-evidence.md) adds reviewed source excerpts as
pre-KB inputs, preserving the existing KB/rule/citation path and explicit manual provenance.

| Order | Task boundary | Release state |
| --- | --- | --- |
| 1 | [EVID-01 #202](onboarding/reviewed-source-evidence-spec.md): eight reviewed excerpts, exact target/source audit, three readable operator previews | Complete, accepted PR #204 |
| 2 | [BUILD-01 #206](onboarding/build-profile-isolation-spec.md): isolate legacy ISCT policy and guard explicit build entry | Complete, accepted PR #208; no GSFS KB |
| 3 | [IMPORT-01](onboarding/reviewed-fragment-import-spec.md): 23 fragments to three candidate KBs and bound lineage | Complete, accepted PR #211; no production activation |
| 4 | [MAT-01](onboarding/material-condition-spec.md): shared condition core, compatible profile envelope and pinned policy previews | Complete, independently accepted PR #215; condition-only, no official report |
| 5 | [RPT-01 #217](onboarding/material-slice-report-spec.md): reviewed multi-source evidence and teacher reference report | Complete, independently accepted PR #219; JSON/Markdown only |
| 6 | [DISPLAY-01 #221](onboarding/optional-reference-workspace-spec.md): shared entry, evidence browsing and optional report/copy | Complete, independently accepted PR #223; bounded local journey verified |

Do not activate the full GSFS source set or claim complete eligibility, dates or materials coverage.
No new models/PDFs, MinerU reruns, paid calls, index migration or M13 work are part of #202.
Keep one M15 development chat and checkpoints at contract/tests, real previews and PR handoff.
M15 completion includes downstream integration under its own reviewed Specs and actual user-facing
acceptance. EVID-01 passed independent acceptance
in PR #204 (96 focused tests, six reproduced real previews and exact-digest approval). The unique
local presentation contract in [ADR0014](decisions/0014-optional-reference-workspace.md) is accepted in PR #223, following accepted
[RPT-01 #217](onboarding/material-slice-report-spec.md) in PR #219. Its independent review
resolved the public assembly/render trust-boundary defect at head `a72989e`, passed 406 focused
tests (nine local Windows symlink skips), and reproduced all three real reports byte-for-byte.
The report CLI budget is 3/3 exhausted; DISPLAY-01 validation is also exhausted at3/3 starts and7/7
covered POSTs, including the user-authorized developer supplement. No next implementation is Ready.
[ADR0013](decisions/0013-reviewed-material-report-slice.md) specifies a reviewed
partial projection over immutable Facts, not whole-KB quality approval. The user prioritizes a
credible internal demonstration by2026-09-29: a copyable report, then dual-school UI and optional
page highlighting. This is a planning checkpoint, not a promised production deadline.
[ADR 0012](decisions/0012-material-conditions-and-report-boundaries.md) separates condition matches from
material obligations and preserves strict report/evidence gates. [ADR 0011](decisions/0011-explicit-build-profiles-and-reviewed-lineage.md)
and the import Spec pin deterministic candidate mapping, unknown scope and failed production
quality gates. DISPLAY-01 releases only a local capability-aware entry and optional report action:
school selection and evidence browsing generate no report; an explicit button does. Users are not
restricted to teachers or students. ISCT retains its original workflow; GSFS advertises its actual
historical three-topic coverage. Highlighting, GSFS search/QA and full admissions coverage remain
unreleased. The new bounded HTTP/browser budget does not reset any older experiment. M15 is complete.
Independent final validation:179 focused tests passed,3 Windows symlink skips, exact-head CI green;
the evidence-loading race is fixed. A real final-head browser run verified both capabilities,
zero automatic report POSTs, three byte-identical reports, desktop/mobile copy and22 unchanged
input files. See the [acceptance record](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/223#issuecomment-5869795291)
and [release boundary](releases/m15-reviewed-materials-preview.md). Stop M15 progression monitoring;
M16, highlighting and expanded admissions coverage need a separate decision and Spec.

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
| COR-04 | Select reviewed active/historical versions | Constrained defaults cannot mix editions silently |
| COR-05 | Add safe global retrieval across selected documents | One audited, document-qualified global hybrid rank |

### M6 Usable Service

| ID | Task | Output |
| --- | --- | --- |
| APP-01 | Expose build and query APIs | Stable request, response, and error contracts |
| APP-02A | Define durable build-job records and repository | Crash-safe SQLite/blob job ownership |
| APP-02B | Run durable jobs through a bounded worker | Lifecycle-owned local build execution |
| APP-02C | Expose durable job HTTP routes | Observable long-running document builds |
| APP-03A | Define reviewed single-document report plans | Canonical partial rulebook for later report execution |
| APP-03B | Materialize exact reviewed report evidence | Audited bound Facts with official text, pages, and rule IDs |
| APP-03C | Assemble deterministic cited applicant reports | Exact selected evidence and M4 results become a self-auditing partial report |
| APP-03D | Expose cited applicant report HTTP route | Strict single-document report request returns the validated report and exact Markdown |
| APP-04A | Add local evidence-review UI and reviewed-document catalog | Offline one-document search exposes exact evidence and diagnostics |
| APP-04B | Add applicant profile and cited-report UI | Bounded profile controls call the frozen APP-03D contract |
| APP-04 | Add a focused evidence-review interface | Search, profile input, evidence, and report views |

## GitHub Workflow

The intended workflow is `Backlog`, `Ready`, `In Progress`, `Review`, and `Done`. The audited
GitHub Project currently exposes `Todo` for #163, while the other open design/deployment records
have no project membership. Until those fields are explicitly aligned, record release/blocking
decisions in the Issue body; neither `Todo`, priority, nor an open milestone means Ready.

- Release only one dependency-ready implementation issue at a time, as required by #191.
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
