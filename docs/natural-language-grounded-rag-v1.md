# Natural-language grounded RAG API and page v1

`POST /v1/grounded-answers` is the local end-to-end boundary for a natural-language question. It accepts a strict question, the target already selected in the four-step page, and the applicant fields currently held by that page. The endpoint never accepts caller-supplied evidence, rule findings, document hashes, citation provenance, provider identity, or source links.

## Server trust path

For every request the service selects exactly the requested reviewed document, audits its current corpus/index bindings, and runs hybrid retrieval across that document. Retrieval returns at most 12 ranked records from at most 48 candidates; the depth never expands to the document row count. The search result is projected into an `EvidencePack` with exact document, KB, PDF, row, Fact, page, scope, ranking, embedding, and lexical provenance. The question is separately parsed through the reviewed intent catalog. The server then builds the strict applicant profile and deterministic `ApplicantReport`/`CitedAnswer` from the matching reviewed plan and evidence bundle.

Only after those steps succeed does `run_grounded_rag` receive the request-local question, target scope, EvidencePack, and reviewed state. Every exact citation required by the reviewed answer must occur in the bounded retrieval result; otherwise the endpoint returns `insufficient_evidence` without calling the generation provider. The generation boundary independently rejects more than 16 evidence records or more than 60,000 evidence/scope characters. M9-03 closes every returned claim against opaque request-local evidence IDs and then restores only server-owned authoritative provenance. Cross-document, cross-hash, cross-scope, unknown-reference, incomplete, malformed, and unsupported claims fail closed inside each M9 grounded answer.

M10 adds a product route above this unchanged boundary. It analyzes and splits at most eight
subquestions, then invokes this closed path separately for each substantive subquestion. An
insufficient or unsupported sibling receives an explicit no-clear-evidence/clarification state
without deleting other independently validated results. Provider/citation failures still fail the
request closed. See [Natural-language RAG productization v1](natural-language-productization-v1.md).

The response includes the immutable `GroundedAnswer`, a cited-evidence presentation inventory, a verified local-PDF route when configured, and the separately labelled official webpage URL. Provider output is data, not markup.

## Lifecycle and offline behavior

Embedding and generation providers are initialized once during the FastAPI lifespan and cleared at shutdown. Calls run outside the event loop and each provider has its own lock because providers are not assumed to be thread-safe. A failure to initialize the generation provider leaves the rest of the service available but makes the grounded endpoint return a privacy-safe `grounded_service_unavailable` response.

The packaged demo uses `ReviewedStateGenerationProvider`. It is deterministic, offline, and selects reviewed findings without inventing prose. It performs no network request, paid API call, key lookup, or model download. Production provider selection remains an explicit dependency-injection decision.

## Stable failures

Input and reviewed-scope failures return 422. Corpus/evidence/rule reconciliation conflicts return 409. Provider refusal, incomplete or malformed output, invalid citations, and unsupported claims return 502. Provider unavailability returns 503 and provider timeout returns 504. Error envelopes contain allowlisted codes and generic messages only; questions, applicant data, evidence text, provider payloads, exception contexts, and local paths are not echoed.

## Browser boundary

The natural-language area is outside the four-step application flow and reuses its current target and applicant form values at submission time. Target or profile changes abort an in-flight request and clear the answer. A 15-second client timeout, explicit retry, and request snapshot prevent stale results from appearing.

Generated claims are inserted with `textContent`. The page does not use HTML/Markdown rendering, `innerHTML`, `insertAdjacentHTML`, cookies, `localStorage`, or `sessionStorage`. Each official or reviewed claim has citation buttons opening the existing evidence drawer; the drawer exposes verified PDF page links and the official webpage as separate actions. Question, answer, retry, and applicant state are memory-only, so reload clears them.
