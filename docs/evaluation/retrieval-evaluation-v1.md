# Retrieval Evaluation v1

Retrieval evaluation consumes one validated benchmark, the matching trusted knowledge base and
local index, and one `EvidencePack` per benchmark query. It emits one strict canonical JSON report.
The report is diagnostic evidence, not an answer and not an applicant-applicability decision.

## Evaluation Run

`jgrad-evaluate-retrieval` runs the benchmark queries in their declared order through hybrid
retrieval and one-hop reference expansion. Every query uses an empty `MetadataFilter` and an empty
`ScopePreference`; benchmark gold labels are read only after retrieval. The minimum primary depth
is 10 and the default candidate depth is 50.

```powershell
jgrad-evaluate-retrieval outputs\index\sample-bge-m3 `
  --current-kb outputs\kb\sample\document_kb.json `
  --benchmark tests\fixtures\retrieval_queries_v1.json `
  --provider sentence-transformers `
  --model BAAI/bge-m3 `
  --revision <same-40-character-commit-sha> `
  --dimension 1024 `
  --cache-folder .cache\models
```

Evaluation is cache-only and rejects model-download authorization. It validates index freshness,
benchmark-to-KB content and structure hashes, EvidencePack runtime identity, query ordering, empty
filters/preferences, complete primary depth, and evidence alignment before scoring.

## Metrics

For query `q`, let `Gq` be its non-empty set of relevant Fact IDs and `Rk(q)` the first `k` ranked
primary Facts. The report computes:

- `Recall@k = |Gq intersect Rk(q)| / |Gq|` for `k` in `1, 3, 5, 10`.
- Reciprocal rank is `1 / r`, where `r` is the first relevant primary rank, or zero for no hit.
- Overall Recall@K and MRR are arithmetic macro averages over queries.
- Breakdowns use the same macro calculation for category, query style, scope sensitivity,
  multiple-clause need, and reference-expansion need.

Metrics use ranked primary Facts only. A gold Fact reached solely through an attached reference is
listed in `reference_only_gold_fact_ids` when the benchmark marks the query as requiring reference
expansion, but it never receives ranked Recall or MRR credit. Missing gold IDs and zero-hit query IDs
remain explicit diagnostics.

The JSON stores full finite floating-point values. Human-facing displays may round values, but any
future comparison or gate must use the stored values rather than rounded text.

## Quality Eligibility

`deterministic-fake` embeddings test deterministic plumbing only. Their reports always contain
`semantic_evaluation=false`, `quality_eligible=false`, and `gate_status=not_evaluated`. This version
defines no acceptance threshold and does not add a CI quality gate. A separately accepted semantic
baseline and threshold policy are required before retrieval quality can gate changes.

## Report Safety

The `1.0` schema forbids unknown fields, unsupported versions, non-finite metrics, inconsistent
rankings, fabricated aggregates, and mismatched quality status. Canonical serialization uses UTF-8,
stable compact JSON, and one trailing newline. File loaders reject symlinks and parse one byte
snapshot so a report can be hashed and archived reproducibly.
