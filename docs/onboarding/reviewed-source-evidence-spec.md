# EVID-01: inspect reviewed GSFS material evidence

Owner: design main #191. Execution: [#202](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/202),
[M15](https://github.com/yasu-isct/J-Grad-Admission-RAG/milestone/15). Development: user-assigned
milestone Agent. One active Issue only. Ready after this design merges.
Dependencies: accepted MS-01 #195, MS02 #197 and M14 reject closeout #177 / PR #200.
Design authority: [ADR 0010](../decisions/0010-reviewed-source-evidence.md).

## Background and observable goal

Deliver an operator-facing command that can inspect three named topics for the exact fixed GSFS
target: `english-score-sheets`, `checklist-submission`, `work-study-plan`.
Each result contains the actual Japanese excerpts, separately labeled Chinese review notes, exact
source/physical-page references and scope/coverage limitations. Use the eight-record
[design-reviewed seed](gsfs-material-evidence-seed-v1.json). This is not applicant advice or a
complete checklist. Wrong target/topic and invalid evidence must not produce a plausible answer.

## Scope and non-goals

Implement a reusable strict schema, canonical serializer, pure loader, explicit read-only artifact
audit, and small CLI/operator preview. School variation belongs in versioned input data. Module
layout/command name is developer choice; document one copyable invocation per topic.

No new PDF/model download, parser experiment, whole-PDF extraction, production dependency install,
KB/Fact/vector/index build, cloud/paid call, API/UI change, Applicant Profile judgment, institution
registry redesign or production rule/schema modification. The closed MinerU runner stays closed.
No standalone chatbot/search engine or arbitrary phrase-to-answer branches. No editing ISCT's
five-material policy or adding GSFS identifiers to ISCT-specific extraction code.

## Input contract and review semantics

Use the seed fields as the minimal v1 contract (a non-public pre-KB artifact). Keep:

- schema version, artifact role, `production_enabled=false`, stable bundle ID/revision;
- full MS-01 target tuple and explicit source-set ID/revision; exact-byte SHA-256 references to
  the source manifest and MS-01 target examples, so selection never relies on a friendly label;
- source ID/PDF hash, physical page, printed label, local anchor and ordered text/context fragments
  per record; topic membership is data, not a school-name conditional;
- `capture_method=manual_transcription`, normalization policy, reviewer kind/id/date/method,
  record revision and relationships; `parser_locator`, bbox, Fact ID and KB hash remain null;
- reviewer commentary distinct from source fragments; bundle-wide limitations and topic-specific
  caution notes. Do not merge fragments into a falsely contiguous quote.

All target fields must match, including school/program/degree/year/route/schedule/intake. Unknown
or missing dimensions are not wildcards. Check exact source-set membership and source PDF hashes,
record/fragment IDs, positive integer pages (reject booleans), unique references, valid topics,
nonempty source text and review metadata, relation endpoints and same-target bindings. The
employer-consent record stays a separate enrollment-stage clause; no generic “all applicants” rule.

Only cosmetic whitespace and line-wrap joining are allowed under the recorded policy; do not
normalize away punctuation, digits or negation. Changes to source text, scope, fragments, notes,
relations or source-set identity create a new bundle revision/digest requiring review. Canonical
UTF-8/LF sorted serialization is deterministic; use existing conventions, not a dependency.

The trusted revision/digest is supplied explicitly from the reviewed repository acceptance record,
not read solely from an untrusted bundle's own `reviewed` field. Before implementation acceptance,
the seed is design-reviewed only; design main reviews the converted content and records the exact
accepted digest in the PR. This is a governance/integrity check, not a digital signature or proof
that an AI transcription is factually correct. Developer must not self-label a human reviewer.

## Read-only audit and output

Separate loading from auditing: the pure loader never opens PDFs. The auditor receives an explicit
source-ID-to-local-path mapping; verify manifest identity, byte hashes and page counts with existing
PDF metadata support (no text extraction). For these three topics require all three core PDFs:
common guideline, department guide and additional-material sheet. The conditional intake PDF is
outside this slice and must not be read or inferred as covered. Its missing local path does not
break these topics; its membership in the locked source manifest remains intact.

No scanning parent directories or following a source ID as a filesystem path. Audit failure means
no verified preview. A CLI invocation must bind its preview to freshly audited content/bytes;
do not reuse a cached success after evidence or source changes. Unknown topic or mismatched target
returns explicit `not_covered`/non-success with no cross-target fallback. Missing PDF, changed hash,
invalid schema/digest and dangling relations return distinguishable safe errors and nonzero exit.

Emit deterministic JSON and a readable console/Markdown preview; no separate generated production
copy. Show historical target, topic, ordered excerpts, physical page and optional printed label,
official URL with `#page=N` derived from verified source metadata, and labeled review notes. Bbox/
highlight support is unknown. Public product routes remain unchanged. Query performs zero parser,
model, network, KB/index operations and has no side effects other than explicitly requested output.

## Concrete real-data acceptance

1. English topic returns common p6's department-dependent requirement, department p28's explicit
   no-score-sheet clause, and additional p1's sending-instructions footer as a cross-reference.
   It does not claim no English assessment of any kind or create a submission duty from the footer.
2. Checklist topic returns department p28's instruction to consult the checklist and p40's explicit
   no-submission notice with master's/general heading. It does not waive the listed documents.
3. Work/study topic shows employed-and-retaining-employment conditions, additional p1's upload
   header and exact row, plus the separate employer-consent clause at enrollment. It never evaluates
   an applicant automatically or labels the employer consent as an application upload.
4. A change to any target dimension (ISCT, doctoral, special oral, B, October, another year/program)
   is refused as uncovered. A different source revision or missing core PDF yields no verified output.
5. Wrong page/printed-page substitution, edited negation, deleted condition/context, stale trusted
   digest, duplicate IDs and dangling relations fail validation/audit as applicable. Semantic
   correctness is separately reviewed, not “proven” by substring matching against faulty extraction.
6. A tiny synthetic second-school fixture uses the same implementation with different IDs and
   topic data. No real download or duplicated school-specific path. MS02 contracts remain unchanged.

## Checkpoints, tests and evidence

Keep the same milestone chat; do not execute all future roadmap steps. At three checkpoints record
what changed, evidence paths/digests and remaining work: (a) contract + focused tests, (b) three real
previews + source hashes, (c) PR handoff. Only escalate back to design for a boundary change, not
routine implementation choices. Aim for one to two focused development days; stop and report a
scope overrun instead of quietly adding a KB builder or general rule engine.

Test pure-load I/O isolation, canonical stability, target isolation, hostile/invalid bindings,
stale digest, missing/changed source, relation/context completeness and zero downstream calls.
Use synthetic PDFs where page/hash changes are needed. Real evidence: independently verify three
existing source hashes; demonstrate all three previews; compare the eight excerpts with the four
existing rendered page images and explicitly record corrections before requesting acceptance.
Do not silently edit the seed or gold to make tests pass. Include evidence limitations in the PR.
Run focused tests for the new tooling and MS02 compatibility, plus normal CI. Do not run unrelated
full model/browser suites or hash every model weight for this change.

Artifact impact: zero new extraction/model calls, KB/index builds/downloads/copies. Tracked changes
are small code/tests/review data; previews stay in an explicitly named ignored output directory.
Record unchanged git paths for production configs and hash current protected assets if any code
path touches them; the intended path does not. No changes to 334/391 identities or M13.

## Failure, rollback and release

If a clause cannot be faithfully transcribed or its context is ambiguous, mark the topic incomplete
and return to design; never guess or widen scope. Rollback removes/reverts only the additive tool
and review-data files. Existing assets and runtime pointers are untouched. Submit one PR with
tests, real previews, source/review digests and known limits; design main reviews before merge.
Subsequent KB/rule/API/UI tasks remain blocked until this Issue is accepted and their Specs exist.
