# DISPLAY-01: Local evidence browsing and optional reference reports

Governance: #191. Implementation: [#221](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/221).
Milestone: M15. Depends on accepted #217 / PR #219 and documentation PR #220.
Base main `9f88d7271722be1b84de694a6d77f770e511c95a`.
[ADR0014](../decisions/0014-optional-reference-workspace.md) is the product/architecture contract.
Only this implementation may become Ready after its design PR merges; reuse M15 Main, one PR,
two checkpoints. Do not start another task concurrently.

## User-visible goal

A user opens a common local reference page, selects Science Tokyo or the available University
of Tokyo slice, sees exactly what is supported, and can inspect official evidence without
providing personal details. They may explicitly generate and copy a grounded reference report.
No teacher/student role is required. No report is generated automatically.

This increment deliberately uses the existing Science Tokyo workflow via a real navigation link.
It does not reimplement its four steps or pretend GSFS supports those same steps. The common
school selector must show both real capabilities when both runtimes are configured and validated.

## Scope and non-goals

Add a capability catalog, read-only GSFS evidence endpoint, report POST adapter, optional local
configuration, and one lightweight page in the existing FastAPI/static-JS app. Reuse CSS/components
where suitable; no new frontend framework or dependency is needed. Minor navigation/header copy
changes on `/app` are permitted; its existing form IDs, behavior and endpoint payloads stay intact.

Excluded: GSFS retrieval/indexing/QA, full eligibility/material/date coverage, uploads, accounts,
role selection, saved profiles/reports, telemetry, notifications, document refresh pipelines,
PDF viewers/highlighting/download/export, production schema migration, online generation or M13.
The optional ordinary browser opening of official source links is not an Agent PDF download.

## Checkpoint 1: server binding and API

### Configuration and lifetime

- Add an optional `reference_workspace_config_path` (absolute server-owned JSON) to service
  settings and `--reference-workspace-config` to the existing demo launcher. Default absent keeps
  the old launcher/API behavior. Do not loosen `--allow-runtime-build` / `--rebuild` requirements;
  the recorded launch command for this task must use existing391 runtime, no build flags.
- Config is closed schema1.0 with `slices` (1..4); each entry has unique `slice_id`, display names
  for institution/organization/program, five absolute paths `plan_path`, `trust_path`,
  `policy_path`, `policy_trust_path`, `seed_path`, plus `candidate_root` and `pdf_dir`.
  Identity and readiness derive from validated plan/data, not display labels. Duplicate IDs or
  duplicate target/plan bindings are invalid. Reject unsafe/link/reparse paths as in RPT-01;
  use bounded metadata reads, at most256KiB per config/plan/policy/seed input.
- Startup loads pins through `load_plan`, captures the original five candidate files/three PDFs
  using accepted readers and runs `verify_evidence_bytes`. Fail closed on any binding mismatch.
  Retain immutable raw bytes and a private immutable evidence presentation; never retain a
  caller-modifiable verified DTO as authorization. Source cap:64MiB per slice,128MiB total.
  Disabled/broken optional configuration must not break old ISCT initialization or readiness.
- Lifespan defines a fixed source snapshot. Later changes on disk take effect only after restart;
  display the edition/revision and snapshot digest, never imply live annual updates. No watcher,
  periodic audit, global persistent cache or second index. GETs and report POSTs read no source
  files after startup. Public report assembly still revalidates exact captured bytes on each POST.
- Reuse the old runtime catalog to advertise `legacy_applicant` only when that actual runtime
  validates. GSFS readiness is independent of embedding/generation provider availability. Names
  and target selections are configuration/data, not hardcoded school-specific Python/JS logic.
- Provide a checked-in example with placeholders and documented absolute-path setup; actual local
  paths live only in ignored config. Never commit PDFs, candidate copies, personal data or caches.

### Additive routes (schema_version1.0, closed request models)

| Method/path | Input | Output/behavior |
| --- | --- | --- |
| GET `/v1/reference-targets` | no query | `items` with opaque `entry_id`, `kind`, human labels, actual complete target for a slice, `availability`, coverage/limitations, capability booleans; legacy entry uses `/app` href and existing catalog identity without fabricating multi-source dimensions |
| GET `/v1/reference-slices/{slice_id}/evidence` | no query/profile | target and source snapshot identity, three topic descriptions, all8 reviewed records/23 fragments, original quote/hash, physical/printed pages, source title/official URL, basis/context/stage labels; no profile results/dispositions |
| POST `/v1/reference-slices/{slice_id}/reports` | accepted `MaterialConditionRequest`1.0 body | `{schema_version, slice_id, snapshot_id, report, markdown}` with the unchanged accepted report and its deterministic Markdown |

