# QueryIntent v1

`QueryIntent` v1 is a conservative, deterministic interpretation of an applicant's question. It is
not an answer, an eligibility decision, official evidence, or an `ApplicantProfile` extractor.

The parser accepts a caller-provided, reviewed `QueryIntentCatalog`, recognizes only catalog terms,
and records each match with the exact original-query offsets and surface. Unsupported wording stays
unselected. Ambiguous aliases deliberately select no entity. `null` and empty scope values mean that
no explicit scope was supplied; they never mean "global".

The v1 adapter always returns an empty `MetadataFilter`. Explicit department/program and parent
college mentions become `ScopePreference` values only, preserving global and unmatched evidence as
retrieval candidates. Degree and intake context remain on `RequestedScope` but are not passed to
retrieval because the current payload has no durable fields for them.

Use `config/query_intent_catalog_v1.json` as the reviewed catalog and the safe byte/file loaders for
untrusted catalog input. Canonical JSON is UTF-8, sorted-key, and LF-terminated. The parser has no
model, prompt, network, KB mutation, profile extraction, or retrieval implementation.
