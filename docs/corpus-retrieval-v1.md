# Corpus Retrieval v1

COR-04 decides which exact editions are authorized. COR-05 searches those approved documents as
one temporary corpus without physically merging or rewriting their indexes. The boundary is:

```text
current manifest + reviewed policy + saved selection + absolute corpus root
  -> audit all declared artifacts and revalidate the complete selection
  -> load and freshness-check only selected indexes into immutable byte snapshots
  -> one query embedding, one global vector rank, one global BM25 rank
  -> one RRF and scope-preference rerank
  -> document-qualified retrieval candidates
```

## Preparation Gate

`prepare_corpus_search_context` first audits the supplied manifest, then calls
`revalidate_corpus_selection_result`. Every selected entry must still be ready and must exactly
match its loaded index manifest, current KB bytes, reviewed document/PDF identity, and payloads
derived from that KB. Corpus-relative paths are resolved beneath one explicit absolute root without
directory discovery.

Selected indexes must share provider, model, revision, dimension, normalized float32 cosine
contract, index and source-KB schema versions, embedding-text version, and payload contract. A
mixed configuration fails before a query provider is inspected. Preparation never constructs or
calls an embedding provider.

The resulting `CorpusSearchContext` stores detached selection JSON, payload JSON, lexical
statistics, and vector bytes in canonical document/local-row order. Query methods reopen no KB or
index files and cannot be changed through returned selection objects.

## One Global Ranking

Exact metadata filters apply to document-qualified rows before either channel truncates. One
checked query embedding is normalized once and compared with every eligible vector. BM25 document
frequency and average length are computed over the union of eligible rows, not independently per
document. Both channels sort globally by descending score, then exact `document_id`, then local row
index; `candidate_k` is one corpus-wide limit.

The two global ranks are fused once with existing equal-weight `rrf-v1`. Existing exact target and
parent-college bonuses rerank the complete fused union before global `top_k`. There are no
per-school quotas, score rescaling, diversity rules, or inferred query scope.

Fact IDs, Unit IDs, and row indexes remain local to a document. Every candidate uses
`(document_id, local_row_index, unit_id, fact_id)` as its alignment key, so two schools may both
have `fact:00001` without collision. Final hits retain the complete reviewed document identity,
KB/index bindings, source pages, section path, scope, text, metadata, and exact payload snapshot.

## Result Trust

`CorpusSearchResult v1` is strict, immutable at its model boundary, canonical UTF-8 JSON with one
trailing LF, and explicitly labels its contents as retrieval candidates rather than eligibility
conclusions or answers. It retains all eligible composite keys and both channel candidate lists so
structural loading can recompute counts, contiguous ranks, ordering, RRF scores, scope bonuses,
selected-document coverage, and hit/payload equality. Per-document diagnostics include selected
documents with zero eligible rows or final hits.

Structural loading proves only internal consistency. It does not reopen current files or prove that
policy, selection, or index bytes have not changed. Prepare a new context to recheck disk state, then
call `revalidate_corpus_search_result` to re-execute the saved request and require canonical exact
equality. Structural validation proves that final hit count fills the available global depth, but a
result does not carry every non-final payload's scope metadata; therefore exact top-membership under
scope preference is established by that current-context re-execution, not by the loader alone. No
result hash is added.

## Deliberate Limits

This layer does not expand references across documents, construct a multi-document EvidencePack,
resolve conflicting rules, evaluate an applicant, or generate prose. Existing single-document
vector, lexical, hybrid, metadata, and RET-09 contracts remain unchanged. Multi-document reasoning
and service/report orchestration belong to M6.
