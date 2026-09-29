# UI-01: Unified main page and optional two-school reference reports

Implementation: [#225](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/225).

Completed 2026-09-29 in independently accepted PR #227, head `f1b7b5c7a3cded5749c49de38355364c2732114f`.
[Final evidence](unified-workspace-acceptance.md). The release instructions and resource allowances
below are the historical implementation contract, not a new Ready task or budget reset.

Status: design approved in conversation; implementation becomes **Ready only after this design
PR merges and #191 records the one Issue release**. Milestone: M16 — Unified admissions workspace.
Owner: independent development Agent; design-main performs exact-head architecture/product review.
Dependencies: merged DISPLAY-01 #221 / PR #223, M15 closeout #224, [ADR0015](../decisions/0015-unified-admissions-workspace.md).
Base main: `5fb98c413f0c75ed2bb59d4cdbdae8ba7e8b3a59`.

## Background and visible goal

The accepted M15 integration has the correct reviewed GSFS evidence/report machinery, but its
separate page and link back to the Science Tokyo app violate the user's intended product flow.
The user approved the [interactive prototype](../ui-prototypes/unified-workspace-v1.html) on
2026-09-29 and instructed building that page. Do not repeat the split by wrapping two links in
a new landing page. This task changes the actual `/app` journey, not just navigation text.

Users choose either school in one dropdown, select the supported admissions scope, read concise
results and their evidence, optionally supply personal information, and click the same report
button to preview/copy a cited reference report. They stay on the same main page throughout.

## Scope / non-goals

In scope: common selectors, presentation capability adapters, same-page evidence/results,
optional personal comparison, deterministic legacy reference export, GSFS report presentation,
copy, error/loading/stale-state handling, responsive styling, old-path compatibility and evidence.

No new institutional/degree/edition coverage, new rules, GSFS search or QA, authority expansion,
LLM report summarization, exact PDF highlights, print/PDF export, user roles/accounts, persistent
profiles, uploads, framework migration or new frontend package. Keep existing Science Tokyo
advanced search/detailed reports usable, preferably folded into same-page advanced tools.

## Approved design and data mapping

Visual reference: prototype HTML and the adjacent desktop ISCT/UTokyo, report and mobile images.
The prototype is a design artifact only: never ship its placeholder conclusions, fixed two-field
ISCT profile, fake data objects, sample scope or prototype banner as production behavior.

| User control/action | Production source / behavior |
| --- | --- |
| School dropdown | Actual server catalog; both ready schools selectable in one control |
| Organization / program | Dependent validated choices; preserve all old ISCT options; GSFS only the supported target |
| Degree / edition / intake / route | Actual supported data, not hardcoded year arithmetic or filenames |
| 查看募集要项 | ISCT existing base-requirements API; GSFS accepted evidence GET; no report generation |
| 查看官方依据 | Dialog with exact required quotes/context and document/page/source; no invented locator |
| Personal information | ISCT existing supported fields/comparison; GSFS two employment conditions; optional |
| 生成参考报告 | ISCT current base/comparison presentation export; GSFS existing report POST; same visible action |
| Copy | Current preview's headings, scope, personal-context status, limits, findings and citations |
| Question area | Existing supported ISCT behavior; explicitly unavailable for GSFS, with no request/fallback |

The underlying ISCT document spans April 2027 and September 2026. Do not derive a fake admission
cycle from intake, drop the September option, or turn a document edition into a different route.
Use verified edition metadata or the official edition label; if a separate cycle is not represented
in the old contract, show an edition label rather than a fabricated selectable value. GSFS has an
explicit2027 cycle and A schedule. Display labels/CBMS alias are configuration, never routing keys.
Missing/unready GSFS config must leave all existing ISCT functionality usable.

## Checkpoint 1: mapping, current-result binding and report behavior

Deliver compact implementation notes and synthetic tests in the same Issue/PR before spending
real integration allowance. No separate Ready task is created for this checkpoint.

- Reuse current HTTP contracts and shared reviewed inputs. A capability adapter produces display
  models from validated server outputs. New UI code branches on capability kind, not names.
  A synthetic second slice/renamed school must exercise the same logic with unchanged identities.
- Update the additive catalog's availability/capability advertisement to match actual behavior;
  do not treat a false report capability as true only in hardcoded browser logic. Keep old field
  schemas and endpoints compatible. No global multi-school corpus registry is created here.
- ISCT report uses the full loaded base-requirements response, including dates and all displayed
  covered categories, not only what the old applicant-report intent happened to support. Preserve
  evidence lists, source pages, unknowns, status meanings, official deadline precision and scope.
  A visual filter must not silently drop findings; this report covers the full loaded selection.
- Optional personal data uses the existing comparison endpoint and its supplied-field validation.
  Retain the existing education, language and material-preparation inputs and distinctions among
  blank/unknown/not-yet/self-declared-not-applicable. Show current comparison/preparation features
  on the same page; do not remove them to match the prototype's abbreviated form.
- With no supplied profile, no fabricated applicant and no comparison call are necessary for
  ISCT. With changed personal data, one explicit generate action may obtain a fresh comparison;
  otherwise reuse a result only if target/input identity matches. Never use stale rendered DOM
  as authority. Cache at most current in-memory responses, not mutable certified report DTOs.
- This legacy report is a user-facing export of existing reviewed responses. It is not a new
  `ApplicantReport` schema, server-certified upload, or eligibility decision. Keep the existing
  `/v1/applicant-reports` API and detailed report tool unchanged and usable.
- GSFS keeps the exact report POST contract and raw server artifact/Markdown. Neutral report
  preview is a lossless presentation of statuses, conditions, missing fields and citations.
  Copy may add neutral wrapper headings but must not omit canonical limitations or change
  disposition semantics. Preserve raw artifact hashes in evidence; no trust/pin migration.
- GSFS unknown/unknown is a valid explicit report request; it must retain needs_information,
  not invent a personal match. E07 is enrollment context, not another application obligation.
- Neither adapter includes free-form QA output or raw ranked search hits in a reviewed report.
  Failed/missing citations or a mismatched response invalidate report/copy and show an error.

## Checkpoint 2: complete page and behavioral proof

- `/app` follows the approved header, selection card, results, optional report/profile area,
  evidence dialog and formatted report preview. `/app/reference` becomes an alias/redirect with
  no alternate split flow. Use responsive equivalents of the approved desktop/mobile layout.
- Both schools are in the same school control; switching never opens another page or resets to
  an unrelated entry. No role selection or personal details are prerequisites for browsing.
- Reports are optional; report preview and copy are not bare Markdown dumps. Normal views show
  concise Chinese explanations; exact Japanese evidence remains accessible. Do not hide actual
  historical/partial coverage, uncertainty or limitations under general marketing language.
- Display source titles, physical page numbers and printed labels when available. Preserve
  required quote context while translating internal basis/context IDs into understandable labels.
  Existing ISCT local-PDF links remain; GSFS uses official links. Do not promise exact highlighting.
- Retain ISCT comparisons, action groups and session-only preparation state. Changed target or
  relevant personal input clears affected comparison/report/copy; refresh clears personal state.
  Preserve old documented semantics for filters/checklists and the reference_only assistant.
- Target/evidence and profile/report lifecycles must be independent. Cover delayed evidence while
  a user changes employment or generates a report, delayed reports after input edits, A→B→A
  selection races, duplicate clicks and explicit retry. Display an error rather than endless
  loading after failure. There is no automatic report POST during selection/evidence browsing.
- Disable unavailable questions for GSFS with a clear short explanation. A query cannot reach an
  ISCT endpoint when GSFS is selected. ISCT QA remains connected to its current target/profile
  semantics and existing provider policy; this task authorizes no paid calls.
- Keyboard labels, focus management, Escape/close for dialogs, accessible status, readable mobile
  controls and clipboard/manual fallback are required. HTML/URLs must remain safe; no untrusted
  innerHTML, scripts, unsafe source URLs, browser profile storage or third-party assets.
- Existing CSP/no-store/no-referrer protections cover all new/changed page assets and redirects.
  Do not weaken headers to serve the inline-script prototype unchanged; production assets follow
  the repository's CSP-compatible external JS/CSS pattern.

## Compatibility and asset impact

Keep `service/app.py` and frozen release-gate inputs byte-identical. Reuse its existing endpoints;
implement route compatibility/catalog adjustments in the additive wrapper and static layer.
No schemas/rule facts or canonically accepted report contracts change. If implementation actually
needs a pinned-core change, return a concrete blocker rather than changing the gate hash.

The original391 runtime is `outputs/m10-09-deepseek-live/runtime-v1`; `jgrad-demo --workspace`
uses its parent. The frozen334 baseline is separate. Reuse the configured original GSFS candidate
and PDFs. Access denied is not missing data: use an approved execution context, never a new build,
private large copy or ACL modification. Query embeddings, if needed for the bounded ISCT smoke,
are distinct from building embeddings/indexes. No acquisition, migration, parsing or asset writes.
Do not stop the user's running preview server or reset their shared checkout. Use an isolated
development workspace and distinct loopback port; record ownership before starting/stopping it.

## Evidence, tests and bounded resources

Synthetic checks first: catalog filtering/dependencies, a second capability slice, missing config,
school/edition isolation, report mappings/citations, all supported profile distinctions, no-profile
and supplied-profile exports, request counts, invalid/mismatched responses, races, clipboard and
keyboard/mobile behavior. Use existing focused test suites plus meaningful new integration tests.
Run existing Quality CI; do not alter ranking golds or protected artifacts to silence diagnostics.
Record the previously known 391 ranking limitation if relevant; do not claim unrelated full-suite
success. Do not run old browser harnesses that parse/build during import.

New **UI-01** integration allowance is independent of exhausted M15 runs, not a reset:

| Resource | Total cap | Allocation |
| --- | --- | --- |
| Real service startups, including failures/restarts | 4 | developer3, independent reviewer1 |
| Explicit real report generations, including retries/client exports | 20 | developer12, reviewer8 |
| Real base-requirement/comparison or legacy detailed-report POSTs | 40 | developer24, reviewer16 |
| ISCT real local search smoke requests | 2 | developer1, reviewer1; cache-only existing model |
| Model/PDF downloads, paid calls, builds, migrations | 0 | all roles |

Each report activation is counted even if it produces only a local presentation. Its underlying
GSFS report POST counts in the same report row; an ISCT comparison call also counts in the POST
row. Do not hide nested calls. Pages/catalog/evidence GETs are read-only, limited to these sessions.
Per startup wall limit5minutes, per report/base/comparison operation60seconds, query120seconds,
browser session20minutes. Total real service wall time≤80minutes; one service per reviewer/developer
role at a time, no parallel asset/model experiment. No reruns merely to obtain prettier evidence.
Use synthetic pages for layout iteration; preflight dependencies/paths before real startup. RSS
cap12GiB and minimum system available memory4GiB; stop the owned process on limit/failure, log it,
and count the attempt. Stop any still-owned service at session end. No retry beyond remaining cap.
No model loading is required for report logic; metadata-only provider tests must disclose that
they do not prove retrieval quality. A real smoke uses the pinned existing cache, never download.

Use one cumulative Issue ledger: exact head, case/action, start/end, per-operation counts,
provider mode, pass/failure, resource stop and remaining role allowance. User-requested exploratory
use is not silently claimed as acceptance evidence or authority for additional automated runs.
Old DISPLAY-01 3/3 starts and7/7 report POSTs, RPT-01 3/3, import4/4 and MAT-01 3/3 remain closed.

Required real same-head browser cases per role (six minimum report activations):

1. ISCT no-profile report, then supplied-profile report; source citations and current target match.
2. ISCT another supported target (including a different intake where available), without carrying
   previous profile/report; verify the old catalog options were not reduced to prototype samples.
3. GSFS reports for the existing unknown/unknown, yes/yes and no/unknown employment cases, with
   exact canonical payload parity against retained accepted reports; no new CLI runs.
4. In those same cases, inspect evidence, copy, mobile and desktop and switch between schools.
   Capture actual request counts; no hidden automatic report requests. One offline ISCT search
   smoke checks routing if the existing local provider is available within the above allowance.

Hash/size/mtime the explicitly referenced protected source/runtime inputs before and after; no
recursive disk scan or large copies. Retain source-response-to-preview/copy parity evidence.
Commit an implementation review with representative readable screenshots, exact-head CI link,
raw artifact hashes, ledger, remaining limits and known gaps; keep private local assets ignored.

## Acceptance / failure / rollback

Pass only when the actual production page matches the approved common interaction and visual
structure, both report modes preserve evidence/unknowns, all prior ISCT supported behavior remains
accessible, cross-school state/request isolation holds, and real proof plus required CI pass.
Prototype screenshots or synthesized reports alone do not establish implementation completion.

Design-main reviews the exact PR head independently, including visual comparison. One Issue/PR
contains both checkpoints; no implementation phase is independently released in parallel. If an
unexpected change exceeds this boundary, report it before expanding scope. Preserve the original
Issue handoff through Ready→In progress→Awaiting review→Changes requested or Accepted/merged.

Errors leave the selected scope visible and explain the failed operation; they must not show
stale/example conclusions or switch school. Rollback reverts this UI/adapter change, restores
the former entry and leaves existing contracts/assets intact. No data cleanup is required.
M16 completes after this bounded unified workspace is accepted; no automatic highlighting,
expanded coverage or M13 release follows.
