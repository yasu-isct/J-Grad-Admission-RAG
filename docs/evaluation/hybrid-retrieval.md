# Hybrid Retrieval

RET-03 combines vector and lexical candidates without pretending cosine similarity and BM25 scores
share units. Both channels run over the same validated `LocalVectorIndex` payload rows. Their raw
scores remain diagnostics; only rank contributes to fusion.

## RRF Contract

Version `rrf-v1` uses equal channel weights and `RRF_K = 60`:

```text
fused_score(row) = sum(1 / (60 + channel_rank))
```

A row ranked first by vector only scores `1/61`. A row ranked second by vector and first by lexical
scores `1/62 + 1/61`. Rows returned by only one channel remain eligible. Higher fused scores rank
first, and exact ties use ascending payload `row_index`. Raw channel scores are never added,
normalized, rounded, thresholded, or compared.

Duplicate rows, non-contiguous ranks, non-finite scores, out-of-range rows, and evidence that differs
from the authoritative payload row fail closed. Hybrid hits expose vector/lexical ranks and raw
scores by name, ordered `matched_channels`, and complete detached official evidence. Raw scores and
the fused score are not confidence or applicant-applicability judgments.

## Candidate Depth

The final `top_k` is applied after union and fusion. Each channel receives the same deeper candidate
limit. Omitting `candidate_k` resolves it to `max(top_k, 50)`; an explicit value must be a positive
non-bool integer at least as large as `top_k`. Lexical search may return fewer candidates because it
excludes zero-score rows. Results report requested/resolved depth and both channel counts.

## CLI Compatibility

`jgrad-search` keeps `--retrieval-mode vector` as its default, preserving the existing vector JSON.
Opt-in `--retrieval-mode hybrid` accepts `--candidate-k` and adds fusion/depth/channel provenance to
the success JSON. The index is loaded once, freshness is checked before provider construction, the
provider and query embedding are each constructed once, and lexical retrieval uses that same index.
`--candidate-k` is rejected in vector mode.

The deterministic fake provider proves plumbing only and is always reported as non-semantic. On the
frozen 298-row corpus its arbitrary vectors can worsen lexical ranking after fusion; those numbers
must not be presented as product quality. Semantic thresholds, scope filters/boosts, reference
expansion, `EvidencePack`, reranking, applicant reasoning, and answer generation remain later work.
