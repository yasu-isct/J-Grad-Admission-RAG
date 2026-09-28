# ADR 0012: Reusable material conditions before multi-source reports

Status: Accepted for MAT-01; implementation independently accepted in PR #215. Report activation remains gated by a later Spec.
Owner: #191. Baseline: main `595e6998ed8dcba0f565d732ba09180e605078cd`, after IMPORT-01 #209 / PR #211.

## Evidence

The accepted three candidate KBs preserve 23 fragments and five reviewed relations. They deliberately
have unknown Fact scope, empty official section paths and failed production quality gates. Their
context reader now validates trusted inputs and complete candidate bytes. IMPORT-01's four real
calls are exhausted; no downstream task may reuse that allowance for another import run.

`reasoning/application_materials.py` fixes exactly five ISCT items, their order, credential exceptions
and 2026-09/2027-04 coverage. `ApplicantProfile` 1.0 has no employment facts or canonical institution/
route identity. `ApplicabilityRule` has reusable comparisons and ALL/ANY three-valued logic but its
field paths are tied to that profile. `ReviewedReportPlan` / `ReviewedReportEvidenceBundle` 1.0 each
bind one document; evidence requires nonempty section paths and matching Fact scope. These are real
dependencies, not grounds to relabel unknown scope or concatenate three single-document outputs.

## Decision

1. Preserve ApplicantProfile 1.0, existing five-item policy, rule/decision/plan/evidence schemas,
   public routes and their canonical bytes. Add a separate versioned operator request envelope
   containing the existing profile, explicit MS-01 target and two strictly typed applicant assertions:
   currently employed in a company/public agency/organization, and intention to retain that status
   at enrollment. Null means unknown; occupation, citizenship and free text do not supply either fact.
2. Factor the existing value comparisons and ALL/ANY status combination into one small shared pure
   implementation. The old applicability engine delegates without changing behavior; the new envelope
   uses the same logic. Keep existing enums/import paths and validation responsibilities. No second
   school-specific engine, expression language, plugin registry or arbitrary field-path execution.
3. Store material names, reviewed target, conditional predicates, stages and proposed effects in pinned
   policy data. Generic code selects by exact complete target before evaluating conditions. A condition
   match is not a material obligation: an unconditional rule can mean “submission not required.”
   MAT-01 outputs only condition status, unknown input fields and input/policy identity; it does not
   issue an official material conclusion, create a report or attach unchecked evidence as authority.
4. For the fixed slice, distinguish: English score-sheet submission; submitting the checklist itself;
   and application-stage work/study plan. The employment condition is a conjunction of two assertions.
   A false condition only means this reviewed rule does not apply, not a general exemption. E07's
   employer consent is an enrollment-stage context note; its common-guideline 11.(8) reference has
   not been imported, so no complete consent requirement is activated.
5. Full document identity, candidate coverage, rule applicability and applicant assertions remain
   separate. The existing mixed-degree guide never becomes a master's-only document. Same names do
   not authorize another school or route; target conflicts produce no topic decisions.

## Next integration gate

MAT-01 is a reusable condition prerequisite, not a new answer store or a bypass of the evidence chain.
The next separately reviewed Spec must bind every actionable rule to exact qualified Facts plus
required context, resolve common/program/additional-document roles explicitly, and provide a genuine
scope/section review before any candidate can enter authoritative report materialization. No adapter
may set a failed KB quality gate to true, pretend a technical label is an official heading, or feed
unknown scope into the existing report materializer as if it were approved.

That Spec must choose and audit an additive reviewed scope/artifact and multi-source composition
contract. A new derivative artifact, if needed, has a new immutable identity and preserves the accepted
candidate; existing 334/391 assets and candidate files are never migrated or overwritten. Reuse the
existing Fact/hash/text/page checks and deterministic applicability core. Preserve the single-document
v1 validators and do not generate fake component rules just to satisfy their cardinality.

## Sequence and rollback

1. MAT-01 only: shared condition logic, additive operator envelope, pinned draft material policy and
   exhaustive tri-state/target-isolation tests. No official report or runtime evidence activation.
2. Design and accept reviewed scope/evidence plus multi-source report binding; split implementation
   if it exceeds two focused days. Not Ready in this ADR.
3. Bounded local API/UI materials journey and real browser/citation acceptance; M15 closes only then.

Rollback MAT-01 removes the additive condition tooling and restores delegation in the existing
predicate helpers; no stored data migration. No downloads, parsing, embeddings, paid calls, index
builds or M13 work. Reference-only assistant responsibility stays unchanged. No user product-choice
decision is required for this isolated, backward-compatible condition prerequisite.
