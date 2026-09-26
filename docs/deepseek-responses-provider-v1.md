# DeepSeek Responses provider v1

> The current product assistant uses the provider's minimal one-call
> [Simple local QA](simple-local-qa-v1.md) path. The two-call question-analysis and claim-closure
> material below is retained as historical provider-development context, not current routing.

M10-02 adds `deepseek-responses` as an explicit first-party online mode. It implements both
`QuestionUnderstandingProvider` and `GenerationProvider`; it does not impersonate OpenAI by
changing a key or endpoint.

## Closed configuration

- credential source: `DEEPSEEK_API_KEY` only;
- endpoint: `https://api.deepseek.com`, fixed in code;
- accepted models: `deepseek-flash` and `deepseek-v4-pro`;
- explicit `--generation-model` required;
- timeout at most 120 seconds, output at most 16,384 tokens, SDK retries at most two;
- default DeepSeek timeout: 90 seconds (an explicit CLI value may reduce it); OpenAI retains its
  30-second default;
- the server publishes a browser request deadline derived from the configured provider timeout,
  SDK attempts, the current maximum of two provider calls, and a 15-second transport grace; the
  browser therefore cannot pre-empt the normal provider budget but still recovers from a hung
  fetch or lock wait;
- default DeepSeek output budget: 8,000 tokens (an explicit CLI value may override it within the
  same 128–16,384 hard bounds); OpenAI retains its 2,000-token default;
- first stable path is non-streaming and has no outer retry loop;
- grounded drafting explicitly uses `reasoning.effort=none`, so hidden reasoning does not consume
  its bounded structured-output budget or enter logs; multilingual question analysis retains the
  provider default because its server-constrained decomposition needs that capability;
- no Web Search, file search, tools, file upload, or whole-PDF input.

There is intentionally no Base URL argument. `OPENAI_API_KEY` cannot satisfy DeepSeek startup.
Provider construction is request-free, and a missing key leaves readiness and ordinary structured
features available while natural-language generation reports itself unconfigured.

## Structured and grounded boundary

Both calls use the official OpenAI-compatible Responses shape. The request supplies
`text.format.type=json_schema`, a DeepSeek-compatible strict JSON Schema, a bounded
`max_output_tokens`, and `store=False`. DeepSeek's compatibility guide says `text.format` is fully
supported and that storage is unsupported with responses always reporting `store: false`.

### DeepSeek schema projection

DeepSeek strict Structured Outputs accepts a narrower JSON Schema dialect than the complete
Pydantic schemas used by this service. M10-04 therefore adds a provider-local wire projection. It
does not replace or modify the application models and is never used by `openai-responses` or
`reviewed-state-offline`.

Projection version `1.0`:

- deep-copies the source schema and deterministically inlines only local `#/$defs/...` references;
- makes every object closed with `additionalProperties: false` and lists every property in
  `required`;
- lists fields with non-null defaults as required values of their original type, while fields whose
  source schema permits `null` remain nullable;
- converts `const` to a one-value `enum`;
- removes wire-unsupported defaults, string/number/array validation constraints, and annotations;
- rejects unknown keywords, remote or unresolved references, cycles, conflicting constraints,
  excessive depth, and excessive input/output size.

Each projected schema has a canonical SHA-256 identity. Operations may record only the projection
version and a short hash prefix alongside non-sensitive status/latency metadata; the schema,
prompt, evidence, profile, and raw response are not default-log fields.

The projection is an API compatibility layer, not a trust boundary. DeepSeek output is decoded and
validated again with the original full Pydantic model. Constraints omitted from the wire schema,
including text length, patterns, numeric bounds, and array sizes, remain authoritative locally.
Question analysis must still reconcile with the deterministic server anchor, and answer generation
must still pass the existing citation and claim closure checks. A wire-valid but locally invalid
response fails closed.

The question-analysis result is parsed locally and must exactly reconcile with the deterministic
server constraint after only bounded alias/typo correction. A model cannot redirect an exam,
retrieval topic, or user-facing subquestion.

The answer call receives only the consolidated bounded evidence projection (at most 16 records and
60,000 evidence characters), request-local `evidence:NNNN` IDs, typed proposition transport data,
and any explicitly selected non-identifying applicant facts. The current product route sends no
Applicant Profile facts to generation. It never sends document IDs, Fact IDs, pages, hashes,
filesystem paths, a complete PDF, names, contacts, or credentials.