`snapshot_id` is SHA-256 of canonical server-owned plan/policy/seed/candidate/source content
bindings (not paths, time, labels or user input). No client can select paths, trust, hash overrides,
renderer output, a model or evidence objects. IDs must have bounded safe syntax and resolve only
against the in-memory allowlist; reject extras. Missing ID404; bad JSON/schema422; unavailable or
failed evidence/config503 with generic error envelopes and no local paths. GET catalog may return
an empty list or an explicitly unavailable known slice plus reason code; it must never return
ready=true for unaudited source data. A valid wrong target returns `not_covered`, conflicting
profile `target_mismatch`, with no quotations/topics, as RPT-01 specifies. No fallback to ISCT.

Covered POST calls public `assemble_report` using pinned server bytes and request bytes. An
internal formatter may format its fresh result within that same function before anything is
returned. Do not pass client DTOs into `_assemble_report`/`_render_markdown`. If an additive public
envelope helper is preferable, it must keep the same byte gate; no changes to existing schemas,
canonical accepted report bytes, pins or snapshots. Evidence GET must not call report assembly
with a made-up unknown applicant. Reuse accepted evidence verification and presentation data.

Response≤512KiB per report,≤1MiB evidence/catalog. Maximum report concurrency1 per service
process; excess429 without starting work. No automatic retry. Existing same-origin/error policies
apply; extend no-store/CSP/no-referrer/nosniff protections explicitly to the new page and assets.
Reject rendered HTML injection, use safe text nodes and validated https official URLs. No user
profile/request body logging or persistence. Normal access logging must not encode profiles in URLs.

Checkpoint1 handoff: synthetic route/config/trust tests, endpoint schemas, snapshot lifetime and
failure behavior; no intermediate real-source startup or report run merely to populate evidence.

## Checkpoint 2: page and state behavior

New `/app/reference`: “募集要项参考”. Link from `/app`; retain a return/navigation link. Visual order:

1. School selector, then visible supported research school/program/degree/cycle/route/schedule/
   intake for the selected capability. For current GSFS there is one fixed option in each dimension;
   do not invent empty choices for unsupported programs. Labels include 东京大学／新领域创成科学研究科／
   複雑理工学专攻／2027年度修士／一般选拔 A 日程／2027年4月入学.
2. Coverage card: GSFS is a historical fixed selection covering English score-sheet submission,
   checklist form submission and employment-related work/study plan only. It is not an open
   admission window or a full checklist. ISCT card lists its actual available workflow and opens
   `/app`; new page does not automatically call its report/comparison endpoints.
3. GSFS evidence topics can be browsed immediately, including full required context. Render
   Japanese quotes separately from Chinese labels. Every fragment has document/title, physical
   page and printed page if known, plus an official-source link. Document links may use `#page=N`
   with a visible note that browser behavior varies. No local PDF route or highlighting is added.
4. Optional “生成参考报告” area with two condition selects: currently employed by an organization,
   and intending to retain that employment at enrollment. Each offers unknown/null, yes,true,
   no,false; default unknown, never assume false. Clarify that these are conditions of the person
   whose application is being checked. Other profile fields are null; target_application binds to
   the selected target. Do not ask for name, age, role, employer or unrelated qualifications.
5. Only button activation submits one POST. Selection, evidence browsing, condition edits, page
   load and reset send zero report POSTs. During submission disable duplicate action. Display
   pending/success/error status accessibly; retry is another explicit click. All unknown still
   permits a report with needs_information rather than fabricated completion.
6. Generated result includes selected school/program/route/year, current input summary, the three
   statuses and missing fields, complete official citations, historical/partial limits. Distinguish
   “本条条件不适用” from “无需提交”. E07 stays enrollment context, not a fourth application duty.
   UI uses “参考报告”, not a teacher-only product label. `teacher_preview` and production_enabled
   remain untouched in the inner artifact; do not expose technical metadata as user instructions.
7. “复制报告” is enabled only for a current successful report. Copy all display identity labels
   plus unedited backend Markdown; mark any added display header as presentation, outside the
   signed/canonical artifact. Clipboard failure offers a selectable plain-text area, not false
   success. No new download/print engine. Escape content safely; no raw Markdown innerHTML.
8. Selection/condition change clears report and copy state and aborts/invalidates pending results.
   A slow old response must never appear under a new target or inputs, even after switching away
   and back. Track a monotonic request generation in addition to target/input identity. No storage,
   including localStorage/sessionStorage. Refresh clears inputs and results.

At1280px desktop and390px mobile: no horizontal overflow for citations/URLs; keyboard reaches
selectors, evidence disclosures, generate/copy; labels and live status exist. Reuse established
styles without redesigning unrelated ISCT forms or adding an LLM chat panel.

