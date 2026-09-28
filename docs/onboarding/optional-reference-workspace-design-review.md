# DISPLAY-01 design review and handoff

Date:2026-09-28. Owner:#191. Implementation:#221. This is design self-review, not implementation
acceptance. Base main `9f88d7271722be1b84de694a6d77f770e511c95a`; #217/PR #219 is accepted,
PR #220 closed its docs. M15 is open. No other implementation Issue was Ready at this audit.

## Read-only findings and choices

| Existing boundary | Evidence in main | Design consequence |
| --- | --- | --- |
| Single-document applicant flow | `service/demo_requirements.py` DemoTargetRequest includes document_id; catalog derives old reviewed plans | New additive capability catalog; do not force multi-source GSFS into this schema |
| Existing four-step page | `service/static/app.html`, `app.js` | Keep `/app`; add `/app/reference` plus navigation rather than a risky full rewrite |
| Trusted report entry | `reasoning/material_slice_report.py` public assembly/loading/rendering after PR #219 | Service uses server-owned raw bytes; no client evidence DTO or self-asserted verified flag |
| Old report readiness | `service/app.py:_report_service_ready` depends on old plan/scope settings | New optional slice failure independent of old API/health; advertise capability readiness separately |
| Current source PDF route | One VerifiedSourceDocument; hash-bound GET/HEAD/range | No general filename serving route for three new PDFs; use official URLs/pages in this task |
| Page security | `_secure_response` checks `/app` exactly | Extend equivalent CSP/no-store/etc to new page explicitly |
| Local launch | `demo_cli.py` binds loopback, default no build; `ServiceSettings` supports additive config | Optional config flag, retain no-build protections and old defaults |
| Browser harnesses | `run_demo01_browser_audit.py` and `run_rule04g_browser_audit.py` build KB at import | Do not execute those scripts; new real harness reads retained runtime only |
| Audience pin | MaterialSlicePlan/Report carry literal teacher_preview | Keep pinned schema/output; UI neutral wording and no user-role requirement |

The user explicitly requested the optional report button and a broader audience. The simple
initial integration routes ISCT to its working existing flow, instead of asserting equivalent
coverage between schools. GSFS browsing includes complete approved quotes/context before any
profile or report action. School-specific labels belong in configuration; adapter behavior is
capability based and exercised with a synthetic alternate institution.

## Self-review checks

- Scope has one user journey and two checkpoints; no dependency on PDF highlighting or new search.
- Endpoint status/error behavior, input authority, immutable snapshot lifecycle, safe paths,
  source limits, request-generation invalidation and copy semantics are explicit in the Spec.
- Evidence GET does not generate an unknown-applicant report. Report source checking remains the
  accepted gate; private formatting is only within the freshly validated backend flow.
- No accepted pins, production schema, 334/391 or candidate mutation; rollback removes optional
  configuration/entry. Old source-PDF and report routes keep contracts.
- Old budgets are closed. New service/browser proof is separately bounded to two real starts/six
  report POSTs with developer/reviewer quotas, failure accounting and a ban on rebuild harnesses.
- Real data is not read again in this design session. No CLI report, service startup, browser
  experiment, model/API call or download was executed. DISPLAY-01 starts0/2, POSTs0/6.
- Existing391 ranking diagnostic stays disclosed. No full-suite rerun is needed for these docs.
- Publication checks: relative document links, referenced code paths, whitespace/diff and design CI.

## Handoff

Merge this design before marking #221 Ready. M15 Main uses the complete Spec and same chat,
updates one Issue handoff and returns one non-Draft PR with exact head and evidence. Design
independently reviews trust/identity/real-browser behavior before merge. No second task is Ready.
After DISPLAY-01 acceptance, assess M15's exit boundary; do not automatically launch M16 or a
highlighting experiment. M13 remains paused, #177 closed and the assistant reference_only.
