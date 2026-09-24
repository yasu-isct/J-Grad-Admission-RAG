# ADR 0005: Grounded generation and citation boundary

## Status

Accepted

## Context

Hybrid retrieval returns candidate evidence, and reviewed rules determine applicability. A
language model is useful for selecting and arranging those accepted records, but it cannot be
allowed to assign official provenance, reinterpret rule status, or turn similarity into an
eligibility decision. Model-visible evidence also must not expose authoritative identifiers that a
model could invent or alter.

## Decision

The model is a replaceable language-generation component only. The server gives it opaque,
request-local evidence IDs and closed reviewed findings. The server privately binds each opaque ID
to one EvidencePack record and, after generation, reconstitutes document ID, Fact ID, exact source
pages, PDF SHA, KB SHA, and evidence role.

The orchestration accepts only one source-consistent EvidencePack and CitedAnswer. The selected
target must match retrieval scope. Reviewed citations must already close against pack evidence, and
the complete reviewed state is copied into the GroundedAnswer independently of model output.

Citation or state failure rejects the entire generated answer. We do not delete isolated claims or
fall back to uncited prose because either policy could change the meaning of the remaining text and
hide a provider failure. Explicit conservative abstention remains valid.

Provider replacement occurs behind the existing `GenerationProvider` contract. Provider identity
is server-assigned; timeout, retries, storage, structured parsing, and credentials stay adapter
concerns. Orchestration neither imports a particular SDK nor adds another retry loop.

Applicant facts are caller-supplied untrusted data. They may enter a configured provider request,
but they are never official evidence, never receive citations, and are not logged or persisted by
this layer. Real external processing requires explicit approval and synthetic data during
acceptance testing.

Retrieval similarity is only candidate ranking. Rule applicability remains the output of the
reviewed deterministic reasoning chain because ranking cannot establish scope, exceptions,
overrides, missing profile fields, material acceptance, final eligibility, or admission.

## Consequences

Every returned factual or reviewed claim has deterministic, server-owned provenance, while
applicant statements remain visibly non-authoritative. Cross-document/year/hash/page references and
provider-authored authority fail closed. The output is more constrained than free-form RAG and may
abstain more often, but downstream API/UI work receives a self-auditing contract instead of prose
that merely looks cited.

