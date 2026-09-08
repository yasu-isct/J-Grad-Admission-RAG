# Local Evidence And Applicant Report UI

APP-04A adds evidence search and APP-04B adds a separate applicant-report workflow. Open
`http://127.0.0.1:8000/app` after starting `jgrad-serve` with at least one explicit reviewed report
plan and an explicit query-intent catalog. The page lists only safe reviewed documents. Its first
tab sends one-document evidence searches to `/v1/corpus/query`; its second tab parses a bounded
Japanese question server-side and submits the existing APP-03D report request.

```text
audited manifest + reviewed policy + lifespan plans
  -> GET /v1/reviewed-documents
  -> choose exactly one document
  -> POST /v1/corpus/query
  -> exact server-ordered evidence candidates

question -> POST /v1/query-intents/parse -> validated QueryIntent
profile + intent + one document -> POST /v1/applicant-reports
  -> partial readiness, findings, diagnostics, and exact evidence
```

## Boundary

This screen answers where the official guideline contains potentially relevant text. Each result
shows the returned document title and ID, Fact ID, official pages, exact search text, section path,
scope, Fact type, and vector/lexical/fusion diagnostics. Results are evidence candidates, not rule
applicability, overall eligibility, admission probability, or a recommendation.

The report form exposes the supported target application, one academic credential, age/experience,
and individual-review fields. The credential includes country, degree level, reviewed basis,
completion state, completion/expected date, and years of education. Unknown values stay explicit
JSON `null`; blank is never treated as false or zero. Citizenship/residence members and the
language-test collection remain null in this form. The browser does not infer intent, evaluate
rules, rebuild traces, or create citations. The UI does not alter selection, ranking, provider
lifecycle, or corpus state.

## Configuration

The document catalog is available only when reporting is configured with one or more repeatable
absolute `--report-plan` paths. On every catalog request, the service reloads and audits the current
manifest and reviewed version policy. It returns only ready documents with exactly one matching
lifespan-loaded plan. Public catalog identities omit PDF/KB hashes, paths, index/provider/model
configuration, predicates, and evidence text.

The UI limits a question to 1,000 characters as a conservative browser input bound and submits the
existing strict query schema with `top_k=5`, `candidate_k=20`, empty filters/preferences, and
`allow_multiple_documents=false`. Refreshing the page clears question and results.

Enable report-form intent parsing with one absolute server-owned
`--query-intent-catalog D:\jgrad-config\query_intent_catalog_v1.json` path. It is loaded only during
service lifespan through the accepted RSN-02 loader. Omitting it leaves evidence search and the
existing report API compatible, but the browser report workflow is unavailable. An invalid
configured catalog fails readiness closed. The parser accepts only a non-empty question of at most
1,000 characters and rejects unrecognized or ambiguous intent with a fixed `invalid_request` error.

## Report Walkthrough

Select one reviewed document, open **申請条件レポート**, and enter a question containing a reviewed
intent phrase such as `情報理工学院の出願資格`. Fill only facts you know. Leaving age blank sends
`age_at_enrollment: null`, while entering `0` sends zero; choosing "いいえ" sends false. Contradictory
individual-review or credential completion fields are blocked before submission. The form submits
at most one credential; multiple-credential selection remains a server-side fail-safe rather than
a browser-side best-match guess.

The result labels `complete`, `needs_information`, or `needs_review` as report preparation status.
It then preserves server order for rule findings, missing fields, interaction/process diagnostics,
and exact Fact/page/text evidence. Codes remain visible beside Japanese labels. Use
**入力と結果を消去** to clear both workflows; changing the document clears the report and requires
an explicit resubmission.

## Offline And Privacy

HTML, CSS, and JavaScript are package data served only from `/app`, `/assets/app.css`, and
`/assets/app.js`. They require no npm build, CDN, framework, analytics, telemetry, or internet
connection. The installed wheel resolves assets from its package location, independently of the
current working directory.

Untrusted catalog, profile-adjacent response, error, query-result, and evidence values are inserted through DOM text
properties only. The implementation uses no HTML string insertion, dynamic script execution,
browser storage, cookies, service worker, query-string state, automatic clipboard access, or
logging of queries/evidence/profile data. It never renders returned Markdown or exposes report hashes.

The UI and API return `no-store`, `nosniff`, and `no-referrer` headers. UI assets additionally use a
restrictive self-only Content Security Policy, denied framing, and disabled sensitive browser
permissions. These controls are scoped so existing `/docs` and `/openapi.json` behavior remains
unchanged. The service remains loopback-only development software without authentication, TLS,
rate limiting, or public-hosting hardening.

## States

Native labeled form controls, visible keyboard focus, a polite live status region, and a responsive
single-column fallback cover catalog loading, parsing, report generation, complete,
needs-information, needs-review, not-applicable, invalid local input, unavailable/conflict,
explicit retry, and clear states. The UI maps only allowlisted HTTP status/code classes to short
Japanese recovery text and never displays raw exception bodies.