## Compatibility and asset boundary

Preserve old endpoint response schemas, `/app` behavior, existing five-item ISCT rules, source-PDF
range/HEAD behavior, query-intent/reference_only boundaries and health semantics. New slice status
is carried by its catalog capability, not by making the whole service unready. No mutations to
334/391, reviewed candidate, source locks, accepted trust JSON or retained outputs. No new index,
parser, knowledge store or institution-specific condition engine.

## Required tests and real evidence

Synthetic tests (unlimited reasonable focused runs):

- Config absent/bad/safe-path/duplicate/size cap, startup error isolation, request rejection and
  wrong-target/profile isolation. A synthetic different institution/variable topic count travels
  through identical service adapters; UI labels follow catalog, not hardcoded school branches.
- Existing quote/binding/fragment negatives survive API integration. Count source disk reads at
  startup only; report calls use public byte gate. Evidence GET never calls report assembly.
- Zero auto-report calls; one click one POST; double-click/concurrency; retry; late response after
  target/condition change; clipboard success/failure; refresh clear. Use browser execution, not
  only source-string tests, for these JS state behaviors. Mocked delays/errors are synthetic
  evidence, clearly distinguished from real-source acceptance.
- Relevant existing service/API/demo launcher/UI/report tests and frozen gate checks. Do not
  default to the whole real-PDF suite. Existing391 ranking diagnostic remains disclosed; no
  golden/asset changes to silence it. Run lint/diff and exact-head CI.

Real acceptance is a new HTTP/browser integration experiment, not a rerun of exhausted RPT-01 CLI:

- Use current original five candidate files/three locked PDFs and accepted plan/policy/seed under
  documented paths from RPT-01 implementation evidence. Use existing391 ISCT runtime; no copying
  or rebuilding. Local browser must reach the actual backend; no mocked GSFS catalog/evidence/
  report responses may be presented as real evidence. Use only three synthetic applicant cases.
- New DISPLAY-01 allowance: **2 real service starts total** (developer1, reviewer1), **6 covered
  report POSTs total** (developer3, reviewer3), exactly the three accepted employment cases per
  start. Each startup source-validation phase≤60s; each report≤60s; cumulative startup/report
  work≤8minutes. Browser observation≤20minutes per session. All failures/restarts/retries count;
  no reserved reviewer quota use by developer. Log attempts before starting; no hidden TestClient
  real startup. Catalog/evidence/page GETs in these same sessions do not consume report POST count.
- Use cached local providers only if existing ISCT launcher needs them; zero downloads/paid
  generation, no QA/model experiment. A service-only harness may reuse accepted runtime/config
  without initializing unused embedding models. Show actual old ISCT target/base requirements
  route works and report zero unexpected generation. Do not run old audit scripts that rebuild KBs.
- Record exact head, startup/HTTP commands, source/runtime paths and hashes, before/after source
  and protected-runtime hash/size/mtime, network counts, elapsed time, limits, each report hash and
  evidence counts. Compare all three inner reports/Markdown to retained accepted RPT-01 output
  (137963-byte JSONL SHA `ee27b3be0669fe05576542bc5c9b123ff91e4732884f888f00b4cf52613fa956`).
  The new envelope/header differs by design; do not compare whole new HTTP response to old JSONL.
- Retain ignored screenshots at desktop/mobile for both capability choices, visible source/pages,
  generated report and copy feedback; sanitize profiles (synthetic only). A checked-in short
  implementation review records commands, counts, hashes, budget and limitations. A non-Draft PR
  must hand off exact head and any hardening done after real proof; reviewer run reproduces final head.

Old budgets stay closed: RPT-01 CLI3/3, design source audit1/1, IMPORT-01 4/4, MAT-01 CLI3/3.
Do not invoke them. This new allowance exists only for service integration/browser validation;
it is not permission to tune parsing, re-experiment on reports, regenerate assets or start a
long-lived public service. Stop when evidence quota is exhausted; use synthetic fixes and hand
back the blocker. Browser package/runtime absence must be reported before any installation/download.

## Acceptance and rollback

Accept when a user can browse evidence with no report, explicitly generate/copy the fixed scoped
report, change target without stale content, and navigate to the existing ISCT flow; source/profile
boundaries, real source parity and old behavior pass. No assertion of full GSFS admissions support.
Rollback disables config/new entry and removes additive service/static code; retains all artifacts,
old schemas and `/app`. Failure returns honest unavailable/error states, not cached sample reports.
If two checkpoints cannot fit one focused implementation cycle, return a concrete blocker; do not
expand scope, bypass validation or start a dependent highlighter. Design independently reviews
the PR before merge; M15 exit is assessed afterwards, M16 is not automatically started.
