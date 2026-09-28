# ADR 0013: A reviewed multi-document material report slice

Status: Accepted on this design merge for RPT-01 only; API/UI remain unreleased. Owner: #191. Base: main
`f77da8bf336bd2d1792cdc1a8ac7b622ac9e218b` (MAT-01 independently accepted).

## Product decision

The user wants a credible internal demonstration by 2026-09-29: preserve the working ISCT flow,
show real GSFS evidence, and prioritize a report a teacher can take away. This is an internal
checkpoint, not a promised live admissions service or authority to weaken evidence checks.
The fixed GSFS historical target remains unchanged. Future winter trials must select actual
institutions/editions with the teaching team; this slice is not a current application window.

## Evidence and constraints

MAT-01 supplies a shared tri-state evaluator and pinned three-topic policy. Its policy remains
`production_enabled=false`, with runtime evidence unverified. IMPORT-01 preserves23 exact Facts
in three immutable candidate KBs, but their scope is unknown and document quality gates fail.
The existing v1 report/evidence executor accepts one document and requires genuine section/scope
information. Changing those validators or marking a candidate as globally approved is unsafe.

The design Agent rechecked retained images for common p6, program pp28/40 and additional p1.
The review explicitly distinguishes section headings, table headers/row context, source-wide
scope and applicability to the selected target. It is Agent review, not a university or teacher
endorsement. The pinned report plan records these judgments and the review-image fingerprints.

## Decision

1. Add an immutable, explicitly partial `ReviewedMaterialSliceEvidence` artifact and
   `ReviewedMaterialSliceReport` contract. They are not `DocumentKnowledgeBase`,
   `ReviewedReportEvidenceBundle` or `ApplicantReport` v1, and cannot be passed as such.
   Existing wire schemas, canonical bytes, ISCT behavior and public routes stay unchanged.
2. The new evidence artifact is a reviewed projection over existing qualified Facts, not another
   knowledge base. It reads the accepted candidate once, validates exact bytes, identities,
   pages, text hashes, lineage and required context, then binds the selected records to an
   explicit target-specific scope/section review. Raw Fact scope/section and failed KB gates
   remain visible and unchanged. No candidate promotion, corpus registration or index creation.
3. For this manually reviewed slice, a distinct slice-readiness gate supplements the raw candidate:
   exact pinned inputs + complete context + reviewed official locators + exact target + explicit
   basis/context roles. It does not convert a failed full-KB quality gate into a pass. This is the
   additive reviewed-artifact choice anticipated in ADR0012; it applies only to the pinned reviewed
   fragments, never to arbitrary failed KBs. Existing production evidence gates remain strict.
4. Reuse MAT-01's policy loader, request normalization and condition evaluator. The new report
   independently verifies the bound evidence before turning a matched policy effect into a
   scoped result. No second predicate engine, school-name dispatch or LLM-authored conclusion.
   Calling the accepted pure evaluator is allowed; rerunning its exhausted preview experiment is not.
5. Multi-source composition is approved data. English: E02 supplies the selected program rule;
   E01 directs the reader to the program; E03 is a method cross-reference, not a competing duty.
   Checklist: E04 asks the applicant to consult it, E05 says the form itself is not submitted.
   Work/study plan: E06 gives the employment condition, E08 binds the upload group/row and PDF
   method. E07 is context-only for a separate enrollment-stage document, with an incomplete
   outgoing reference; it cannot become an application-stage obligation.
6. Result statuses are `submission_required`, `submission_not_required`, `rule_not_applicable`
   and `needs_information`. A false condition never becomes a blanket exemption. The report
   retains source quotes separately from Chinese explanatory text, visible partial/historical
   limits, missing facts, and qualified citations with physical and printed pages.
7. The backend first produces deterministic JSON and readable Markdown without persisting
   profiles. Later API/UI consumes the same validated output: two school choices, clear coverage,
   results, evidence and copy/print. PDF coordinate highlighting is a separate bounded locator
   experiment; it is not a dependency of the core report and does not reopen MinerU.

## Sequence and exit boundary

Only RPT-01 (see [Spec](../onboarding/material-slice-report-spec.md)) may be released by this design.
It has two checkpoints inside one Issue: evidence validation, then report assembly/CLI.
If either cannot fit a focused implementation/review cycle, hand back the blocker and retained
evidence; do not solve it by bypassing a gate. No implementation of a following API/UI task until
this report boundary is independently accepted and its separate Spec is Ready.

The demonstration fallback is honest evidence browsing plus the existing ISCT report, with GSFS
reporting marked unavailable. It is not a fake school option or a partially validated report.
M15 remains open until the local user journey is verified. M13 stays paused, #177 closed,
334/391 and the accepted candidate immutable, and the assistant `reference_only`.

## Rollback

Remove the additive material-report modules and registration in their own local CLI; retain the
existing candidate and accepted MAT-01. The report plan and trust can be disabled by operators.
No existing KB/index/schema migration is needed. No paid service or new download is authorized.
