# ADR 0004: Atomic Corpus Manifest Activation

## Status

Accepted

## Context

`CorpusManifest` v1 identifies the exact KB and optional index artifacts available to a corpus.
Adding or replacing one registration must not expose a partially written catalog, overwrite another
writer, or imply that KB and index creation are part of one filesystem transaction.

ADR 0002 already requires replacement indexes to be built and validated in new absent directories.
The remaining activation decision is therefore a switch of one canonical manifest file.

## Decision

One update explicitly names `add` or `replace`, one candidate registration, and, for replacement,
the exact current document ID. Before activation the operation:

1. loads canonical current manifest bytes and audits all declared artifacts;
2. validates the candidate through the COR-02 builder without a model;
3. derives and canonicalizes the complete proposed manifest in memory;
4. writes a uniquely owned sibling temporary file, structurally loads it, and audits it;
5. compares the current manifest bytes with the initially read bytes;
6. uses the platform same-directory atomic replace primitive;
7. reloads the committed file before reporting success.

The manifest replacement is the sole activation point. The operation never writes, rebuilds,
renames, or deletes any KB or index directory. Existing and candidate indexes can remain as safe
unreferenced artifacts. There is no inferred successor or active-edition policy.

## Failure And Recovery

Before activation, failure leaves the original manifest byte-identical except when another writer
has intentionally changed it. Cleanup may remove only the exact regular staging file created by the
invocation. A compare-and-swap mismatch fails instead of overwriting the other writer.

After atomic replacement, a verification failure is reported as an uncertain committed state. The
operation does not claim rollback and does not delete any artifacts. An operator can structurally
load and explicitly audit the manifest to establish its current state.

This is not a transaction across KB creation, index creation, and manifest activation. It adds no
lock, journal, revision counter, backup, or persisted event record.

## Consequences

Readers observe either the old complete manifest or the new complete manifest. Concurrent writers
are detected at the final byte comparison when their change occurs before that comparison; this
small local-file contract does not promise distributed locking. Index retirement remains a separate
operator action, preserving ADR 0002.
