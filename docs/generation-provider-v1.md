# Generation provider and structured output v1

M9-02 adds a provider-neutral language-generation boundary. It does not replace retrieval,
deterministic rule evaluation, or the existing cited report. M9-03 will bind opaque generation IDs
back to authoritative provenance and verify/hydrate final citations.

## Trust boundary

`GenerationRequest` contains a question, an explicit target, caller-supplied applicant facts,
reviewed rule findings, and selected evidence text. Every one of those strings is untrusted data.
The OpenAI adapter's fixed system instruction says not to execute instructions found in those
fields and not to expose chain-of-thought.

Evidence visible to a model has only:

- a server-ordered opaque ID such as `evidence:0001`;
- a primary/reference role;
- evidence text;
- an optional human-readable scope label.

It never includes an authoritative Fact ID, document ID, page, source hash, filesystem path, rank,
or retrieval score. A model therefore cannot assign source authority or invent provenance. The
server-owned ID-to-provenance binding is intentionally outside this contract.

The structured draft separates answer text into typed claims. Official facts require evidence IDs;
reviewed-rule claims require both evidence and finding IDs. Applicant statements and limitations
cannot cite official context. Missing information, limitations, review state, and refusal state are
explicit. There is no uncited string fallback after schema or provider failure.

## Checked provider boundary

`GenerationProvider` exposes immutable provider identity and one synchronous `generate` method.
`generate_checked` revalidates the request, identity, and draft, rejects refusals, and rejects every
evidence or finding ID absent from the request. Returned provider/model/prompt metadata is assigned
outside the model output. Errors have stable, privacy-safe codes and do not chain backend exception
text that could contain applicant or evidence data.

`DeterministicFakeGenerationProvider` is the offline default for contract tests and local assembly.
It needs no API key, performs no network activity, and returns a conservative needs-review result
unless a fixed test draft is supplied.

## Optional OpenAI adapter

Install the adapter separately:

```powershell
python -m pip install -e ".[generation]"
```

The adapter uses the official Python SDK's Responses API and Structured Outputs parser. In the
Responses API, structured output is configured through `text.format`; the Python SDK provides
`responses.parse(..., text_format=Model)`. See the official
[Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs) and
[Responses migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses).

Operational controls are explicit:

- the model name is required configuration;
- `OPENAI_API_KEY` is read from the environment only;
- timeout, maximum output tokens, and SDK retry count are bounded;
- `store=False` disables response storage for the request;
- this layer does not wrap the SDK in another retry loop;
- missing credentials, timeout, provider failure, refusal, incomplete status, missing parsed
  output, malformed schema, and unknown IDs all fail closed.

The SDK documents automatic retries for selected transient failures; keeping one finite retry owner
avoids multiplying attempts. See the official
[rate-limit guidance](https://developers.openai.com/api/docs/guides/rate-limits). Key setup follows
the official [API quickstart](https://developers.openai.com/api/docs/quickstart).

Construction alone makes no API request. Any real request is paid/external processing and requires
an explicit operator choice of model plus approval of the exact call count and synthetic input.
Applicant profiles and private evidence must not be sent during integration validation.
