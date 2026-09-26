# Simple local QA v1

> Historical M10-08 design. M10-09 keeps this reference-only assurance boundary and fallback, but
> replaces the online one-call retrieval-first path with the adaptive flow in
> `adaptive-local-qa-v1.md`.

The natural-language assistant is an optional presentation layer above locally extracted and
indexed admission material. It is not an admission-decision engine and does not extend the
authority of the M9 reviewed report, rule, or cited-answer paths.

## One-call path

A cache miss performs deterministic local normalization, bounded target-scoped hybrid retrieval,
and at most one online generation call using `SimpleQaDraft { answer }`. There is no online
question-analysis call. Known exam aliases are normalized locally; other questions use the
original question as their retrieval query, so the assistant is not limited to the reviewed intent
catalog.

The model receives at most 16 local records and 60,000 source characters. It receives only the
normalized question, a non-identifying target label, request-local `source:NNNN` values, record
text, and section labels. It does not receive Applicant Profile values, document/Fact IDs, pages,
hashes, filesystem paths, credentials, names, contacts, or the complete PDF. Web Search, tools,
uploads, streaming, and outer retry loops are disabled.

The prompt requires an answer based only on supplied records and an explicit knowledge gap when
those records are insufficient. Absence must not become rejection, exemption, or an admission
guarantee. Unlike M9, this optional layer does not require claim, citation, proposition, or evidence
closure. Every answer is marked as a reference that must be checked against structured local
results and the official source.

The public response uses a separate `reference_answer` contract with `assurance=reference_only`.
It contains no Claim IDs, claim kinds, citations, or evidence inventory, so generated prose cannot
be mistaken for an M9 reviewed disposition by API consumers.

Provider refusal, timeout, or malformed output returns a labelled local fallback containing at
most three retrieved excerpts instead of a blank 502 response. No retrieval hit returns a direct
“not found in the selected local material” answer without a paid call.

## Cache and provider boundary

The exact cache key covers the request, local analysis, source/index/page-scope identity,
provider/model/revision, and simple-QA prompt/schema versions. A fresh answer uses at most one
provider call; an exact hit uses zero. The cache is process-memory-only, TTL/LRU bounded,
single-flight, and cleared at restart. It does not store raw provider responses, retrieval payloads,
questions, or Applicant Profiles.

DeepSeek remains pinned to `https://api.deepseek.com`, reads only `DEEPSEEK_API_KEY`, and requires
an explicit allowlisted model. Missing credentials do not affect readiness or structured local
features. CI uses fake clients; real calls require fresh bounded authorization.

The one-call synthetic harness additionally requires the exact one-run guard:

```powershell
$env:JGRAD_ALLOW_DEEPSEEK_LIVE = "I AUTHORIZE 1 DEEPSEEK SIMPLE QA CALL"
python -m jgrad_admission_rag.manual_simple_qa_evaluation `
  --model deepseek-flash `
  --synthetic-only
```

## Relationship to M9

`POST /v1/grounded-answers`, reviewed reports, cited evidence, scope/hash validation, and the M9
release gate are unchanged. Eligibility, deadlines, score rules, and other high-stakes decisions
should use those structured features. Simple QA is broader and cheaper to extend to newly indexed
documents, but deliberately has a weaker trust guarantee.
