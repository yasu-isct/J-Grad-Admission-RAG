# ADR 0008: Multi-school compatibility and source-set ownership

Status: Partially accepted under MS-01; implementation details remain Proposed. Design under
[ARCH-01 #191](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/191).
Date: 2026-09-27. Production schemas, runtime and parser behavior are unchanged.

MS-01 [contract](../onboarding/gsfs-source-set-contract-v0.1.md) accepts the fixed target/source-set,
scope and failure semantics, qualified evidence, additive compatibility, asset protection and
single-task release. The experimental [parser v0.1](../onboarding/parser-pilot-contract-v0.1.md)
is implementable for comparison. Production schema/wire layout, cross-source report executor,
registry storage, native block/table details and parser choice remain Proposed pending their
implementation/pilot evidence. Acceptance of these boundaries does not authorize migration.

## Context and product contract

The [audit](../audits/single-school-coupling-2026-09-27.md) finds reusable multi-document retrieval
and evidence infrastructure, with school-specific builder/policy assumptions in generic entry
points. The user selected University of Tokyo / Graduate School of Frontier Sciences (GSFS) /
Complexity Science and Engineering as the first new target and authorized downloads. The user
confirmed the fixed 2027 master's ordinary general-selection A / April 2027 intake slice. The
[source lock](../onboarding/utokyo-gsfs-complex-2027.md) supplies real design inputs.

The first journey is deliberately small: select one reviewed target, inspect dates, ordinary
eligibility, language and materials, compare supported profile facts, then open the correct
official document and physical page. Unsupported routes remain visibly unavailable. Additional
programs, teacher-directory rules, full schema generality and deployment are not prerequisites.
Follow the [development lessons](../development-lessons.md); do not build another long sequence of
infrastructure without demonstrating this journey. The assistant remains `reference_only`;
general questions need at most one planning call, school-specific questions at most planning plus
final, and exact successful cache repeats zero. This ADR adds no model calls.

## Decisions

### 1. Separate admission targets, sources and builds

A reviewed target binds stable institution, organization unit/graduate school, program, degree,
admission cycle, intake, selection route and examination schedule identities. Japanese/translated
names and aliases are presentation data. Do not conflate ordinary selection, special oral selection,
foreign-applicant selection, an A/B schedule, citizenship and admission month. Optional dimensions
must explicitly be not-applicable or unknown; unknown is never an unrestricted wildcard.

An organization hierarchy describes affiliation; program associations describe participation.
Avoid requiring every university to reproduce Science Tokyo's college/department hierarchy.
Degree vocabulary gets an explicit mapping at the v1 boundary.

One PDF may cover multiple targets; one target may need several PDFs. A reviewed, versioned
source-set binding connects the target to exact documents and their roles (common guideline,
program guide, supplement, correction, conditional reference). Required missing sources fail closed.
Cross-source conflicts remain visible until reviewed; neither the latest timestamp nor the most
specific-looking heading automatically wins. v1 one-document plans remain valid legacy contracts;
new multi-source orchestration must preserve each binding's own document/KB/Fact/page identity.

### 2. Distinguish official versions from local builds

Document family, admission edition, exact revision and PDF SHA-256 identify official sources.
Record landing/download URLs, retrieval time and explicit publication/revision dates when known.
HTTP Last-Modified is transport metadata, not proof of an official revision date. Changed bytes at
the same URL require a new source revision. A source-set version freezes the exact constituent
revisions; active/historical selection remains reviewed, never inferred from filename order.

Parser/config/model provenance, normalization/chunking versions, KB schema/hash and embedding
projection describe derived builds, not new official editions. Preserve physical PDF page and
printed page label separately; a viewer link always uses the former.

### 3. Repository-owned parser adapter

`parse(exact_source, parser_config) -> NormalizedDocument` is the candidate seam. Its records carry
1-based physical page, block locator/type/text, reading order, heading/table relationships, optional
bbox with coordinate convention/known-state, parser version, dependency/model revision and config
digest. Locator stability is defined for identical source/configuration, not promised across parsers.
Missing coordinates stay unknown. Mixed pages retain block-level provenance.

Keep current PyMuPDF/pdfplumber behavior as the comparison baseline. School-specific section/scope
configuration belongs in an explicit reviewed build profile. New identities must not fall through
to the Science Tokyo entity table or page-specific exceptions. Normalized output is neither a
reviewed admission fact nor a rule decision. The prototype contract is frozen only after #177
supplies comparative evidence; no production parser replacement is assumed.

### 4. Scope rules by their reviewed source set

Global means common within the bound institution/source-set/target coverage, never global across
universities. Reuse typed predicates, precedence, interaction and cited-report mechanisms. Isolate
five-material policies, B-schedule logic, conversion constants and special-program rules behind
their exact reviewed scope. Do not create a second rule engine or infer policies from parser output.
Every authoritative conclusion requires exact official text and document-qualified evidence.

### 5. One logical corpus, immutable physical builds

Separate source records, KB/index build records and role/activation references. A runtime chooses
one authorized build per selected source, and never combines experiment, product and frozen
baseline variants as ordinary documents. Existing PDF-hash uniqueness is a useful source constraint;
do not bypass it by inventing duplicate source IDs for A/B outputs.

The complete build key binds exact source and KB hashes, KB/index schemas, build/projection
configuration, embedding provider/model/revision/dimension, normalization and distance contract.
Record parser lineage with the KB build. Missing legacy provenance remains explicitly unknown,
not fabricated to force equality. Identical complete keys reuse a canonical artifact; concurrent
duplicate requests must not publish competing canonical outputs. A minimal explicit registry for
this slice is sufficient; no storage-service migration or vector database is required.

Feature workspaces and acceptance runs reference assets read-only. Start with registration of
existing exact paths; do not move, copy, link or delete the 334/391 artifacts. An access error or
identity mismatch is a typed stop, never permission to rebuild elsewhere. Physical cleanup needs
its own reference audit, dry run and user approval.

### 6. Eligibility before both retrieval channels

Resolve the user's target and source-set first. Derive the same document-qualified eligible Fact
set for vector and BM25 ranking, including reviewed common/ancestor clauses and explicit program
clauses. Apply edition, intake, route, schedule and content-purpose restrictions before candidates
are ranked; unknown scope is not an ordinary-admission default. Review relevant appendices rather
than excluding all appendices categorically. One-hop reference expansion cannot bypass these gates.

Page classification alone cannot sanitize mixed Facts. A reviewed Fact/block eligibility mapping
must either admit a justified bound span or withhold it. Keep old frozen ranking runs intact;
validate intentional new product selection behavior in its own suite rather than editing old gold.

### 7. API and UI compatibility

Use a server-owned supported-target catalog instead of a Cartesian product inferred from rules.
Validate the complete selected combination; load scoped aliases and an exact-document PDF registry.
Expose edition and source identity in evidence without leaking local paths. A target change clears
old results, checklist and target-relative profile fields; genuinely target-independent personal
facts can be retained explicitly. Test keyboard, selection, filter and resubmission transitions.

Keep v1 single-school request/data behavior. New contracts use explicit versions or reviewed
external bindings; never silently rewrite old KBs or broaden a legacy request to multiple schools.
Any incompatible public schema change returns to user decision with a migration plan.

### 8. Regression and pilot isolation

Maintain separate suites for the 334-vector frozen semantic baseline, 391-vector Science Tokyo
product, the GSFS source set, and cross-school/edition/route isolation. Synthetic same-name schools
prove identity behavior; real PDFs prove provenance and rule meaning. Fake vectors prove plumbing
only. Semantic acceptance reuses pinned models and registered indexes without implicit builds.

[#177](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/177) compares fixed inputs with the
legacy parser and a verified fixed MinerU release/model/config. Published backend availability,
license and resource needs must be checked rather than assuming names in an older Issue still
exist. Download permission is recorded; it does not remove this version/resource selection step.
Keep experimental outputs outside production activation. Assess page/locator coverage, text,
reading order, tables, duplication/noise, key-rule recall, resources and repeatability against
reviewed samples. End in adopt/hybrid/fallback/reject; never decide from attractive Markdown alone.

## Dependency sequence and single release point

These are slices, not an authorization to start all tasks or new milestones.

| Order | Work | Exit evidence |
| --- | --- | --- |
| 1 | MS-01: freeze target/source-set and v1 compatibility contract | Completed design: concrete GSFS mappings, conflict/unknown examples and next Spec |
| 2 | MS-02: isolated baseline parser adapter, complete in PR #198 | 83 real pages preserved; GSFS never enters the ISCT KB builder |
| 3 | #177 complete in PR #200 | Rejected execution: cumulative budget exceeded; observations retained, no parser authorization |
| 4 | Freeze provenance contract and minimal build registration | Correct document/block/page lineage and duplicate-build prevention |
| 5 | Legacy build-profile isolation, then thin first-target backend slices | Explicit profile before any GSFS KB; scoped selection, minimal reviewed rules and multi-source evidence |
| 6 | First-target API/UI journey and real acceptance | Correct selection, requirement/profile behavior, PDF navigation and ISCT non-regression |

Split each implementation slice into no-more-than-two-day Issues when its prerequisites are known;
do not pre-release a large backend/UI task. Each Issue needs product/non-goals, asset inventory and
impact, focused behavior/real-data evidence and rollback. Broader generalization follows the first
accepted journey. M14 groups orders 1-3 and closes with the
[rejected-execution handoff](0009-mineru-4.0.7-pilot-fallback.md), not a production parser contract.
The follow-up [ADR 0010](0010-reviewed-source-evidence.md) and
[EVID-01 #202](../onboarding/reviewed-source-evidence-spec.md) defined the pre-KB evidence tool,
now accepted in PR #204. [ADR 0011](0011-explicit-build-profiles-and-reviewed-lineage.md) releases
only [BUILD-01 #206](../onboarding/build-profile-isolation-spec.md) for legacy profile isolation before
reviewed import. This refines the coarse orders 4-5 above: profile isolation first, then a reviewed
KB/lineage/publication Spec. No parser rerun is released. Registry implementation and new-school
KB/rule/UI activation remain later work.
MS-01 deliberately separates the parser-only seam from legacy builder-profile isolation. The latter
is still mandatory before new-school KB construction; it is not needed to compare parser output.

## Consequences, unresolved details and rollback

Multi-source rule composition is an explicit gap in current one-document reports. MS-01 specifies
an additive envelope and failure boundaries; its wire/executor details need review before backend
implementation. This ADR does not choose a production schema migration, parser
winner, model patch, or new physical registry layout. It records the invariants and a bounded path
to test them. M13 is paused; cloud upload, paid calls and destructive asset changes remain outside
scope. Documentation can be reverted independently. Future activation changes must restore the
previous reviewed pointer without rebuilding or replacing frozen artifacts.
