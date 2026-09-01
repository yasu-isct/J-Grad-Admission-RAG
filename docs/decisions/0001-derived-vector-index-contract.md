# ADR 0001: Derived Vector Index Contract

## Status

Accepted

## Context

`document_kb.json` is the authoritative, source-traceable knowledge artifact. A local vector index
will accelerate retrieval, but it must not become a second knowledge base or hide which KB and
embedding configuration produced it.

## Decision

- Index artifacts are derived and rebuildable. `ScopedFact` remains authoritative.
- Payload row order is the vector-row alignment contract: payload row `N` describes vector row `N`.
- The manifest records the SHA-256 of the exact `document_kb.json` bytes and the source PDF hash.
- Index schema versions and KB schema versions evolve independently and are both checked.
- Cosine distance, float32 vectors, normalization, provider, model, and revision are explicit
  manifest fields rather than implicit implementation defaults.
- Artifact names are safe basenames so a manifest cannot redirect loading outside its directory.

## Deferred Verification

IDX-01 defines values and pure record compatibility only. File existence, recomputed artifact
hashes, NumPy shape/dtype validation, and stale-index detection require concrete artifacts and are
deferred to IDX-05 and IDX-08.

## Consequences

Future index builders must preserve deterministic RetrievalUnit order, and loaders can reject
incompatible metadata before reading vectors. Deleting an index never deletes authoritative
knowledge; the index can be rebuilt from the recorded KB and embedding configuration.
