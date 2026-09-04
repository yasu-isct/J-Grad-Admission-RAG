# Corpus Version Policy v1

`CorpusVersionPolicy` is reviewed operational metadata that labels each exact document in a
`CorpusManifest` as active or historical. Inventory and intent remain separate: the manifest says
which artifacts exist, while the policy says which reviewed edition may be used by default.

## Complete Reviewed Coverage

Each manifest document family appears exactly once in the policy. A family names zero or one active
document and all remaining documents as historical. A family may intentionally have no active
edition. Policy compatibility validation requires every current document ID to be classified once
inside its actual family and rejects unknown, missing, duplicate, or cross-family IDs.

Structural policy loading does not establish compatibility with a current manifest. Call
`validate_corpus_version_policy(policy, manifest)` after loading both artifacts. A COR-03 membership
or identity change invalidates the old policy until it is reviewed again; changing only index
metadata for the same exact document remains compatible because policy binds document/family IDs,
not derived index state.

No date, title, filename, path, intake, or sorted ID is used to infer an active edition. The policy
contains no corpus hash, identity copy, official evidence, or applicant conclusion.

## Safe Selection

`CorpusSelectionRequest` requires at least one positive exact identity constraint. Values within a
field are OR alternatives; populated fields combine with AND. Supported fields are document,
institution, document family, degree level, and intake term. Tuples are deduplicated, validated, and
sorted canonically.

The defaults are deliberately narrow:

- `version_mode="active_only"`;
- `allow_multiple_documents=false`.

Historical and all-version access require explicit modes. More than one match requires explicit
multi-document authorization. Identity matches excluded by the requested version mode produce a
version mismatch rather than silently overriding policy.

Only `ready` entries can be selected. If a matching active entry is `not_indexed`, selection fails
with that document state and never falls back to a ready historical edition. No match, not ready,
version mismatch, and disallowed multiplicity are distinct typed failures.

## COR-05 Handoff

`CorpusSelectionResult` contains the normalized request, explicit active/historical classification,
and complete detached corpus entries, including validated index-manifest snapshots. It is ordered by
exact document ID and contains no ranking implication.

Selection reads only the supplied manifest and policy objects. It does not open KB/index files,
audit freshness, call an embedding provider, rank Facts, or generate an answer. The caller must run
the COR-02 artifact audit before query-time use; COR-05 will consume the selected ready entries.

COR-04 intentionally exposes the library and canonical policy/request/result JSON APIs without a
CLI. This keeps the pre-retrieval contract directly testable while avoiding a second command-line
boundary before COR-05 defines how selected indexes are consumed.
