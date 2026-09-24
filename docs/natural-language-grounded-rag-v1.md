# Natural-language grounded RAG API and page v1

`POST /v1/grounded-answers` is the local end-to-end boundary for a natural-language question. It accepts a strict question, the target already selected in the four-step page, and the applicant fields currently held by that page. The endpoint never accepts caller-supplied evidence, rule findings, document hashes, citation provenance, provider identity, or source links.

## Server trust path

For every request the service selects exactly the requested reviewed document, audits its current corpus/index bindings, and runs hybrid retrieval across that document. The search result is projected into an `EvidencePack` with exact document, KB, PDF, row, Fact, page, scope, ranking, embedding, and lexical provenance. The question is separately parsed through the reviewed intent catalog. The server then builds the strict applicant profile and deterministic `ApplicantReport`/`CitedAnswer` from the matching reviewed plan and evidence bundle.

Only after those steps succeed does `run_grounded_rag` receive the request-local question, target scope, EvidencePack, and reviewed state. M9-03 closes every returned claim against opaque request-local evidence IDs and then restores only server-owned authoritative provenance. Cross-document, cross-hash, cross-scope, unknown-reference, incomplete, malformed, and unsupported claims fail closed; no partial answer is returned.

The response includes the immutable `GroundedAnswer`, a cited-evidence presentation inventory, a verified local-PDF route when configured, and the separately labelled official webpage URL. Provider output is data, not markup.

## Lifecycle and offline behavior

Embedding and generation providers are initialized once during the FastAPI lifespan and cleared at shutdown. Calls run outside the event loop and each provider has its own lock because providers are not assumed to be thread-safe. A failure to initialize the generation provider leaves the rest of the service available but makes the grounded endpoint return a privacy-safe `grounded_service_unavailable` response.

The packaged demo uses `ReviewedStateGenerationProvider`. It is deterministic, offline, and selects reviewed findings without inventing prose. It performs no network request, paid API call, key lookup, or model download. Production provider selection remains an explicit dependency-injection decision.

## Stable failures

Input and reviewed-scope failures return 422. Corpus/evidence/rule reconciliation conflicts return 409. Provider refusal, incomplete or malformed output, invalid citations, and unsupported claims return 502. Provider unavailability returns 503 and provider timeout returns 504. Error envelopes contain allowlisted codes and generic messages only; questions, applicant data, evidence text, provider payloads, exception contexts, and local paths are not echoed.

## Browser boundary

The natural-language area is outside the four-step application flow and reuses its current target and applicant form values at submission time. Target or profile changes abort an in-flight request and clear the answer. A 15-second client timeout, explicit retry, and request snapshot prevent stale results from appearing.

Generated claims are inserted with `textContent`. The page does not use HTML/Markdown rendering, `innerHTML`, `insertAdjacentHTML`, cookies, `localStorage`, or `sessionStorage`. Each official or reviewed claim has citation buttons opening the existing evidence drawer; the drawer exposes verified PDF page links and the official webpage as separate actions. Question, answer, retry, and applicant state are memory-only, so reload clears them.
