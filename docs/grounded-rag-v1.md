# Grounded RAG orchestration v1

M9-03 connects one already-built `EvidencePack`, one exact reviewed `CitedAnswer`, caller-supplied
applicant facts, and a replaceable `GenerationProvider`. It does not add a second retrieval or rule
engine.

```text
EvidencePack + CitedAnswer + explicit target/applicant facts
  -> detached input validation
  -> server-owned opaque evidence binding
  -> checked GenerationProvider
  -> deterministic citation hydration
  -> GroundedAnswer
```

## Input closure

The orchestrator revalidates every input before provider activity. The EvidencePack query becomes
the generation question, so a caller cannot substitute a different question after retrieval. The
explicit generation target must match the pack's scope preference and any hard scope-target filter.
Its authoritative document ID must equal the pack runtime document, independently of its display
label. The reviewed answer must match the pack's document ID, KB SHA, and PDF SHA. Every reviewed
citation must then match one pack record by document ID, Fact ID, exact sorted source pages, and
primary/reference role. Every reviewed source rule must still have a citable finding.

An empty pack or a reviewed rule without official evidence fails as insufficient/mismatched
evidence before the provider is called. Retrieval scores remain diagnostics and never become rule
status or confidence.

## Opaque provider boundary

Primary evidence is ordered before attached reference evidence. The server assigns contiguous
`evidence:NNNN` IDs and retains the binding to document ID, Fact ID, pages, KB SHA, PDF SHA, and
role. Only the opaque ID, role, evidence text, and scope label cross the provider boundary.

Reviewed findings are projected deterministically from `CitedAnswer`: original applicability
status, resolution disposition, subject, and scope remain server-owned statement data. Citable
interaction warnings become `needs_review` findings. Applicant statements remain explicitly typed
and carry no official citation.

## Whole-answer validation policy

`generate_checked` validates claim types, opaque references, exact finding coverage, missing fields,
and pending/review state. M9-03 then replaces every opaque factual reference with a
`GroundedCitation` containing the authoritative document/Fact/page/hash binding. Official claims
require exactly one citation, reviewed claims require the exact finding citation set, and applicant
claims cannot carry citations.

Any unknown ID, changed finding evidence, source mismatch, invalid claim, or rewritten reviewed
state rejects the whole answer. The orchestrator does not delete individual claims, downgrade them
silently, or return free text. A provider may conservatively abstain; an empty answer must remain an
explicit review state.

`GroundedAnswer.reviewed_state` retains the complete validated `CitedAnswer`, including findings,
interaction warnings, process notices, and missing-information entries. The model cannot replace
that state. Canonical grounded-answer bytes use sorted compact UTF-8 JSON plus one LF.

## Privacy and operations

Public failures contain only allowlisted codes and fixed messages. Input validation, provider
calls, SDK failures, output validation, and citation hydration raise stable errors only after
leaving exception handlers; sensitive payloads are retained in neither `__context__` nor
`__cause__`. This layer performs no logging or persistence.

The deterministic fake remains the offline default and may return an explicit uncited abstention.
No model or paid API call is required by this contract. The OpenAI adapter remains optional and a
real request still requires explicit per-run approval with synthetic applicant data.
