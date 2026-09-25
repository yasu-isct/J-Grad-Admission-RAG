# Natural-language RAG productization v1

M10-01 adds a product-facing boundary above the M9 grounded-answer endpoint. It preserves M9 as
the citation authority rather than weakening its whole-answer validation.

## Explicit modes

Both `jgrad-demo` and `jgrad-serve` accept:

- `--generation-provider reviewed-state-offline` (default): deterministic question normalization,
  reviewed-state generation, no key, network request, or model download;
- `--generation-provider openai-responses --generation-model <model>`: OpenAI Responses API for
  Structured Outputs question analysis and the existing citation-constrained generation draft;
- `--generation-provider deepseek-responses --generation-model <model>`: DeepSeek's
  OpenAI-compatible Responses API through an explicit first-party adapter. Only
  `deepseek-flash` and `deepseek-v4-pro` are accepted.

The online adapter reads only `OPENAI_API_KEY`, uses the official SDK default endpoint, sends
`store=False`, and bounds timeout, output tokens, and SDK retries. There is no configurable base
URL and no retry loop around the SDK. Provider construction makes no request.

The DeepSeek adapter reads only `DEEPSEEK_API_KEY` and pins `https://api.deepseek.com` in code.
It never reads `OPENAI_API_KEY`, and no CLI, environment, or request option can replace the base
URL. It uses non-streaming `responses.create`, a strict `text.format` JSON Schema, local Pydantic
validation, bounded output/timeout/SDK retries, and no tools. See
[DeepSeek Responses provider v1](deepseek-responses-provider-v1.md).

If online mode is selected without a usable key, the service continues to report ready when its
corpus, retrieval, and structured report functions are healthy. `GET /v1/generation-status`
reports `configured=false` and the browser displays `在线生成服务未配置` for OpenAI or
`DeepSeek 在线生成服务未配置` for DeepSeek; the natural-language
route returns a privacy-safe 503. The service never silently falls back and labels offline rules as
online AI.

## Strict analysis boundary

`QuestionAnalysis` is a frozen, extra-forbid Structured Outputs schema with detected language,
normalized question, explicit corrections, requested intents, ordered subquestions and retrieval
queries, mentioned exam types/scores, target-scope mentions, missing context, and unsupported
parts. Subquestion IDs are contiguous and all lists are bounded and canonical.

Before an online call, the server builds a request-local semantic constraint from its deterministic
normalizer and sends it beside the untrusted question. The Structured Output must preserve that
minimum constraint, but it may quote an exact source token and correct it to a closed canonical exam
term. Additional corrections accept only an existing alias, a single insertion/deletion, or an
adjacent transposition such as `toiec` → `TOEIC L&R`; substitutions such as `topic` → `TOEIC` and
changes to an already recognized exam are rejected. The server reapplies accepted corrections,
rebuilds every dependent field and subquestion, and requires the model result to match that derived
constraint exactly. A schema-valid response that otherwise changes the exam, language,
user-facing subquestion, or retrieval topic is rejected as malformed before retrieval. SDK and
validation exceptions are converted only after leaving their handlers, so private provider
payloads cannot remain reachable through an exposed exception context.

The deterministic fallback recognizes Chinese, Japanese, and mixed forms of TOEIC L&R, TOEFL iBT
and Home Edition, JLPT, and J.TEST. It decomposes the formal M10 acceptance question into alias
interpretation, score conversion/allocation, JLPT, and J.TEST questions. Prompt-injection requests
and admission guarantees are recorded as unsupported parts and are never followed.

The fixed M9 intent lexicon remains a reviewed downstream adapter. It is no longer the product
entry gate: analysis succeeds first, then every substantive subquestion receives bounded,
target-scoped local retrieval. Those results are fairly deduplicated into one request-local bundle
before reviewed-report reasoning and final generation. Scope preference affects ranking only, so a
separate hard boundary removes unknown and nonmatching college/department/program records before
the model call; the consolidated generator checks the same scope metadata again before invoking its
provider.

The user-facing subquestion and generation instruction follow the detected user language, while
the separate retrieval query remains concise Japanese for the reviewed Japanese source. The
retrieval query is never reused as a reason to switch a Chinese user's answer into Japanese.

## Partial-answer and trust policy

