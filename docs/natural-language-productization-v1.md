# Natural-language RAG productization v1

M10-01 adds a product-facing boundary above the M9 grounded-answer endpoint. It preserves M9 as
the citation authority rather than weakening its whole-answer validation.

## Explicit modes

Both `jgrad-demo` and `jgrad-serve` accept:

- `--generation-provider reviewed-state-offline` (default): deterministic question normalization,
  reviewed-state generation, no key, network request, or model download;
- `--generation-provider openai-responses --generation-model <model>`: OpenAI Responses API for
  Structured Outputs question analysis and the existing citation-constrained generation draft.

The online adapter reads only `OPENAI_API_KEY`, uses the official SDK default endpoint, sends
`store=False`, and bounds timeout, output tokens, and SDK retries. There is no configurable base
URL and no retry loop around the SDK. Provider construction makes no request.

If online mode is selected without a usable key, the service continues to report ready when its
corpus, retrieval, and structured report functions are healthy. `GET /v1/generation-status`
reports `configured=false` and the browser displays `在线生成服务未配置`; the natural-language
route returns a privacy-safe 503. The service never silently falls back and labels offline rules as
online AI.

## Strict analysis boundary

`QuestionAnalysis` is a frozen, extra-forbid Structured Outputs schema with detected language,
normalized question, explicit corrections, requested intents, ordered subquestions and retrieval
queries, mentioned exam types/scores, target-scope mentions, missing context, and unsupported
parts. Subquestion IDs are contiguous and all lists are bounded and canonical.

Before an online call, the server builds a request-local semantic constraint from its deterministic
normalizer and sends it beside the untrusted question. The Structured Output must preserve the
detected language, corrections, exam types/scores, intents, subquestions, clarification state, and
retrieval queries exactly. A schema-valid response that changes the exam, language, user-facing
subquestion, or retrieval topic is rejected as malformed before retrieval. SDK and validation
exceptions are converted only after leaving their handlers, so private provider payloads cannot
remain reachable through an exposed exception context.

The deterministic fallback recognizes Chinese, Japanese, and mixed forms of TOEIC L&R, TOEFL iBT
and Home Edition, JLPT, and J.TEST. It decomposes the formal M10 acceptance question into alias
interpretation, score conversion/allocation, JLPT, and J.TEST questions. Prompt-injection requests
and admission guarantees are recorded as unsupported parts and are never followed.

The fixed M9 intent lexicon remains a reviewed downstream adapter. It is no longer the product
entry gate: analysis succeeds first, then every substantive subquestion independently attempts
bounded target-scoped retrieval and reviewed-report closure.

The user-facing subquestion and generation instruction follow the detected user language, while
the separate retrieval query remains concise Japanese for the reviewed Japanese source. The
retrieval query is never reused as a reason to switch a Chinese user's answer into Japanese.

## Partial-answer and trust policy

`POST /v1/natural-language-answers` reuses the selected document, college, department, intake,
schedule, and in-memory applicant form. It performs at most eight subquestion runs. Each run uses
the existing top-12/candidate-48 hybrid retrieval, scope preferences, EvidencePack construction,
reviewed report, opaque evidence IDs, checked provider call, and server citation hydration.

An unsupported or insufficiently evidenced subquestion becomes `no_clear_evidence` with the fixed
message `当前审核资料中未找到明确依据。`; a clarification-dependent one becomes
`needs_clarification`. Other validated siblings remain visible. Provider outages, malformed
outputs, citation failures, and unexpected server conflicts still fail closed rather than being
misrepresented as missing knowledge.

Alias interpretation is labelled separately and explicitly says that normalization is not an
official acceptance conclusion. Every affirmative admissions fact remains inside a nested M9
`GroundedAnswer`, so it carries server-hydrated document, Fact, page, KB-hash, and PDF-hash
provenance. The model never sees those authoritative identifiers or local paths.

## Browser boundary

The browser fetches the actual generation status, displays `在线大模型回答`, `离线规则结果`, or
`在线生成服务未配置`, and never derives the label from marketing text. The main answer presents a
direct status summary and ordered subquestions. Missing evidence and missing context are prominent.
Provider/model, reviewed scope, missing fields, and limitations are placed in collapsed
`技术详情 / 审计信息`. Factual strings still use `textContent`, and citations continue to open the
existing verified evidence drawer and local PDF page controls.

Question, profile, analysis, and answers remain request-local and browser-memory-only. The service
does not log or persist API responses, keys, questions, profiles, or generated output.

## Manual real-provider boundary

CI and ordinary local verification use fake/offline providers only. A real request is a separate
operator action that requires a locally set key, an explicit model, synthetic applicant data, and
advance authorization of an exact maximum call count. One multi-intent request can consume one
analysis call plus one generation call for each evidence-supported subquestion, so authorization
must cover that computed upper bound. No real request was made for M10-01 implementation.

The planned first manual acceptance model is the explicit snapshot
`gpt-5.4-mini-2026-03-17`; it is operator configuration, not a code default. The official model
page lists Responses and Structured Outputs support. A different model requires a new explicit
operator choice and recorded evaluation identity.

The checked-in `.github/workflows/manual-paid-m10-question-analysis.yml` is dispatch-only and uses
an environment approval plus a guard whose authorized call count must exactly match `max_cases`
(1–8). Its output records the snapshot, exact synthetic questions, call count, latency, language,
subquestion count, and schema-valid flag; it never persists raw provider responses or a key.
