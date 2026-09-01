# Lexical Retrieval

RET-02 provides a deterministic lexical candidate generator for exact names, dates, test labels,
form numbers, and Japanese admission terminology. It consumes validated, ordered `IndexPayload`
rows from a `LocalVectorIndex` or directly from `derive_index_payloads`; it does not require vectors,
a model, network access, or a new persisted artifact.

## Versioned Contract

- Tokenizer: `nfkc-casefold-ja23-v1`.
- Scoring: `bm25-v1`, with `k1 = 1.2` and `b = 0.75`.
- Japanese text: overlapping character 2-grams and 3-grams.
- Latin and numbers: NFKC plus case folding, grouped-number comma removal, and collapsed connector
  variants for identifiers such as `TOEFL-PBT`, `TOEIC L&R`, dates, emails, and numbered labels.
- Corpus projection: canonical payload text plus document, Unit, Fact, section, type, scope, target,
  and parent-college fields. These fields improve matching but do not become answer evidence.
- Ranking: positive BM25 scores descending; exact ties use payload `row_index` ascending.
- Results: immutable, detached payload evidence including complete text, scope, section path, and
  official source pages.

Changing tokenization or scoring behavior requires a version change and updated golden tests.
Lexical retrieval intentionally has no CLI, score threshold, vector fusion, applicant reasoning, or
answer generation; those belong to later tasks.

## Real-PDF Baseline

The RET-01 benchmark contains 34 annotated queries over 298 payload rows. With the frozen PDF and KB
baseline, lexical retrieval finds at least one gold Fact for all 34 queries in the top 10 and for 32
queries in the top 5. All 21 paraphrase queries hit in the top 5. The two top-5 misses, `rq:0010` and
`rq:0019`, both hit in the top 10. Tests also require every exact-term and identifier query to hit a
gold Fact in the top 10 and verify that retrieval does not mutate payload evidence.
