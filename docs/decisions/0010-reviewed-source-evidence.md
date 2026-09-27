# ADR 0010: Reviewed source excerpts before new-school KB construction

Status: Accepted design boundary; implementation and production mapping require independent review.
Owner: #191. Date: 2026-09-27. Supersedes no production schema.

## Problem and decision

M14 exposed missing clauses and uncertain structural relations. Approving a parser globally is
neither sufficient nor necessary to curate a bounded set of official evidence. Add a generic,
versioned **pre-KB reviewed evidence artifact** for explicit excerpts verified against exact PDF
pages, with separate source context, review notes and review provenance. Start with three GSFS
materials topics and eight records. No new extraction, rule engine, public evidence endpoint,
production KB, embedding or index belongs to the first implementation.

Manual transcription is allowed only when visibly attributed. It does not modify the PDF, old
parser result or frozen gold. It does not fabricate parser locators, source character offsets,
bounding boxes, Fact IDs or KB hashes. Where extraction is incomplete, source hash plus physical
page plus a human-readable anchor remains honest evidence for review; machine verification checks
identity, not the truth of a visual transcription.

The design reviewer here is an Agent; `reviewer_kind=agent` must remain explicit. Do not describe
this as human review, legal eligibility approval or a cryptographic signature. Repository review
and an expected artifact digest bind acceptance; a self-declared `reviewed` flag is insufficient.

## Artifact and authority boundary

Separate source text fragments from Chinese commentary and topic associations. Keep exact target
dimensions, source-set revision/digest, per-source PDF hashes and physical/printed page identities.
An ordered fragment list preserves boundaries; joining a header and a clause is not a contiguous
official quotation. A table record must retain required header/row labels and related conditions.
Review relations are explicit data, not inferred precedence such as “department always wins”.

The first query is an operator inspection of trusted reviewed content by exact target/topic.
It is not semantic search or an applicant decision. No `required`, `eligible`, exemption verdict,
complete-checklist flag or Applicant Profile evaluation is generated at runtime. Review notes are
not promoted into evidence. Missing/changed evidence fails closed; omitted topics are not negatives.

The loader verifies structure without I/O. An explicit auditor verifies caller-named PDF paths,
hashes and page bounds and returns verified references. Preview requires that audit and a trusted
expected artifact digest. No path scanning, fetching or rebuilding occurs on query. File paths
are operator inputs, never part of deterministic content identity or arbitrary public URLs.

## Integration plan and compatibility

EVID-01 is additive and isolated from public schemas. The future import step must first isolate
the ISCT builder profile, then map records to the existing per-document Facts/RetrievalUnits and
reviewed evidence chain, preserving a record-to-Fact lineage map. Cross-document relations stay
document-qualified. Explicitly review any schema change before implementation; this ADR is not
permission for an incompatible migration or to bypass current KB/text/page/scope checks.

Existing exact-source identity conventions, MS02 provenance and canonical serialization patterns
are reused. Existing 334/391 data, parsers and rules stay unchanged. A second synthetic institution
tests portability without downloading a second real dataset or copying school-specific code.

## Alternatives, limitations and rollback

Do not run MinerU again under the exhausted #177 budget. Do not patch the old parser with more
school-specific strings. Do not directly author a parallel applicant-answer store or inject manual
text as if the parser emitted it. A reviewed excerpt input preserves auditability while permitting
bounded progress; it does not eliminate later table, rule-scope and multi-source work.

Faithful transcription still requires reviewer inspection. Digests detect changes, not correctness.
Only the selected topics are covered; conditional intake and general eligibility remain unresolved.
Rollback removes only the new optional evidence tooling/data; no runtime pointer or asset changes.