`POST /v1/natural-language-answers` reuses the selected document, college, department, intake,
schedule, and in-memory applicant form. A cache miss makes one bounded analysis call, performs all
top-12/candidate-48 hybrid searches and reviewed reasoning locally, and makes at most one final
generation call. The consolidated boundary permits at most 16 evidence records and 60,000
evidence/scope characters. It assigns new request-local opaque evidence and proposition IDs; the
model never receives Fact IDs, pages, hashes, paths, names, contacts, or the complete PDF.

An unsupported or insufficiently evidenced subquestion becomes `no_clear_evidence` with the fixed
message `当前审核资料中未找到明确依据。`; a clarification-dependent one becomes
`needs_clarification`. Other validated siblings remain visible. Provider outages, malformed
outputs, citation failures, and unexpected server conflicts still fail closed rather than being
misrepresented as missing knowledge.

Alias interpretation is labelled separately and explicitly says that normalization is not an
official acceptance conclusion. Affirmative claims must match a server-owned typed proposition.
The first controlled semantic predicate permits a natural statement of an exact department English
maximum only when its subject and sole numeric value match reviewed state and its complete evidence
set. Conversion relations, admission outcomes, negative requirements, named-exam inferences, and
extra numbers are rejected. Active, confirmed reviewed findings for dates, eligibility, fees,
contacts, and other supported categories may use exact-evidence propositions only when their
complete citation set is present in this request's bounded retrieval; the official evidence text
must remain verbatim. Pending, not-applicable, cross-scope, and partially retrieved findings do not
become affirmative claims. After
validation, server-owned document, Fact and page provenance is restored for the public evidence
drawer; hashes and internal finding/rule identifiers are not part of the public natural answer.

## Exact validated response cache

Before online analysis, the server applies its deterministic normalizer and computes a SHA-256 key
over canonical JSON. The key covers the exact request, normalized question and language, selected
target and applicant input, document/KB/PDF, reviewed-plan and page-scope state, manifest/policy and embedding
identity, analysis/generation schema and prompt versions, claim-validator/pipeline versions, and
generation provider/model/revision. The reviewed-evidence projector version is explicit. Only the
digest is held as the cache key.

The cache is process-local, concurrency-safe, single-flight, TTL-bounded, capacity-bounded, and
deterministically LRU-evicted. Only a response that completed all local validation is inserted.
Timeout, refusal, malformed output, invalid citation, unsupported claim, and other failures are not
cached. An exact hit returns the same answer and citations without either online call. The response
and page label the source as `live`, `cache_hit`, or `offline`, expose bounded timing and a short KB
identifier, and state that restart clears the cache. It is not a semantic or cross-user cache.
The cached value itself is limited to validated public claims, safe citation keys, and disposition
mappings. It excludes the raw/normalized question, Applicant Profile, retrieval queries, official
evidence text, and raw provider response. On a hit the evidence drawer is reconstructed from the
current authoritative reviewed state. A response whose online analysis differs from the local
key-time analysis is deliberately not inserted.

## Browser boundary

The browser fetches the actual generation status and never derives the label from marketing text.
It renders one consolidated natural answer, then the ordered subquestion dispositions. It shows
`DeepSeek 实时生成`, `已验证缓存回答`, or the explicit offline label together with provider/model,
timing, and a short KB version. Missing evidence and missing context are prominent. Reviewed scope,
missing fields, and limitations remain in collapsed `技术详情 / 审计信息`. Factual strings still use
`textContent`, and citations continue to open the verified evidence drawer and PDF page controls.

Question, profile, analysis, and answers remain request-local and browser-memory-only. The service
does not log or persist API responses, keys, questions, profiles, or generated output.

## Manual real-provider boundary

CI and ordinary local verification use fake/offline providers only. A real request is a separate
operator action that requires a locally set key, an explicit model, synthetic applicant data, and
advance authorization of an exact maximum call count. One new multi-intent request can consume at
most one analysis plus one consolidated generation call; an exact validated repeat consumes zero.
Authorization must still count every SDK attempt before transmission. M10-07 development does not
inherit any earlier live-call authorization.

The planned first manual acceptance model is the explicit snapshot
`gpt-5.4-mini-2026-03-17`; it is operator configuration, not a code default. The official model
page lists Responses and Structured Outputs support. A different model requires a new explicit
operator choice and recorded evaluation identity.

The checked-in `.github/workflows/manual-paid-m10-question-analysis.yml` is dispatch-only and uses
an environment approval plus a guard whose authorized call count must exactly match `max_cases`
(1–8). Its output records the snapshot, exact synthetic questions, call count, latency, language,
subquestion count, and schema-valid flag; it never persists raw provider responses or a key.
