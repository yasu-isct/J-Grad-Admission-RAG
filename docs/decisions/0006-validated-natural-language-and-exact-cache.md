# ADR 0006: Retain validated natural wording and cache exact successful responses

Status: Accepted for M10-07

## Context

The M9 boundary correctly treated the model as non-authoritative, but it discarded every generated
claim string and rebuilt the answer from server templates. The M10 product route also generated once
per supported subquestion. That made wording mechanical, multiplied paid calls and failure points,
and repeated the same work for an identical request.

Keeping arbitrary model text would weaken the citation boundary. Matching numbers or evidence IDs
alone is not enough: a sentence can contain allowed values while asserting an unsupported relation,
such as converting TOEIC 840 directly to a 100-point final score.

## Decision

The original `/v1/grounded-answers` behavior and M9 release gate remain unchanged. The product
`/v1/natural-language-answers` route uses a separate consolidated boundary:

1. one bounded question-understanding call decomposes the request;
2. every retrieval and reviewed-rule operation completes locally;
3. the server hard-filters every record to global/university, matching college, or matching
   department/program scope before it can enter the model request, then fairly deduplicates the
   remaining evidence and creates typed, request-local claimable propositions;
4. one final provider call may phrase those propositions;
5. the server validates claim kind, exact evidence set, subject, controlled predicate, numbers,
   forbidden relations/outcomes/negation, scope and citation closure;
6. only validated claim text is retained, and authoritative page provenance is restored by the
   server.

Coverage gaps are server-owned dispositions, not negative rules. “No JLPT/J.TEST rule found” may
not become “JLPT is not required” or “J.TEST is rejected.” A department maximum may not become a
score-conversion or admission conclusion. The offline provider remains an explicitly labelled
deterministic renderer.

An exact response cache wraps the online analysis boundary. Its SHA-256 key is derived from
canonical request, target/profile, source/index/reviewed-plan/page-scope identity,
provider/model/revision, and prompt/schema/pipeline/validator/projector versions. The cache is
bounded TTL/LRU process memory with single-flight misses. Only fully validated success is inserted.
The stored value is a minimal projection containing validated public claims, safe citation keys and
subquestion-to-claim dispositions; it contains no raw question, Applicant Profile, retrieval query,
official evidence text, or provider response. Evidence display records are rebuilt from current
authoritative state on a hit. If online analysis differs from deterministic key-time analysis, the
response is returned but not cached. Provider and validation failures are never cached. Restart
clears it, and nothing is written to disk or logs.

## Consequences

- A new request uses at most one analysis and one final-generation call; an exact hit uses zero.
- Natural model wording can reach the user without making the model a fact or citation authority.
- Public responses omit rule/finding IDs and full source hashes while retaining official evidence
  pages and PDF navigation.
- Adding a new semantic claim type requires a new narrow typed predicate and negative tests. It
  cannot be enabled by prompt changes alone.
- Reviewed categories without a narrow typed predicate use a conservative exact-evidence
  proposition: only active/confirmed findings whose complete citations occur in the bounded,
  target-scoped retrieval may surface, and their official text is retained verbatim.
- The first cache is intentionally conservative: semantically similar wording does not share an
  answer, and restarts lose all entries.
- Live-provider behavior still requires separately authorized acceptance; offline tests cannot
  establish external API availability or latency.
