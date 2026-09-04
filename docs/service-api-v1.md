# Service API v1

APP-01 exposes the accepted build and reviewed-corpus retrieval workflows through a small local
FastAPI service. It is a transport boundary over existing domain contracts, not a second builder or
retrieval implementation.

```text
multipart upload -> exact identity check -> DocumentKnowledgeBase 0.6 + diagnostics
strict JSON -> COR-04 selection -> COR-05 prepare/search -> CorpusSearchResult 1.0
```

## Routes

| Method | Route | Success | Meaning |
| --- | --- | --- | --- |
| GET | `/v1/health/live` | 200 | The process and app can respond; no disk/model check |
| GET | `/v1/health/ready` | 200 | Whether query paths and the lifespan provider are ready |
| POST | `/v1/knowledge-bases/build` | 200 | Complete detached KB, summary, and quality decision |
| POST | `/v1/corpus/query` | 200 | Complete document-qualified corpus retrieval result |
| POST | `/v1/build-jobs` | 202 | Durably accept one validated asynchronous build |
| GET | `/v1/build-jobs/{job_id}` | 200 | Read fresh durable status and transition history |
| GET | `/v1/build-jobs/{job_id}/result` | 200 | Read a complete passing or quality-failed result |
| POST | `/v1/build-jobs/{job_id}/cancel` | 200 | Request or confirm cancellation |
| POST | `/v1/build-jobs/{job_id}/retry` | 202 | Create one eligible linked retry attempt |
| DELETE | `/v1/build-jobs/{job_id}` | 204 | Delete exactly one eligible terminal job |

`HEAD` is not an alias for either health route and returns 405. There are no unversioned aliases.
OpenAPI is available at `/openapi.json`; `/docs` is the local interactive rendering of that same
contract.

## Build Request

The build route requires `multipart/form-data` with exactly one `pdf` file and one `identity` JSON
text part. An optional `options` JSON text part can set existing chunk and quality thresholds.
Unknown, duplicate, missing, or mistyped parts fail with `invalid_request`.

The server ignores the uploaded filename, streams bytes in bounded chunks to one owned temporary
directory, checks the `%PDF-` header and configured byte limit, and verifies the reviewed identity's
exact SHA-256 before extraction. Temporary data is removed when the request exits. The endpoint
does not save the PDF, KB, identity, or diagnostics.

A completed quality failure is HTTP 200 with `status="quality_failed"` and
`accepted_for_indexing=false`; the complete KB remains available for inspection. The response uses
`uploaded.pdf` as a sanitized source label and does not change Fact text, pages, scopes, or links.

## Durable Build Jobs

Configure an explicit canonical absolute `job_root` to enable durable routes. Submission reuses the
same multipart, size, PDF header, reviewed identity, SHA-256 binding, and request cleanup boundary
as the synchronous build. A 202 receipt is returned only after repository commit, and contains only
relative status/result paths; uploaded names and Host headers never influence them.

Status is always read from the APP-02A repository. The APP-02B worker is the only build executor,
and complete results retain `source.pdf` as their controlled source label. Cancellation, retry, and
deletion delegate to repository transitions rather than maintaining HTTP-side state. A running
builder is non-interruptible; cancellation prevents publication after that build returns.

Job inputs and results survive service restart and remain under `job_root` until an explicit exact
terminal deletion. There is no automatic retry or retention purge. Active jobs and parents with a
retry child cannot be deleted.

## Query Request

The JSON body contains `selection: CorpusSelectionRequest 1.0` and `search: CorpusSearchRequest
1.0`. Paths, provider/model settings, arbitrary URLs, and applicant profiles are not accepted.
Every request reloads the server-owned canonical manifest and reviewed policy, then runs COR-04 and
COR-05 before using the lifespan-owned provider. Provider query embedding is serialized because a
configured model adapter may not be thread-safe; file validation and ranking remain request-local.

The result is `CorpusSearchResult 1.0`. Its hits are evidence candidates with document-qualified
Fact/Unit IDs and official pages. They are not eligibility decisions or applicant answers.

## Errors

All non-2xx JSON responses use `ErrorEnvelope 1.0` with `code`, a short public `message`, and only
allowlisted `details`. Validation consistently uses 422.

| Status | Code | Public meaning |
| --- | --- | --- |
| 404 | `selection_no_match` | No reviewed document matched |
| 404 | `job_not_found` | No durable job has the canonical ID |
| 409 | `source_binding_mismatch` | PDF bytes do not match reviewed identity |
| 409 | `selection_version_mismatch` | Requested version mode excluded available matches |
| 409 | `selection_not_ready` | Allowlisted document IDs/states are not ready |
| 409 | `selection_ambiguous` | Single-document default matched several IDs |
| 409 | `job_result_not_ready` | The job has no complete inspectable result |
| 409 | `job_cancellation_conflict` | Current terminal state cannot be cancelled |
| 409 | `job_retry_conflict` | Retry is ineligible or already exists |
| 409 | `job_delete_conflict` | Job is active or still owns a retry child |
| 413 | `payload_too_large` | Configured upload/metadata limit exceeded |
| 415 | `unsupported_media_type` | Route or PDF part content type is unsupported |
| 422 | `invalid_request` | Strict transport/domain input validation failed |
| 503 | `corpus_unavailable` | Current policy/manifest/index cannot pass safety checks |
| 503 | `provider_unavailable` | Provider initialization or query failed |
| 503 | `job_service_unavailable` | Durable jobs are unconfigured or unhealthy |
| 500 | `internal_error` | Build or service failed without exposing internals |

## Local Runtime

Install and start a deterministic local mechanics server:

```powershell
python -m pip install -e ".[service]"
jgrad-serve `
  --corpus-root D:\corpus `
  --manifest D:\corpus\corpus.json `
  --policy D:\corpus\policy.json `
  --provider deterministic-fake `
  --dimension 8
```

Enable durable jobs only at an explicit server-owned location:

```powershell
jgrad-serve `
  --corpus-root D:\corpus `
  --manifest D:\corpus\corpus.json `
  --policy D:\corpus\policy.json `
  --provider deterministic-fake `
  --dimension 8 `
  --job-root D:\jgrad-jobs `
  --job-worker-max-active 1 `
  --job-shutdown-grace-seconds 0.25
```

The default bind is `127.0.0.1:8000`. Sentence Transformers requires a pinned model, revision, and
dimension and stays cache-only unless `--allow-model-download` is explicit.

This service has no authentication, authorization, TLS, rate limiting, multi-user isolation, or
production deployment hardening. Do not expose it directly on a non-loopback interface. Such a
deployment requires an authenticated reverse proxy and a separate operational review.
