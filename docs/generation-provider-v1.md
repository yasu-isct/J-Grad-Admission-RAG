# Generation provider and structured output v1.1

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

The structured draft separates answer text into typed atomic claims. Official facts require only
evidence IDs; reviewed-rule claims require finding IDs plus the exact evidence belonging to those
findings; applicant statements require only field paths present in the request. Claim text is
server-hydrated: an official claim reproduces the bound evidence text, a rule claim reproduces its
reviewed statement and status, and an applicant claim reproduces the bound path/value. The model may
select and order those records but cannot author a different factual sentence. The public `answer`
must be the exact newline-joined projection of the hydrated claims, so it cannot carry additional
uncited prose. Limitations are a separate non-answer channel. Missing information, limitations,
review state, and refusal state are explicit. With no supportable claims, the answer is empty and
the draft must abstain with `needs_review=true` plus a missing-information or limitation reason.

## Checked provider boundary

`GenerationProvider` exposes immutable provider identity and one synchronous `generate` method.
`generate_checked` revalidates the request, identity, and draft, rejects refusals, and rejects every
evidence ID, finding ID, or applicant path absent from the request. Any non-empty answer must cover
every selected rule finding exactly once. Reviewed-rule evidence and hydrated text must match that
finding exactly. Pending/review/not-covered state is derived from the entire request, not from model
citations, so required review and missing fields cannot disappear. Because no claim has a free-text
display channel, paraphrased final eligibility, material acceptance, completeness, or admission
guarantees fail hydration rather than relying on a phrase blacklist. Returned provider/model/prompt
metadata is assigned outside the model output. Errors have stable, privacy-safe codes and do not
chain backend exception text that could contain applicant or evidence data. Hydration and final
aggregate-size validation are inside the same privacy-safe boundary, so a Pydantic input-value
representation cannot escape when trusted source text expands the draft. The stable public error is
raised after leaving the validation handler and therefore retains neither exception context nor cause.
The same rule applies to request/output revalidation, provider invocation, SDK construction and
parsing, and parsed-output validation.

`DeterministicFakeGenerationProvider` is the offline default for contract tests and local assembly.
It needs no API key, performs no network activity, and returns a conservative needs-review result
unless a fixed test draft is supplied.

## Optional OpenAI adapter

Install the adapter separately:

```powershell
python -m pip install -e ".[generation]"
```

The optional dependency supports the reviewed current official Python SDK 3.x line (`>=3.17,<4`).
CI installs this extra and runs a credential-free import and call-signature smoke test without
making an API request. The adapter uses the official SDK's Responses API and Structured Outputs
parser. In the Responses API, structured output is configured through `text.format`; the Python SDK
provides `responses.parse(..., text_format=Model)`. See the official
[Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs) and
[Responses migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses).
The supported version floor was checked against the official
[openai-python releases](https://github.com/openai/openai-python/releases).

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
