# Local Evidence Review UI

APP-04A adds the first browser-facing workflow to the existing local service. Open
`http://127.0.0.1:8000/app` after starting `jgrad-serve` with at least one explicit reviewed report
plan. The page lists only safe reviewed documents and sends one-document evidence searches to the
accepted `/v1/corpus/query` endpoint.

```text
audited manifest + reviewed policy + lifespan plans
  -> GET /v1/reviewed-documents
  -> choose exactly one document
  -> POST /v1/corpus/query
  -> exact server-ordered evidence candidates
```

## Boundary

This screen answers where the official guideline contains potentially relevant text. Each result
shows the returned document title and ID, Fact ID, official pages, exact search text, section path,
scope, Fact type, and vector/lexical/fusion diagnostics. Results are evidence candidates, not rule
applicability, overall eligibility, admission probability, or a recommendation.

APP-04A contains no applicant profile fields and never calls `/v1/applicant-reports`. APP-04B may
add that separate workflow after this evidence-review contract is accepted. The UI does not alter
selection, ranking, provider lifecycle, or corpus state.

## Configuration

The document catalog is available only when reporting is configured with one or more repeatable
absolute `--report-plan` paths. On every catalog request, the service reloads and audits the current
manifest and reviewed version policy. It returns only ready documents with exactly one matching
lifespan-loaded plan. Public catalog identities omit PDF/KB hashes, paths, index/provider/model
configuration, predicates, and evidence text.

The UI limits a question to 1,000 characters as a conservative browser input bound and submits the
existing strict query schema with `top_k=5`, `candidate_k=20`, empty filters/preferences, and
`allow_multiple_documents=false`. Refreshing the page clears question and results.

## Offline And Privacy

HTML, CSS, and JavaScript are package data served only from `/app`, `/assets/app.css`, and
`/assets/app.js`. They require no npm build, CDN, framework, analytics, telemetry, or internet
connection. The installed wheel resolves assets from its package location, independently of the
current working directory.

Untrusted catalog, error, query-result, and evidence values are inserted through DOM text
properties only. The implementation uses no HTML string insertion, dynamic script execution,
browser storage, cookies, service worker, query-string state, automatic clipboard access, or
logging of queries/evidence. It never renders Markdown.

The UI and API return `no-store`, `nosniff`, and `no-referrer` headers. UI assets additionally use a
restrictive self-only Content Security Policy, denied framing, and disabled sensitive browser
permissions. These controls are scoped so existing `/docs` and `/openapi.json` behavior remains
unchanged. The service remains loopback-only development software without authentication, TLS,
rate limiting, or public-hosting hardening.

## States

Native labeled form controls, visible keyboard focus, a polite live status region, and a responsive
single-column fallback cover catalog loading, empty catalog, search loading, success, invalid local
input, unavailable/error, and explicit retry states. The UI maps only allowlisted HTTP status/code
classes to short Japanese recovery text and never displays raw exception bodies.
