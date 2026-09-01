# Metadata Retrieval

RET-04 distinguishes an explicit hard constraint from a ranking preference. Both consume only exact
values supplied by the caller and already stored in validated payload fields. They do not determine
whether a rule legally applies to an applicant.

## Hard Filters

`exact-metadata-v1` supports `fact_types`, `scope_types`, `scope_targets`, and `parent_colleges`.
Values are non-blank, trimmed, duplicate-free exact strings. Values within one field use OR; active
fields combine with AND. A target filter matches payload target intersection, while a college filter
requires an exact non-null college. Empty dimensions impose no restriction. Zero eligible rows is a
successful empty result; the system never broadens a filter to global or unknown evidence.

One validated eligible-row set is applied before vector and lexical candidate truncation. Vector
scores may still be computed exhaustively, while only eligible rows enter ranking. Lexical corpus
statistics and BM25 scores remain corpus-wide and unchanged; eligibility affects candidate selection
only. Channel ranks are then contiguous and safe for `rrf-v1`.

## Scope Preferences

`scope-match-v1` supports explicit `preferred_scope_targets` and
`preferred_parent_colleges`. It uses exact stored-value membership and never parses the query:

```text
target bonus  = 1.0 / (60 + 1)
college bonus = 0.5 / (60 + 1)
ranking_score = fused_score + target bonus + college bonus
```

Each bonus applies at most once; both may accumulate. Global, unknown, and non-matching department
rows receive no bonus and no penalty. Final order uses descending `ranking_score`, then ascending
`row_index`. Hits preserve the original `fused_score`, channel ranks/raw scores, total boost, matched
preference names in target-then-college order, exact matched values, and complete official evidence.
These values are ranking diagnostics, not confidence or applicant applicability.

## CLI

Metadata flags are repeatable and valid only with `--retrieval-mode hybrid`:

- `--filter-fact-type`
- `--filter-scope-type`
- `--filter-scope-target`
- `--filter-parent-college`
- `--prefer-scope-target`
- `--prefer-parent-college`

Without any metadata flag, default vector and RET-03 hybrid JSON take their existing code paths and
remain unchanged. Metadata-aware JSON adds requested values, corpus/eligible/channel counts, versions,
boost constants, and per-hit base/final score provenance.

## Current Corpus Boundary

The frozen 298-row corpus has seven fact types; scope is 2 global, 126 department, and 170 unknown.
It contains 19 target names and six non-null parent colleges. The durable payload has no explicit
degree, admission year, or intake field. RET-04 does not infer these from a filename, document ID,
text, query, or model. Fuzzy entity resolution, query intent parsing, ApplicantProfile use,
specificity/override reasoning, references, thresholds, and answers remain later work.
