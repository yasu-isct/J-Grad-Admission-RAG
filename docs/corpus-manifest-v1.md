# Corpus Manifest v1

`CorpusManifest` is the durable catalog between trustworthy single-document artifacts and future
multi-document retrieval. It records exactly which KB editions belong to a corpus and which of
those editions currently have a validated, fresh local index. It does not search, rank, or choose a
current edition.

## Build Boundary

The caller supplies an absolute corpus root, a corpus ID, and a finite non-empty tuple of explicit
registrations. Each registration names one corpus-root-relative POSIX KB path and, optionally, one
relative local-index directory. The builder never scans a directory or infers identity from paths.

For every registration the builder:

1. rejects absolute, traversing, aliased, or symlinked paths;
2. loads exact KB bytes, requires schema `0.6`, and requires a passing quality gate;
3. copies the complete reviewed `DocumentIdentity` and records the exact KB SHA-256;
4. when an index is supplied, uses the existing integrity loader and freshness gate without calling
   an embedding provider;
5. enforces corpus-wide identity and artifact-path uniqueness;
6. sorts entries by exact `document_id` and recomputes all aggregate counts.

An operator may omit an invalid or stale index and register the trustworthy KB as `not_indexed`.
The builder will not silently downgrade a supplied bad index.

## Entry States

- `not_indexed` contains no index path or index metadata.
- `ready` contains the relative index path and one immutable snapshot of its validated
  `IndexManifest`, including source bindings, embedding identity, artifact hashes, and row counts.

Both states retain the complete document identity, relative KB path, KB schema, exact KB-byte hash,
and passing quality status. Multiple editions may share a document family and multiple documents
may share an institution. Version selection and successor relationships belong to later layers.

## Load Versus Audit

`load_corpus_manifest_bytes` performs structural validation only. It is deterministic and does not
touch registered KB or index paths. This is useful when transporting or inspecting a saved catalog.

`audit_corpus_manifest` is an explicit filesystem operation. It reopens every registered artifact,
rebuilds the manifest from those exact paths, and requires byte-equivalent canonical content. Use
it before activating a corpus whose files may have changed.

Canonical serialization is UTF-8 JSON with sorted keys, compact separators, and one LF. Models are
immutable and reject unknown fields, unsupported versions, noncanonical order, stale counts,
identity collisions, PDF-hash collisions, and artifact-path collisions.

## Minimal API

```python
from jgrad_admission_rag.corpus import CorpusRegistration, build_corpus_manifest

manifest = build_corpus_manifest(
    "graduate-admissions",
    corpus_root,
    (
        CorpusRegistration("isct/2027/document_kb.json", "indexes/isct-2027"),
        CorpusRegistration("sample/2027/document_kb.json"),
    ),
)
```

The first entry must have a self-consistent, fresh index and becomes `ready`; the second remains a
valid `not_indexed` catalog entry. No document is selected as the answer source at this stage.
