# DeepSeek Responses provider v1

M10-02 adds `deepseek-responses` as an explicit first-party online mode. It implements both
`QuestionUnderstandingProvider` and `GenerationProvider`; it does not impersonate OpenAI by
changing a key or endpoint.

## Closed configuration

- credential source: `DEEPSEEK_API_KEY` only;
- endpoint: `https://api.deepseek.com`, fixed in code;
- accepted models: `deepseek-flash` and `deepseek-v4-pro`;
- explicit `--generation-model` required;
- timeout at most 120 seconds, output at most 16,384 tokens, SDK retries at most two;
- first stable path is non-streaming and has no outer retry loop;
- no Web Search, file search, tools, file upload, or whole-PDF input.

There is intentionally no Base URL argument. `OPENAI_API_KEY` cannot satisfy DeepSeek startup.
Provider construction is request-free, and a missing key leaves readiness and ordinary structured
features available while natural-language generation reports itself unconfigured.

## Structured and grounded boundary

Both calls use the official OpenAI-compatible Responses shape. The request supplies
`text.format.type=json_schema`, a strict Pydantic-derived JSON Schema, a bounded
`max_output_tokens`, and `store=False`. DeepSeek's compatibility guide says `text.format` is fully
supported and that storage is unsupported with responses always reporting `store: false`.

The question-analysis result is parsed locally and must exactly reconcile with the deterministic
server constraint after only bounded alias/typo correction. A model cannot redirect an exam,
retrieval topic, or user-facing subquestion.

The answer call receives only the already bounded EvidencePack projection (at most 16 records and
60,000 evidence characters), request-local `evidence:NNNN` IDs, reviewed finding transport data,
and any explicitly selected non-identifying applicant facts. The current product route sends no
Applicant Profile facts to generation. It never sends document IDs, Fact IDs, pages, hashes,
filesystem paths, a complete PDF, names, contacts, or credentials.

The model output is not authoritative. Local schema validation rejects empty, incomplete, refusal,
or malformed responses. `generate_checked` then rejects unknown evidence/finding/applicant IDs,
unsupported claims, missing reviewed findings, and state mismatches. `run_grounded_rag` alone maps
opaque evidence IDs back to server-owned document, Fact, page, and hash provenance. This preserves
the M9 release-gate semantics and prevents cross-document citations.

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

Official references:

- [DeepSeek API quick start](https://api-docs.deepseek.com/)
- [Using the Responses API](https://api-docs.deepseek.com/guides/responses_api)
- [JSON Output](https://api-docs.deepseek.com/guides/json_mode)
- [Models and pricing](https://api-docs.deepseek.com/quick_start/pricing)
