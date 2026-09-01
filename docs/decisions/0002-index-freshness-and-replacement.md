# ADR 0002: Index Freshness And Replacement Policy

## Status

Accepted

## Context

IDX-05 self-integrity validation proves that an index directory is internally consistent. It does
not prove that the directory still represents the `document_kb.json` and embedding configuration an
operator intends to use now. A stale but internally valid index can return correctly aligned evidence
from old source bytes or a different model configuration.

## Decision

- `document_kb.json` remains authoritative; every vector index is derived and rebuildable.
- Freshness hashes the exact current KB bytes with SHA-256. It does not use timestamps, path names,
  file sizes, or partial semantic comparison.
- The current KB `document_id` and source PDF SHA-256 are checked separately so provenance changes
  remain auditable even when the exact-byte hash already differs.
- Provider, model, revision, and dimension are declared from validated CLI arguments and compared
  with the index manifest before constructing or loading a model backend.
- Search proceeds only after index self-integrity and current-input freshness both pass. The runtime
  provider identity is still checked before query embedding.
- Freshness checks are read-only and never create reports, locks, markers, or replacement artifacts.

## Replacement Policy

IDX-08 does not implement automatic overwrite, deletion, rename, directory swap, `--force`, or
backup cleanup. Replacing a non-empty directory atomically is not portable across supported
filesystems, and a failed multi-step swap can leave an ambiguous active index.

The supported procedure is:

1. build the replacement into a new, absent directory;
2. validate and freshness-check that complete directory;
3. switch the caller or configuration to the new path;
4. retire the old directory separately after the switch is confirmed.

Any future automatic replacement requires an explicit crash-recovery and rollback design, tests on
supported platforms, and separate approval.

## Consequences

A one-byte whitespace change makes an index stale even when parsed KB content is equivalent. This is
intentional: exact bytes are the reproducible build input recorded by the index. Operators receive
stable mismatch codes and rebuild to a new destination instead of silently querying old evidence.
