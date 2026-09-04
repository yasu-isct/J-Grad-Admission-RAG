# Durable Build Job Storage v1

APP-02A defines the local durable ledger used by the later APP-02B worker and HTTP routes. It owns
job metadata and build inputs/results, but does not invoke the builder, start a worker, or add an
HTTP route.

```text
validated identity/options + identity-bound PDF
  -> atomic repository create
  -> queued durable job
  -> later worker transitions and result publication
```

## State Contract

Every record has a canonical UUID, attempt and optional parent, UTC timestamps, current state and
phase, fixed blob-role references, and a complete append-only transition projection. Records are
strictly revalidated whenever loaded and returned as detached Pydantic objects.

| Current state | Legal next state | Phase after transition | Diagnostic |
| --- | --- | --- | --- |
| initial | `queued` | `waiting` | none |
| `queued` | `running` | `building` | none |
| `queued` | `cancelled` | `finished` | `cancelled_by_request` |
| `running` | `cancel_requested` | `cancelling` | none |
| `running` | `succeeded` | `finished` | none |
| `running` | `quality_failed` | `finished` | none |
| `running` | `failed` | `finished` | `build_failed` or `worker_interrupted` |
| `running` | `cancelled` | `finished` | `cancelled_by_request` |
| `cancel_requested` | `cancelled` | `finished` | `cancelled_by_request` |
| any terminal state | none | `finished` | immutable |

`quality_failed` means the builder completed and returned inspectable diagnostics; it is not an
operational failure. Only `succeeded` and `quality_failed` can advertise `result.json`.

## Owned Layout

One explicitly opened repository owns one canonical absolute root:

```text
<job-root>/
  .repository.lock
  jobs.sqlite3
  .staging/
  jobs/<canonical-job-uuid>/
    identity.json
    options.json
    source.pdf
    result.json          # only after successful result publication
```

The SQLite database stores privacy-safe state and canonical record JSON. It never stores uploaded
filenames, absolute paths, PDF/identity text, exception strings, headers, client data, or model
configuration. Blob names and directories are repository constants derived only from parsed UUIDs.
Unknown root/job/staging entries, symlinks, non-regular blobs, incompatible schema versions, corrupt
records, and broken PDF identity binding make the repository unavailable rather than triggering
repair or deletion.

## Transactions And Recovery

Input creation writes canonical identity/options and a checked PDF copy to a known staging
directory, atomically renames that directory into `jobs/`, then commits the queued record. A method
failure removes its own staging or newly published directory before returning. An acknowledged job
is therefore available after close/reopen.

Result publication validates a detached APP-01 `BuildResponse`, writes a staging file, atomically
publishes `result.json` inside the database transaction, and commits the matching terminal state.
The complete result must retain the job's exact reviewed identity and canonical `source.pdf` label.
A small pending marker proves ownership across the filesystem/database commit window; recovery may
remove a non-terminal result only when that marker exists. No partial result is advertised.

Explicit open/recovery keeps `queued`, converts stale `running` to `failed/worker_interrupted`, and
converts orphaned `cancel_requested` to `cancelled/cancelled_by_request`. Known uncommitted create
and result staging entries are removed. A delete tombstone is restored if its database record still
exists, or removed if the deletion commit completed.

Terminal deletion atomically renames exactly one UUID directory into the staging namespace before
deleting its database row. Active jobs and parents with an existing retry child cannot be deleted.
A missing ID returns a typed not-found outcome. There is no automatic purge.

## Concurrency And Retry

An OS file lock rejects a second active repository owner. SQLite `BEGIN IMMEDIATE` transactions and
a small process-local reentrant lock serialize claim, cancel, terminal transition, publication,
retry, and deletion decisions. This is single-service-instance infrastructure, not distributed
coordination.

Only `failed` or `cancelled` jobs with intact validated input blobs can create one retry child. The
child uses a new server UUID, points to exactly one parent, and increments its attempt. A unique
database constraint makes concurrent duplicate retry requests deterministic conflicts.

## Privacy-Safe Failures

Public repository exceptions use fixed messages: validation, conflict, not-found, or unavailable.
They do not include paths, supplied bytes, document text, SQLite details, traceback names, or raw
exceptions. APP-02B will translate these internal categories into the versioned HTTP envelope.
