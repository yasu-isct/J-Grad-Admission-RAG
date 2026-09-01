# Retrieval Query Annotation v1

## Purpose

`tests/fixtures/retrieval_queries_v1.json` is RET-01 gold data for one official admission
guideline. It is an auditable exam paper for later retrieval work, not a generated answer set. The
authoritative annotation source is the rebuilt `DocumentKnowledgeBase`; vector similarity, model
output, nearby text, and keyword overlap cannot approve a gold label.

## Dataset Fields

- `schema_version`, `benchmark_id`, `language`, and `annotation_policy_version` version the contract.
- `document_id`, `source_pdf_sha256`, `expected_kb_schema_version`, `fact_content_sha256`, and
  `fact_structure_sha256` bind the fixture to the frozen real-data baselines without recording a
  machine path or committing the PDF.
- `queries` is ordered presentation data. IDs are contiguous `rq:0001` values.

Each query records a natural Japanese question, one controlled category and style, sorted complete
`relevant_fact_ids`, and one `gold_evidence` row per Fact. Evidence pages, scope type, and targets
are copied exactly from the authoritative Fact. `annotation_note` states why the Facts directly
support the question without reproducing a long official passage.

Controlled styles are `paraphrase`, `exact_term`, and `identifier`. Categories cover eligibility,
application dates, fees, documents, language tests, selection/exams, results, enrollment,
contacts/forms, and department requirements.

## Relevance Policy

A Fact is relevant only if its official clause directly contributes evidence needed to answer the
question. Section adjacency, shared vocabulary, or a plausible topic is insufficient. Include every
directly supporting current Fact, including duplicate authoritative projections when the KB exposes
the same official clause more than once; duplicates do not by themselves make a question a genuine
multiple-clause case.

`requires_multiple_clauses` is true only when different official clauses are needed. It is reviewed
separately from the number of Fact IDs. A question with no direct supporting Fact is excluded from
v1. Expected answers, applicant profiles, scores, ranks, and hidden reasoning are never stored.

## Scope And References

Scope is copied, never inferred from the query. A broad-sounding question cannot turn an `unknown`
Fact into `global`, and a department rule is relevant only when the question names or otherwise
selects that department. `scope_sensitive` marks questions where the targeted wording is material.

For a cross-reference, inspect the source Fact, selected target, nearby Facts, and reference
diagnostics. Set `requires_reference_expansion` only when answering requires following the reference,
then include the directly needed source and target Facts. Ambiguous or unresolved references are not
silently promoted to gold.

## Adding Or Reviewing A Query

1. Rebuild the hash-verified real KB and confirm its quality gate passes.
2. Read each candidate Fact's complete text, section path, scope, pages, nearby Facts, and references.
3. Write the question independently in natural Japanese.
4. Record the complete sorted Fact set and copy pages/scope exactly.
5. Decide whether scope, multiple clauses, or reference expansion is genuinely required.
6. Run the focused fixture tests and the `real_pdf` suite; review the PR audit row manually.

Never use Markdown chunks, vector scores, or a generative model as annotation authority. Mutable data
returned by the loader is detached from later loads, and JSON list order is deterministic.

## Ownership Boundaries

- RET-01 owns curated gold questions and evidence judgments.
- RET-02 owns deterministic lexical retrieval.
- RET-03 owns vector/lexical fusion.
- RET-07 owns retrieval metrics and acceptance thresholds.
- M4 owns applicant-profile applicability and reasoning.

Changing a retrieval algorithm must not rewrite gold to make its scores look better. Gold changes
require a new human audit against the authoritative official document and stable baselines.
