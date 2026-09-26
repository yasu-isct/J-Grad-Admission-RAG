# M10-08: Simplify the natural-language assistant to one-call local QA

## Decision

The natural-language assistant is an optional convenience feature. The authoritative structured
material, reviewed rules, applicant comparison, and M9 grounded endpoint already exist locally.
The assistant therefore does not need to reproduce or validate the complete M9 evidence chain.

Replace the two-call typed AnswerFacts/Claims product path with a simple QA presentation layer over
bounded local retrieval. Keep M9 and all structured features unchanged.

## Required behavior

1. Use deterministic local question normalization. Do not call an online question-understanding
   model.
2. Search the selected locally indexed admission document. Known exam aliases may be decomposed;
   other questions use the original question as the retrieval query.
3. Make at most one online generation call on a cache miss and zero on an exact cache hit.
4. Use a minimal strict output schema containing only `answer`.
5. Do not require model-generated Claim IDs, Fact IDs, page numbers, hashes, citations, or evidence
   closure.
6. Send at most 16 local records and 60,000 characters. Send no Applicant Profile values, paths,
   credentials, names, contacts, complete PDF, document/Fact IDs, pages, or hashes.
7. No Web Search, tools, file upload, streaming, or outer retry loop.
8. Prompt the model to use only supplied local records and to express missing coverage without
   inferring rejection, exemption, or admission guarantees.
9. Label the answer as a lower-assurance reference. Direct qualification decisions to the existing
   structured features and official source.
10. If generation fails, return clearly labelled bounded local excerpts instead of a blank 502.
    Do not cache this fallback.
11. If retrieval returns nothing, answer that the selected local material did not contain enough
    relevant content and make no paid call.
12. Preserve the exact-cache privacy boundary and provider status behavior.

## Acceptance

- arbitrary admission questions reach local retrieval instead of a closed intent rejection;
- online question-analysis call count is zero;
- fresh answer generation call count is at most one;
- exact cache repeat adds zero calls;
- the provider request excludes Applicant Profile and internal provenance;
- malformed/refused/timed-out generation returns a local fallback and is not cached;
- DeepSeek and OpenAI adapters both support the minimal schema;
- missing keys leave ordinary structured service readiness available;
- M9 Grounded RAG release gate remains green;
- full offline CI, formatting, compile, and independent review pass;
- real DeepSeek acceptance requires a new explicit one-call authorization.

## Non-goals

- proving the complete semantics of generated prose;
- model-generated citation closure;
- moving structured qualification decisions into the assistant;
- Web Search or arbitrary provider endpoints;
- adding a new university or PDF in this issue.
