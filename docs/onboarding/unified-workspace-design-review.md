# UI-01 design review

2026-09-29, design-main self-review of the user's approved unified-page implementation Spec.
This is not an independent production implementation acceptance. No implementation was changed.
Repository/GitHub base main: `5fb98c413f0c75ed2bb59d4cdbdae8ba7e8b3a59`.

## Evidence and decisions

- M15 closed with9 closed issues and0 open; no open PR or other Ready implementation existed.
  #191 remains governance. M13 is paused and #177 remains closed. New [M16](https://github.com/yasu-isct/J-Grad-Admission-RAG/milestone/16)
  and [UI-01 #225](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/225) follow an explicit user
  approval, not the old overnight automation instruction.
- `service/static/app.html` already contains the school selector, personal comparison and advanced
  report/search tools. `/v1/applicant-reports` exists; previous UI design wrongly made report
  availability appear exclusive to GSFS. The broad main-page reference export instead projects
  already-validated `DemoBaseRequirementsResponse` plus optional `DemoApplicantComparisonResponse`,
  preserving all categories and dates without inventing query intent or changing the old report.
- `service/reference_contracts.py` carries separate `legacy_applicant` / `reviewed_material_slice`
  kinds. Their identity/request schemas remain separate beneath a common presentation.
  `reference_app.py` currently advertises legacy `reference_report=false`; UI-01 must update actual
  capability advertisement when the main-page export is implemented, not hardcode a browser bypass.
- The existing source snapshot and GSFS report POST remain the trust boundary. Source quote/page
  provenance and canonical report pins are preserved. Existing schemas need no incompatible change.
- `config/grounded_rag_release_gate_v1.json` pins `service/app.py`. UI integration can use static
  files and additive wrapper code; modifying or rehashing that core gate is not released.
- ISCT's catalog includes September2026 and April2027 under a single document; year/intake labels
  must follow official metadata, not prototype constants. Retain all real catalog options and
  profile fields; the prototype's abbreviated sample is explicitly not a scope reduction.
- The approved prototype's common question area does not authorize GSFS QA. Availability must be
  explicit and no GSFS request may fall through to the ISCT service.

## Product and resource gates

The standalone HTML and four PNGs are the exact prototype reviewed by the user. It has no real
source data, external requests or service dependency; inline script/style remain prototype-only.
Original Edge/Playwright inspection passed transitions and mobile layout with no page errors.
The implementation must provide real UI evidence alongside API/test evidence. The Spec includes
case counts, preserving unknowns and statuses, source/copy parity, separate request generations,
failure behavior and an explicit visual comparison. Data-only success is not sufficient.

The prior M15 service/report, importer and condition budgets are exhausted and stay closed.
UI-01 has a separately bounded allowance with developer/reviewer allocation and cumulative
failure accounting. No real source service, report, query, model, parser or index run occurred
in this design phase. No download, paid request or production asset change occurred.

## Validation and release

Design validation: relative links for new Markdown documents, source/committed prototype hash
identity, expected prototype school/report controls, `git diff --check`, changed-path inspection,
and repository Quality CI on the exact design head. UI scripts remain in `docs/ui-prototypes`,
not production. No extra production test suite is justified locally for these docs/assets.

After design PR merge, update #225's single handoff to Ready and record it once in #191.
Implementation remains the independent development Agent's responsibility. No other Ready task,
new developer chat, or implementation is created by this design work. M16 exit follows UI-01
independent review and acceptance; no automatic successor milestone is authorized.
