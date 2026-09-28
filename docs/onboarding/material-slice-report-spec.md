# RPT-01: Three-topic teacher reference report with reviewed multi-source evidence

Execution: [Issue #217](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/217).
Status: Sole next implementation after this design merges; before merge, Not Ready.
Milestone: M15. Owner: M15 Main for implementation, design main for independent acceptance.
Depends on #213 / PR #215 and [ADR0013](../decisions/0013-reviewed-material-report-slice.md).
Reuse the current M15 chat. One Issue, one implementation PR, two checkpoints.

## Background and visible goal

The accepted condition preview does not issue material advice. This task connects the exact
three-topic GSFS policy to reviewed official evidence and produces a Chinese reference report
that a teacher can read/copy, without claiming a complete checklist, eligibility or current intake.
The selected historical target is fixed by the plan: UTokyo GSFS Complexity Science and Engineering,
2027 master's ordinary general selection A, April2027 intake. No automatic latest-year selection.

## Scope and non-goals

Implement an additive reviewed-slice evidence contract, deterministic report assembler, strict
external-input-bound loaders, and one local `python -m` CLI. Reuse existing Fact/document/lineage
models and MAT-01 comparisons. Do not change pyproject, existing schemas, official policy/seed/pins,
ISCT rules or behavior, old report validators, API/UI, corpus, indexes, parsers or natural-language
assistant. No profile database, batch student management, uploads, PDF export, coordinate highlighting,
external network, paid calls, new source/model downloads, or new admissions-topic extraction.

The accepted candidate is read-only. No IMPORT-01 map/build/publish/validate_candidate/read_context
execution and no regeneration of its tree. Candidate/Lineage model validation and shared safe
path primitives may be reused; the new reader audits pinned existing bytes, not another import.
Do not load ISCT334/391 assets for this task. Existing synthetic compatibility fixtures are allowed.

## Versioned design inputs

- `material-slice-report-plan-v1.json`: exact target, policy reference, candidate/source pins,
 8 record-level scope/section reviews, approved topic composition, render text, limitations.
- `material-slice-report-trust-v1.json`: plan_id/revision/exact-byte SHA-256 from operator-owned config.
- Existing material-condition-policy/trust and three small request fixtures remain unchanged.
- Existing evidence seed and import lineage are provenance inputs, not substitute evidence text:
  official report quotes must be read from the actual candidate Facts and reconciled with the seed.

Implement closed nested models for every plan section; fixed schema_version1.0, artifact role,
teacher-preview release state, positive strict revisions, strict booleans, lowercase SHA-256,
nonempty trimmed IDs. No arbitrary nested dictionaries to avoid validating the contract.
Exact file shape is authoritative; no silent defaults for omitted trust/authority/scope fields.
JSON rejects duplicate keys, non-finite values and extra fields. Canonical JSON is UTF-8, sorted
keys, compact separators and trailing LF. Pin is not derived from untrusted input at runtime.

## Checkpoint 1: verified evidence and reviewed scope

1. Accept explicit paths to plan/trust, policy/trust, seed, candidate root and source-PDF directory.
   Validate external trust and the plan's policy/seed references before interpreting content.
   Read the five candidate files named in the pinned plan: candidate.json, lineage.json and
   the three fixed `documents/<id>/document_kb.json` files. Enforce exact file set and reject unsafe
   relative paths, symlinks/junctions/reparse ancestors, escapes, duplicates and unexpected files.
   Operator paths never appear in user output/errors. Pure bytes-based validation is provided
   for synthetic tests and future in-process API reuse.
2. Compare exact file hashes before constructing models. Candidate build_id, target, source-set,
   seed/manifest/contract/import-config bindings, documents, KB hashes and lineage hash must agree
   with the plan, MAT policy prerequisites and one another. Reuse the existing strict models where
   applicable; do not accept arbitrary dictionaries or a caller-supplied `verified=true` object.
3. Verify the three PDF hashes and page counts against full DocumentIdentity and pinned plan.
   Only open them for hash/page-count inspection; no extraction/OCR/rendering/building in the CLI.
   Read captured bytes once per source and use them for page-count checks; detect source mutation
   during reads and do not re-open a path later to validate different bytes. Cache only inside
   this invocation. No fourth conditional-intake source or recursive asset scan.
4. Load candidate KBs with existing loaders/canonical checks. Reconcile full identity, unique
   qualified Fact IDs, exact Fact text hashes and source pages with each required binding, lineage
   record and seed fragment. Every required fragment occurs once, none is substituted or silently
   omitted. Verify all23 approved fragments for this plan, all8 records and all5 relations, with
   complete qualified relation endpoints. This is a bounded slice audit, not full-PDF completeness.
5. Preserve raw KB quality=false, Fact scope=unknown, empty section paths, capture method and manual
   provenance. Do not edit them or manufacture v1 `ReviewedReportEvidenceBundle` objects. Bind each
   record to the plan's separate reviewed locator and exact selected-target use. The latter means
   inclusion in this report, not that a common source applies only to this program or that every
   context fragment is itself a rule. Reject missing/unreviewed/mismatched record review entries.
6. Each review entry carries exact OfficialEvidenceBindings, official heading path, manual anchor,
   physical/printed page, source role, use (`basis` or `context`), stage and reviewed target ID.
   Verify bindings match policy context records completely, not only Fact keys. Review-image hashes
   are historical design provenance, not runtime evidence or a reason to skip checking the PDF/KB.
7. Topic composition uses only approved plan entries. Rule IDs, topic/material, basis records,
   required context records and predicate/effect identity must equal the pinned MAT policy.
   Repeated records must be identical in their complete bindings/review snapshots. No generic
   'later document always overrides' rule. Unknown relations, missing context or source drift fail
   the whole invocation, never return a plausible subset report.

The evidence result `ReviewedMaterialSliceEvidence` has schema_version1.0,
artifact_role=reviewed-material-slice-evidence, production_enabled=false,
authority=reviewed_material_slice, coverage=partial, plan_id/revision/sha256, policy_sha256,
target, candidate binding, full source identities, ordered records, reviewed relations and
slice_validation_status=verified. Each record retains its original Fact binding/text/pages,
printed label, capture provenance, raw scope/section state and separate reviewed locator/use.
This gate is derived only after the checks above; a deserialized status is not sufficient trust.
No independent evidence store/corpus or fake document-level quality approval is created.

Provide one bounded summary at checkpoint1: changed files, pure tests, remaining uncertainties
and budget. Do not run an intermediate real import/preview simply to populate the checkpoint.

## Checkpoint 2: report assembly and CLI

Request is the existing `MaterialConditionRequest`1.0. Revalidate request and trusted inputs;
use existing normalization, complete target filtering and profile conflict checks. Wrong target
returns `not_covered`, no topic results or source quotes; a conflicting profile returns
`target_mismatch`, sorted conflict_fields and no results. Malformed input fails without partial
stdout. A valid unsupported selection cannot silently fall back to another school or route.
Preflight all requests after plan/policy pin validation and before candidate/PDF I/O. If no request
matches, emit only the non-covered/mismatch envelopes with empty evidence and topic lists; do not
read source assets. A mixed batch audits the approved slice once for matching requests only.

Use the accepted pure condition evaluator (not the MAT-01 CLI). After evidence validation, map
its status and pinned effect generically:

| Condition | Policy effect | Report disposition |
| --- | --- | --- |
| matched | required | submission_required |
| matched | not_required | submission_not_required |
| not_matched | either | rule_not_applicable |
| needs_information | either | needs_information |

Never map not_matched to submission_not_required. Unknown fields remain visible; if the condition
is already false, do not demand unrelated missing facts as a prerequisite. No applicant eligibility,
application readiness or 'all documents complete' overall score. The client cannot supply result
status, citations, plan effects or policy digests to determine the output.

`ReviewedMaterialSliceReport`1.0 must contain artifact_role=reviewed-material-slice-report,
production_enabled=false, audience=teacher_preview, authority=reviewed_material_slice,
coverage=partial, historical_reference=true, plan/policy/request/evidence digests, full target,
status (`evaluated`/`not_covered`/`target_mismatch`), conflict_fields, ordered topic_results,
qualified evidence inventory, source identities, and explicit coverage limitations.
Each topic result contains rule/topic/material IDs, application stage, condition status,
disposition, missing_fields, reviewed Chinese explanation and limitations, and qualified
basis/context citation keys. No caller-supplied path or full ApplicantProfile snapshot is output.
The citations carry document ID, KB/PDF hashes, Fact ID, original-text hash, physical pages,
printed labels, source title/official URL and reviewed locator; quote text remains byte-exact
from Facts. All citations resolve, and all required context is present; report counts are derived.

Report identity/digests derive from canonical bound inputs, excluding clock time and local paths.
Input reordering cannot change canonical output. The report loader must recompute against external
trusted plan/policy/request/evidence inputs, not validate a self-contained forged report's own
claimed hashes or statuses. Revalidate mutable nested snapshots before use.

The Markdown renderer consumes a validated report. Include target/year/route, the literal header
“募集要项参考报告（历史固定切片／部分材料主题）”, topic results, missing facts, and official evidence.
Chinese explanatory prose is labeled separately from Japanese quotations. Keep E08 fragments
separate with table roles; never present the stitched table cells as one continuous official quote.
E07 is a note, not an extra actionable checklist item. Include physical vs printed page labels,
full coverage limitations and official URLs; no local filesystem paths, raw HTML injection,
tracking resources, LLM output or links built from applicant text. Escape Markdown/URLs safely.

The CLI accepts the explicit trusted input paths plus repeated `--request`; `--format jsonl`
is default and emits one canonical envelope per request containing `report` and `markdown`.
Audit inputs once, validate the entire batch and assemble every result before any stdout.
`--format markdown` accepts exactly one request for teacher-readable stdout; no second evaluator.
All output can be captured by the operator; the tool does not silently persist profiles or files.
Failure exits nonzero with a stable generic code and no profile facts or partial output.
The module is `jgrad_admission_rag.reasoning.material_slice_report_cli`; flags are
`--plan`, `--trust`, `--policy`, `--policy-trust`, `--seed`, `--candidate-root`, `--pdf-dir`,
repeatable `--request` and optional `--format`. The PDF directory contains existing
`<source_pdf_sha256>.pdf` files; candidate paths use their existing original location.
No copy of source assets into a worktree and no call to the old importer is needed.

## Concrete report semantics for the pinned three topics

- English: matched -> this selected route does not require score-sheet submission; never state
  English examination exemption. E02 basis; E01/E03 and all fragment context retained.
- Checklist: matched -> this checklist form need not be submitted; still consult it to prepare
  documents. Do not claim all materials are waived. E05 basis; E04 context.
- Work/study plan: true/true -> submit the plan as a PDF through the online application system
  during the application period, without inventing dates. E06/E08 basis with table group/row context.
  false/null -> this conditional rule does not apply, not a general exemption. null/null -> ask
  for the two missing employment facts. E07's separate enrollment-stage consent and incomplete
  reference to11.(8) stay visibly contextual; no complete consent rule is claimed.

## Acceptance and meaningful tests

1. All9 employment combinations, unconditional English/checklist topics and profile/target
   negatives preserve MAT-01 semantics; output status mapping is separately tested.
2. Small synthetic candidate/seed/PDF fixtures prove pin/hash/text/page/identity/target mismatch,
   unknown/missing review, dropped table header, changed relation endpoint, repeated-record conflict,
   missing context, duplicate/extra files, path escape/reparse and forged output fail closed.
3. A second synthetic institution with a variable number of topics uses the same algorithms.
   No three-topic cardinality in implementation, school-name conditional or copied predicate logic.
4. Verify exact quotation and complete source inventory, no E07 duty promotion, no false->exemption,
   no English-test exemption, no full-checklist claim, Markdown injection/escaping and atomic batches.
5. Focused existing profile/condition/applicability/materials/report/evidence tests and frozen
   implementation gates pass. Do not run unrelated real-asset tests. CI passes exact final head.
6. Real evidence: three fixed synthetic requests produce three inspectable reports from the existing
   accepted candidate and3 locked PDFs. Provide command/head/input-output hashes, context matrix,
   readable report sample, timing/resource ledger and before/after source/candidate hashes+mtime.
   The teacher-facing sample must be clear without raw IDs; technical details may be separate.
7. Independently review evidence source text, scope/table-stage attribution and actual artifacts,
   not just test counts. No real student data in fixtures, output or GitHub.

## Resource envelope (new report work, not a reset of old experiments)

Design review in this phase: at most one read-only audit session of the existing five-file candidate,
three PDF hashes/page counts and four already-retained page images. No import rebuild or parser call.
The four retained page images were visually inspected once during design; no new renders requested.

RPT-01 implementation/acceptance: at most **3 real report CLI invocations total**, development≤2
and independent reviewer1 reserved. Each invocation may batch the three fixed requests and audits
the sources once; ≤60 seconds, cumulative≤3 minutes, each envelope≤512KiB, total output≤2MiB.
Use an external timeout and record an attempted invocation even on failure. Reuse the same retained
output when inputs/head do not require another authorized run. No permanent workers, full-tree asset
scan or separate real evidence CLI run. Pure/synthetic tests do not consume real-call budget.
If more real runs are needed, return to design with retained evidence, not a fresh ledger.

This budget covers the new report source audit and assembly. IMPORT-01 stays4/4 exhausted and
MAT-01 CLI stays3/3 exhausted. No reimport, candidate byte generation, old experiment rerun,
embedding, OCR, MinerU, model download or paid call. Do not copy PDFs/KB/indexes into worktrees.
One small ignored output location can retain the three envelopes and resource/audit summary;
the report evidence projection is embedded or in memory, not another large persistent asset tree.

## Handoff, deadline and rollback

Record Ready -> In progress -> Awaiting review in the original Issue's one updatable handoff.
Include branch/head, completed checks, remaining failures, resource use and next owner. Keep the
two checkpoints bounded; prioritize correctness over the 2026-09-29 demonstration aspiration.
If evidence/report assembly cannot be completed within a focused day, report the concrete blocker
and split at checkpoint1. Do not start UI/highlighting or make provisional findings look official.

Rollback removes only new report modules/CLI and disables this plan. No legacy schema changes,
candidate migration or artifact deletion. Next design after acceptance: local dual-school
selection and copyable report UI; highlighter is an optional separate locator proof. Neither is
Ready under this Spec. Preserve M13 pause, closed #177 and reference_only assistant responsibility.
