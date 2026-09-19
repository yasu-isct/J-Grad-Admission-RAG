# Local Applicant Demo And Evidence UI

DEMO-01 makes a Simplified Chinese application-check wizard the primary local workflow while
retaining APP-04A evidence search and APP-04B's detailed report as auxiliary tools. Open
`http://127.0.0.1:8000/app` after starting `jgrad-serve` with at least one explicit reviewed report
plan and page-scope manifest. The browser first loads the server-owned target hierarchy, then asks
for base requirements only after the user completes and submits a target. DEMO-02 then accepts a
minimal, non-persistent applicant snapshot and asks the service for a conservative comparison.

```text
audited manifest + reviewed policy + lifespan plans
  -> GET /v1/target-catalog
  -> choose School / Degree / Intake / College / Department / optional Route
  -> POST /v1/base-requirements
  -> reviewed dates, p.10 materials, eligibility prompt, language rules + exact evidence
  -> enter education / English / Japanese / material preparation
  -> POST /v1/applicant-comparison
  -> separate official applicability and applicant preparation states + exact evidence
  -> server-derived counts, action groups, and bounded next actions
  -> filter the partial preparation view without re-running rules in the browser

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

The base-requirements step remains profile-free. `required`, `conditional`, `needs_information`, and
`not_covered` describe official requirement coverage, not the applicant's preparation or final
eligibility. RULE-05A exposes only the five reviewed p.10 common materials. The three
qualification-path-dependent items remain `needs_information`; p.11 mixed foreign-national and
scholarship material is not projected. Conditional program evidence is absent unless a later
reviewed catalog explicitly exposes its route.

The personal comparison step keeps blanks as `null` or an explicit `unknown` material state.
Changing any target or personal field cancels and invalidates the pending request and clears the
old result. Academic status is limited to a possible path match or a need for individual review;
English data is recorded for target-rule comparison; Japanese remains only “recorded” or “needs
information” because current evidence does not support a satisfaction conclusion. Material
official applicability and the user's preparation state are displayed independently. Refreshing
the page clears every personal field, and neither browser storage nor server-side persistence is
used.

STEP 4 displays the service-returned target summary, partial-checklist warning, reconciled counts,
and next actions. Native radio controls filter the already classified `action_group` values for
all items, items needing more input, recorded items, or review/uncovered items. Filtering changes
only visibility; it does not calculate readiness, eligibility, material applicability, or counts.
Changing any STEP 3 input hides the entire old STEP 4 view until an explicit new comparison succeeds.

Every requirement with evidence opens a modal side drawer. It displays the official title,
school/intake, exact pages, server-returned Japanese text, safety limitation, and source link.
Fact ID, document ID, and scope stay in collapsed technical details. Because the official source
URL does not guarantee a stable page fragment, the UI opens the official source and separately
instructs the user to inspect the returned page number.

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

For reviewed paths (4)-(8), the same credential row also exposes Japan-coursework, program duration,
and institution/program/completion-timing/person verification controls. The completion-timing
control means that path (7)'s completion point has been checked against the ministerial effective-
date condition; it does not ask the browser to calculate a date. Their Japanese options preserve
the API's three states: applicant claim, official confirmation, and explicit non-confirmation.
Leaving a control at `不明` sends `null`, so the server can return an exact missing-information
request.

## Configuration

The document catalog is available only when reporting is configured with one or more repeatable
absolute `--report-plan` paths and one identity-matched absolute `--page-scope-manifest` path per
enabled document. On every catalog request, the service reloads and audits the current manifest and
reviewed version policy. It returns only ready documents with exactly one matching lifespan-loaded
plan and page-scope manifest. Public catalog identities omit PDF/KB hashes, paths,
index/provider/model configuration, predicates, and evidence text.

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

Native labeled form controls, visible keyboard focus, a polite live status region, a native modal
dialog with focus restoration, and a responsive single-column fallback cover target-catalog and
requirements loading, parsing, report generation, complete,
needs-information, needs-review, not-applicable, invalid local input, unavailable/conflict,
explicit retry, and clear states. The UI maps only allowlisted HTTP status/code classes to short
Japanese recovery text and never displays raw exception bodies.
