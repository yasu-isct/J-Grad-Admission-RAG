# ADR 0014: Optional reports in a capability-based local reference workspace

Status: Accepted when this design PR merges; implementation requires the linked DISPLAY-01 Issue
to be Ready. Owner: #191. Base main: `9f88d7271722be1b84de694a6d77f770e511c95a`.

2026-09-29: **presentation decisions partially superseded by [ADR0015](0015-unified-admissions-workspace.md)**
after the user rejected the split entry and approved the unified-page prototype. Separate
page/legacy-link/no-common-presentation decisions below describe historical M15 scope, not the
next product design. Evidence validation, snapshot/privacy and protected-asset boundaries remain.

## Product decision

The user clarified on2026-09-28 that a reference report is an optional button action. The product
is not restricted to teachers or students. Teachers are the first demonstration audience, not an
authorization role. Browsing official evidence must not require a report or personal information.

The next milestone increment makes the two actual capabilities discoverable in one local entry:
Science Tokyo's accepted applicant workflow and the University of Tokyo GSFS Complexity Science
and Engineering fixed historical materials slice. Neither a second school name nor a report
button means complete admissions coverage. All material conclusions keep their reviewed provenance.

## Evidence from main

- `/app` is a four-step Science Tokyo workflow in `service/static/app.html` and `app.js`.
  Its `/v1/target-catalog` and `DemoTargetRequest` derive from existing single-document report plans.
  GSFS's multi-source target cannot be inserted into that old schema by inventing a document ID.
- `/v1/reviewed-documents`, `/v1/base-requirements`, `/v1/applicant-comparison` and
  `/v1/applicant-reports` already implement the old accepted journey. Keep them compatible.
- PR #219, accepted at `a72989ee95e76646da00e344835786a09aee7c08`, supplies byte-bound public
  multi-source assembly and externally recomputed report loading/rendering. No GSFS search index
  exists and its candidate is not a production-approved KB.
- `ServiceSettings` and `create_app` support additive settings and lifespan state. PDF serving
  currently binds one source document; replacing it with an unbounded filename route is unnecessary.
- Existing security headers match `/app` exactly; a new page needs explicit equivalent protection.
- Some legacy browser audit scripts invoke `build_document_kb` at import time. Reusing those
  scripts would violate asset/build budgets; borrow assertions or use retained runtime instead.

## Decision

1. Add `/app/reference`, titled “募集要项参考”, with one school selector and visible capabilities.
   Add a navigation link from `/app` and a return link. Keep `/app` and old endpoints operational.
   This is an additive entry in the same app and static asset stack, not a second application.
2. Science Tokyo uses a server-derived catalog entry and an “打开申请检查” link to `/app`.
   It keeps the existing target selector/profile behavior there. GSFS exposes its actual fixed
   target, three evidence topics and optional report action in the new entry. Do not implement
   a common report format for incompatible old/new schemas in this increment.
3. Use a small service presentation catalog with backend capability kinds `legacy_applicant`
   and `reviewed_material_slice`, keyed by configured IDs and complete targets. Branch on
   supported capability, never `if school == utokyo`. A synthetic second slice proves portability.
   This catalog routes interfaces; it is not a second corpus/index registry.
4. A server-owned opt-in config binds each slice to the accepted plan/trust/policy/seed and
   original candidate/PDF locations. Capture immutable bytes and validate them at startup;
   freeze that exact snapshot until restart. No filesystem watching, refresh jobs or auto-build.
   Browsing uses a separately projected reviewed evidence snapshot, never a dummy applicant report.
5. Generate only on an explicit button POST. Reuse the accepted public byte gate for that POST;
   formatted output may use the internal formatter only immediately on its fresh gate result,
   as the accepted CLI does. Never accept evidence/report objects or trust metadata from a client.
   Revalidation uses captured bytes, so no new disk reads per profile and no mutated DTO cache.
6. Keep `audience=teacher_preview` in the pinned underlying artifact unchanged; it is historical
   contract metadata, not access control. The outer UI uses neutral names and preserves historical,
   partial-coverage and no-final-eligibility limits. No role/account system is introduced.
7. Invalidate report/copy state on any relevant selection or condition change. Cancel or ignore
   late responses by request generation ID plus target/input identity. Browser refresh clears
   personal inputs/results. Copy is explicit and includes school/program/edition, limitations
   and official citations; no background clipboard writes or local storage.

## Scope and implementation order

Only [DISPLAY-01](../onboarding/optional-reference-workspace-spec.md) is released after design
merge: two checkpoints, one PR in the existing M15 Main chat (service binding, then UI/browser
proof). Its Spec defines the new bounded HTTP/browser budget; old budgets remain exhausted.
No full redesign, GSFS vector/keyword search, natural-language routing, new admissions topics,
PDF uploads/serving/highlighting, print/PDF export, institutional roles, paid models, source
downloads or public deployment. Official-source links with physical page labels suffice here.

## Exit and rollback

Verify the real loopback journey without mocks for source/report responses, prove zero report
POSTs before a click, and preserve ISCT behavior and source assets. Missing/bad slice configuration
disables that capability without disabling the legacy app. Removing the optional config and new
entry reverts presentation; no schema migration, KB promotion or asset deletion is needed.
M15 closure remains a separate exit review; no M16 or highlighting task is released automatically.
