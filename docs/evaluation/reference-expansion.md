# Reference Expansion

RET-05 adds an opt-in, read-only evidence step after hybrid or metadata-aware retrieval. Its purpose
is to follow explicit clauses such as `下記（3）` when the offline builder has already resolved that
reference. It does not resolve references at query time and does not infer a target from scores.

## Authority And Status

`document_kb.json` diagnostics are authoritative. Before expansion, the implementation validates
the fresh KB against every index payload and validates every reference source, candidate, selected
target, status count, and claim identity.

| Builder status | Query-time behavior |
| --- | --- |
| `resolved` | Attach exactly `selected_target_fact_id`, unless it is already a primary result. |
| `ambiguous` | Report candidates and provenance, but attach no target evidence. |
| `unresolved` | Report the claim and available candidates, but attach no target evidence. |

Malformed identities, selected targets, self-links, non-finite scores, or KB/index drift fail closed
with `reference_expansion_error`.

## One-Hop Contract

Expansion depth is fixed at one. A target's own references are never followed during the same
request, including cycles. Primary hit ranks and scores are unchanged. If several source candidates
resolve to one target, the target evidence appears once and retains every incoming relation in
source-rank and claim order. If the target is already primary, no duplicate evidence is attached and
the claim records its primary rank.

## CLI Contract

`--expand-references` is valid only with `--retrieval-mode hybrid`. Without the flag, existing vector,
hybrid, and metadata JSON remain unchanged. With the flag, the original `results` array remains
unchanged and a separate `reference_expansion` object reports:

- primary candidate identities;
- every claim for those candidates and its disposition;
- deduplicated attached target evidence and incoming relations;
- authoritative and expanded status counts;
- the exact KB, PDF, payload, and vector hashes used for provenance.

The current KB bytes are read once. The parsed KB retained by freshness checking is the object used
for expansion, preventing a second read from observing different bytes.

## Real-PDF Baseline

The frozen ISCT fixture has 141 authoritative claims: 7 resolved, 6 ambiguous, and 128 unresolved.
When all 298 Facts are primary, all seven resolved targets are already present, so no duplicate
target evidence is attached. For benchmark query `rq:0012`, source Facts `fact:00057` and
`fact:00064` authoritatively link to the requested `(3)` conditions `fact:00059` and `fact:00066`.