The model output is not authoritative. Local schema validation rejects empty, incomplete, refusal,
or malformed responses. `generate_checked` then rejects unknown evidence/proposition IDs and
unsupported claims. The consolidated validator additionally checks typed subject/value semantics
and exact evidence closure before it retains model claim text. Only server code maps opaque IDs back
to document, Fact and page provenance. The original `/v1/grounded-answers` hydration path and M9
release-gate semantics remain unchanged.

The product route places a bounded exact cache before online analysis. A valid miss uses at most one
question-analysis and one consolidated-answer call; an exact hit uses neither. The digest includes
source/index/rule/prompt/schema/provider/model/revision identity, and failed validation or provider
operations are never cached. The cache is process-memory-only and is cleared by restart.

No response body or `reasoning_content` is logged or persisted. Public exceptions contain stable
codes only and detach SDK or validation exception context before leaving the provider boundary.

## Product behavior

`GET /v1/generation-status` returns provider `deepseek-responses`, the explicit model, mode
`online_model`, and whether both adapters initialized. A configured instance is labelled
`DeepSeek 在线模型 · <model>`; a missing key is labelled `DeepSeek 在线生成服务未配置`. There is no
offline fallback under an online label.

The formal question
`托业840按官方的标准是多少英语配点，还有没有jlpt成绩,j-test可以吗` is normalized to TOEIC L&R
and decomposed into identity, score conversion, JLPT, and J.TEST concerns. The product answers
supported siblings independently. Missing JLPT/J.TEST coverage remains “not found in the reviewed
material”; it is not converted into “not required” or “not accepted.” Likewise, evidence for the
department's 100-point English maximum does not authorize inventing a TOEIC 840 conversion.

## Live acceptance gate

Default CI and local tests inject fake clients and cannot make a paid request. Live acceptance is a
separate local operator action after all offline checks pass. It requires a synthetic-only flag,
`DEEPSEEK_API_KEY`, an explicit allowlisted model, and an exact authorization string matching a
2–5 call limit:

```powershell
$env:DEEPSEEK_API_KEY = "<set-locally; never commit>"
$env:JGRAD_ALLOW_DEEPSEEK_LIVE = "I AUTHORIZE 2 DEEPSEEK SYNTHETIC CALLS"
python -m jgrad_admission_rag.manual_deepseek_evaluation `
  --model deepseek-flash `
  --max-calls 2 `
  --synthetic-only
```

The evaluator records only model, exact call count, latency, result status, and citation-validation
status. It does not emit questions, raw responses, keys, or personal data. Running it still requires
the user's explicit authorization in the active task; setting the environment guard alone is not
authorization for an agent to call the service.

The evaluator counts each SDK request before transmission, including failed calls. Its report is
limited to phase, attempt number, latency, allowlisted response status/incomplete reason, stable
structured-output validation categories, and citation-validation status. Citation acceptance uses
the production `generate_checked` boundary and requires the expected reviewed-rule claim; it does
not reject additional official claims that already passed that same server-owned closure. Pydantic error inputs,
model-controlled extra field names, raw output, questions, evidence, profiles, and exception text
are never emitted. A failed question-analysis phase stops the batch before citation generation.

M10-05 synthetic acceptance with `deepseek-flash` established that the earlier 2,000-token budget
could return `incomplete`. With the bounded 8,000-token default and non-null wire types for fields
that have non-null Pydantic defaults, the formal multilingual question completed and passed the
original `QuestionAnalysis` plus deterministic server constraints; the following synthetic
generation completed and passed the original `GenerationDraft` plus server-owned citation closure.
No raw response was persisted.

Official references:

- [DeepSeek API quick start](https://api-docs.deepseek.com/)
- [Using the Responses API](https://api-docs.deepseek.com/guides/responses_api)
- [Strict JSON Schema constraints](https://api-docs.deepseek.com/guides/tool_calls)
- [JSON Output](https://api-docs.deepseek.com/guides/json_mode)
- [Models and pricing](https://api-docs.deepseek.com/quick_start/pricing)
