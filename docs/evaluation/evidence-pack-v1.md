# EvidencePack v1

`EvidencePack` is the sealed, request-specific handoff from retrieval to future reasoning. Version
`1.0` carries complete official evidence and technical provenance without interpreting whether an
applicant qualifies.

## Sections And Invariants

| Section | Meaning | Main invariant |
| --- | --- | --- |
| `request` | Exact query and caller-supplied filter/preference/depth | Hybrid only; no inferred intent or profile |
| `runtime` | KB/PDF/index/provider hashes, versions, constants, counts | Frozen v1 versions and internally reconciled counts |
| `primary_evidence` | Ranked metadata-aware hybrid hits | Contiguous ranks; complete official evidence and channel provenance |
| `attached_reference_evidence` | Unique non-primary resolved targets | Never duplicated in primaries; every incoming relation retained |
| `resolved_relations` | Authoritative RET-05 resolved claims | Target exists exactly once and disposition/location agrees |
| `reference_warnings` | Ambiguous and unresolved claims | No selected target or promoted evidence |
| `counts` | Collection totals and warning status totals | Derived values must exactly match every collection |

Within a pack, evidence identity is `(document_id, fact_id)`; row and Unit IDs are also unique.
Text is never summarized, translated, concatenated, or converted into an answer. Pages must be
positive, sorted, unique, and non-empty; section paths and evidence text must be non-empty.
Relations and warnings retain `source_claim_index`; their combined indexes are contiguous from zero
within each primary, preserving the original authoritative diagnostic order across both collections.

## Compact Shape

```json
{
  "schema_version": "1.0",
  "request": {"query": "...", "retrieval_mode": "hybrid"},
  "runtime": {"source_kb_sha256": "...", "fusion_version": "rrf-v1"},
  "primary_evidence": [{"role": "primary", "primary_rank": 1, "fact_id": "fact:00057"}],
  "attached_reference_evidence": [
    {
      "role": "reference_target",
      "fact_id": "fact:00059",
      "incoming_relations": [{"source_primary_rank": 1, "source_fact_id": "fact:00057"}]
    }
  ],
  "resolved_relations": [
    {"source_fact_id": "fact:00057", "selected_target_fact_id": "fact:00059"}
  ],
  "reference_warnings": [],
  "counts": {"primary_evidence_count": 1, "attached_evidence_count": 1}
}
```

The compact example omits required fields for readability; canonical output contains the complete
strict schema. Scores are ranking diagnostics, not confidence, correctness, or applicant
applicability. `ranking_score`, `fused_score`, channel scores/ranks, and fixed boosts remain separate.

## Canonical Bytes And Loading

Canonical serialization is UTF-8 JSON with sorted object keys, compact separators, preserved list
order, `ensure_ascii=False`, finite numbers only, and exactly one trailing newline. Repeated builds
from value-equivalent inputs and loader round trips are byte-identical.

The loader reads one regular non-symlink file once. It rejects invalid UTF-8/JSON, unknown versions,
extra fields, unsafe paths, non-finite values, identity collisions, broken relations, unsupported
runtime versions, and false counts. It never repairs, sorts, deduplicates, loads a model, or uses the
network. Future incompatible formats require a new schema version and explicit policy.

## CLI

`--output-format evidence-pack` requires `--retrieval-mode hybrid`. It automatically executes the
RET-05 one-hop expansion and cannot be combined with the redundant `--expand-references` flag. The
path retains one index load, one current-KB read, freshness before provider construction, one query
embedding, one retrieval result, and one expansion. Stdout contains only the canonical pack.

Default `--output-format search` remains unchanged. The deterministic fake provider validates only
serialization and plumbing; it is non-semantic and does not establish retrieval quality.

## Reasoning Boundary

EvidencePack v1 deliberately contains no `ApplicantProfile`, inferred intent, eligibility status,
specificity/override reasoning, natural-language answer, rendered citation, or report. M4 reasoning
will consume this stable envelope and add those decisions in a separate, auditable layer.
