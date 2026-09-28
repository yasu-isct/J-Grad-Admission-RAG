# Post-single-school Design Handoff

Updated 2026-09-29 after user approval of the unified-page prototype. M15 was technically closed
in PR #224 (`5fb98c4`); its split-entry product design is superseded for the next implementation.
Design continuation below was recorded after the user's GSFS target/download decision.
Always re-read current GitHub
state before acting; this checkpoint is a compact starting map, not a higher authority than `main`.

## Latest decision: implement the approved unified page

The user rejected the separate `/app/reference` journey and approved
[this interactive prototype](../ui-prototypes/unified-workspace-v1.html), then explicitly asked
to build it. Read [ADR0015](../decisions/0015-unified-admissions-workspace.md) and the full
[UI-01 Spec](../onboarding/unified-workspace-spec.md). M16 is one bounded implementation, with
data/report mapping and UI/browser checkpoints in one development context. Only
[UI-01 #225](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/225) is eligible
for Ready after design merge; obtain its live Issue state from #191, not historical Ready sections.

The main page has both schools in one dropdown; GSFS offers only the existing Complex Science
scope. Reports are optional for both. Preserve all supported ISCT functions; its common report
exports reviewed base/comparison results, while GSFS retains its byte-bound report endpoint.
No profile is required for browsing or general reference export. Follow prototype layout, replace
all sample data with actual responses, preserve official evidence and show real coverage limits.
No GSFS QA, new sources, core schema/gate changes, asset builds or M13 work. The prototype's two
ISCT fields and one example program do not authorize reducing existing functionality.

M15 remains closed. Its budgets stay exhausted; UI-01 has its own bounded read-only integration
ledger, including independent-review reserves. The user's live preview process is separate;
never stop/reuse it as an acceptance service without checking ownership. No production code was
changed during this design phase. Historical handoffs below are retained for traceability.

## Required read order

1. `README.md`
2. `docs/releases/single-school-portfolio-v1.md`
3. `docs/architecture.md`
4. `docs/roadmap.md`
5. `docs/deployment-architecture-v1.md`
6. [GitHub #191](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/191) (long-lived design-main charter)
7. [GitHub #177](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/177) (bounded MinerU 4.x pilot)
8. Current open Issues, PRs, milestones, checks, and review threads

Do not load the full historical chat as the primary specification.

## Current GitHub state

- M15 is complete after #221 / PR #223; [release boundary](../releases/m15-reviewed-materials-preview.md).
  No next implementation is Ready; M16 and highlighting are not automatically released.

- M1 through M10 are complete; the documented local portfolio release is v1.4 plus ART-01 runtime
  lifecycle hardening.
- #183 / PR #184 are complete: normal Demo startup is reuse-only and explicit paths can be
  inventoried without mutation.
- M13 DEPLOY-01 #185 / PR #186 are complete as research/design only.
- M13 implementation issues #187-#190 are open but explicitly paused by the user pending external
  consultation. They are not Ready and authorize no cloud resource or asset upload.
- #163 remains open for missing official language/score-conversion coverage.
- #177 / PR #200 are closed as an accepted failed-experiment audit with a reject decision.
  M14 ends with explicit unresolved handoff; no candidate parser is approved.
- #191 is the durable design authority/workflow entry for the next design-main agent.
- #192 is closed; documentation-only closeout PR #193 is merged and main Quality passed.
- No open PR existed at the post-closeout audit. This snapshot does not describe later design PRs.
- The user selected GSFS Complexity Science and Engineering as the first new program and
  authorized downloads. Four exact official PDFs are locally acquired; see the
  [source lock](../onboarding/utokyo-gsfs-complex-2027.md). GSFS's bounded reference preview is now
  available through optional local configuration; no full production KB/index activation is enabled.

## Product and authority boundary

The shipped product is a local, single-school applicant Demo for one exact Science Tokyo master's
guideline edition. `ScopedFact` plus official pages remain authoritative; immutable indexes are
derived search assets; retrieval proposes evidence; reviewed rules determine structured
applicability; DeepSeek is an optional `reference_only` wording/planning layer. Applicant Profile
values are not sent to M10 model calls.

## Artifact identities and roles

- historical: schema 0.5 / 298 vectors / KB prefix `8223fb91...`;
- frozen semantic baseline: schema 0.6 / 334 vectors / KB `b24f85ec...`;
- current product runtime: schema 0.6 / 391 vectors / KB `7fa46e49...`;
- official PDF SHA-256:
  `57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735`;
- embedding identity: `sentence-transformers`, `BAAI/bge-m3`, pinned revision
  `5617a9f61b028005a4858fdac845db406aefb181`, dimension 1024.

These identities are roles, not interchangeable size choices. Do not rebuild, delete, move, link,
or declare duplicates safe without a separately approved reference audit and dry run. Machine-local
paths are intentionally omitted.

## Accepted limitations

- one institution/document edition and reviewed product slice;
- local loopback only; M13 is deferred, not complete or abandoned;
- incomplete JLPT/J.TEST/score-conversion authority under #163;
- the 391-row KB includes conditional/reference material and layout noise, so pre-retrieval scope
  isolation is required;
- browser-dependent PDF fragment navigation;
- process-local answer cache;
- MinerU #177 is closed with a rejected-execution audit; no parser adoption or rerun is authorized.

## Design-main workflow

Use GPT-6 Astra for architecture, migration, data-destructive decisions, issue decomposition, and
high-risk review. Use a workhorse coding agent for one bounded implementation Issue at a time.
Durable decisions belong in GitHub and versioned ADR/docs. Each PR needs real data and architecture
evidence in addition to tests. Never release multiple dependent implementation Issues at once.

## M14 closeout and unique next design step

The [read-only coupling audit](../audits/single-school-coupling-2026-09-27.md) is complete and
[ADR 0008](../decisions/0008-multi-school-compatibility.md) has partially accepted design boundaries. The
[development lessons](../development-lessons.md) retain the user's retrospective without relying
on private notebook access. MS-01 / #195 provides the
[fixed target/source-set contract](../onboarding/gsfs-source-set-contract-v0.1.md), concrete examples,
compatibility matrix and candidate parser contract. MS-02 #197 / PR #198 is accepted: 83 real pages
preserved, 61 focused tests and CI passing, exact source/report identities independently verified.
Baseline checklist omissions/duplication remain disclosed comparison findings.

These tasks and #177 belong to [M14](https://github.com/yasu-isct/J-Grad-Admission-RAG/milestone/14),
now closed with [ADR 0009](../decisions/0009-mineru-4.0.7-pilot-fallback.md) and the
[rejected-execution report](../onboarding/mineru-4.0.7-pilot-report.md). The audit establishes
21 retained runs / 388 attempted page-passes against 168 allowed, with 3813.905 recorded worker
seconds. Legacy scores 30/41 and Flash 33/41 observationally; Basic is incomplete/unscored.
Undrained PIPEs may have stalled Basic, so no inherent MinerU/CPU latency conclusion is justified.
Runner/worker execution is closed. No fresh ledger, output directory or model switch resets budgets.

Design main independently verified 130 historical files, all 41 Flash locators, four MS02 reports,
55 focused tests and exact-head CI. Current 334/391 vectors/payloads and product KB hashes match
established identities; historical pre/post and provider/network/resource evidence gaps remain.
No new-school runtime, fallback routing or candidate rerun is authorized.

## M15 current release point

The [evidence-gap assessment](../onboarding/gsfs-evidence-gaps-and-next-slice.md) is complete for
the first bounded materials slice. [ADR 0010](../decisions/0010-reviewed-source-evidence.md)
defines pre-KB reviewed excerpts, not a second rule engine or direct applicant-answer store.
Design main visually rechecked common p6, department pp28/40 and additional p1, then recorded
[eight design-reviewed excerpts](../onboarding/gsfs-material-evidence-seed-v1.json) across three topics.
Reviewer kind is Agent, not human; manual transcription has no fabricated parser locator/bbox.

Completed and independently accepted: [EVID-01 #202](../onboarding/reviewed-source-evidence-spec.md)
in [M15](https://github.com/yasu-isct/J-Grad-Admission-RAG/milestone/15): strict generic evidence
loading/audit and operator previews for English score sheets, checklist submission and work/study
plan conditions. Exact target/source-set/PDF/review identities gate output. No production KB,
rules, API/UI, model/parser calls or downloads were introduced. PR #204 is merged; 96 focused
tests passed, all six real previews were independently reproduced, three source hashes and four
page images checked. [Exact-digest acceptance](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/204#issuecomment-5856769317)
covers only revision 1 operator evidence inspection. M15 remains open.

BUILD-01 #206 is complete in PR #208. Independent review passed 179 focused tests, checked
unchanged legacy function/constant ASTs, retained canonical KB parity and actual protected assets.
The initial developer report confused an old 298 index with the frozen 334 baseline; the merged
[asset-binding correction](../onboarding/build01-implementation-review.md#independent-design-review-correct-asset-bindings)
records the verified paths/hashes and evidence limits. The reviewer did not run another real build.

[IMPORT-01 #209](../onboarding/reviewed-fragment-import-spec.md) is accepted in PR #211, under
[ADR 0011](../decisions/0011-explicit-build-profiles-and-reviewed-lineage.md). It maps eight records /
23 exact fragments into three existing-schema candidate KBs (2/12/9 Facts), with document-qualified
lineage, complete required context, immutable publication and verified reuse. Mixed-degree source
identity remains truthful; Fact scope stays unknown and production quality gates remain failed.
No parser, index, registry, rule or API/UI activation is released. The Spec includes reviewed source
identities, input pins, deterministic field/ID rules, publication contract and shared real-run budget.
Independent re-review accepted final head 5e0412e: 153 focused tests passed, three Windows symlink
skips covered by Linux CI; both context-binding and CI-fingerprint findings resolved. Actual source
hashes, five candidate files,23 exact fragments and complete E02 context passed with unchanged
bytes/mtime. All four real calls are consumed; final review peak89,714,688 bytes and0.4473403s.
Developer historical unmeasured RSS and the unrelated local391 row-order diagnostic remain disclosed.
[Acceptance](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/211#issuecomment-5862212992).
[ADR 0012](../decisions/0012-material-conditions-and-report-boundaries.md) defines
[MAT-01 #213](../onboarding/material-condition-spec.md), accepted in PR #215: a shared
predicate/tri-state core and a compatible profile envelope with two employment facts.
Pinned policy data covers three topics, while previews expose conditions only, not obligations.
Existing profile/rule/report schemas and the ISCT five-item behavior stay unchanged. No PDF/KB reads
or IMPORT-01 calls; its exhausted budget stays closed. MAT-01 preview budget is now 3/3 exhausted
(developer 2/2, reviewer 1/1). Reuse the same M15 Main chat after a new Spec is released.
Independent final-head review (`573caa4f`) passed 339 focused tests, with six local Windows symlink
skips and green Linux CI. The full-binding consistency defect was fixed; three preview lines
were reproduced byte-for-byte in 0.4182928s (4801 bytes, SHA-256
`4ed106a8b6bf2511b127e4ef52c093be2ac8348b334868d88421ea25df1e46c5`).
[Acceptance](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/215#issuecomment-5863028868).
The accepted report boundary is [ADR0013](../decisions/0013-reviewed-material-report-slice.md) and
[RPT-01 #217](../onboarding/material-slice-report-spec.md), merged in PR #219
(`d7f7b2934c140bd332e9e3c9e7beea4c6ef3ffa3`). It validates a separately reviewed partial multi-source evidence projection
and emits a teacher report in JSON/Markdown. Raw candidate scope and failed full-KB quality gates
remain unchanged; this is not whole-KB production approval. No old report validator is relaxed.
[Design evidence](../onboarding/material-slice-report-design-review.md) records four retained-page
visual checks and one existing candidate/source audit:23 bindings,8 records,5 relations.
Independent review accepted head `a72989ee95e76646da00e344835786a09aee7c08`, resolving the
public assembly/render trust-boundary P1. External pinned bytes are revalidated; modified
evidence DTOs cannot enter public assembly and altered reports fail recomputation before rendering.
406 focused tests passed, nine Windows symlink skips, exact-head CI green. The final reserved
real call reproduced three reports byte-for-byte in0.6774364s,137963 bytes, SHA-256
`ee27b3be0669fe05576542bc5c9b123ff91e4732884f888f00b4cf52613fa956`.
Five candidate files, three PDFs and the developer's retained output had unchanged hashes/mtimes.
[Acceptance and original resolved finding](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/219#issuecomment-5866299464).
RPT-01 report budget3/3 exhausted (developer2, reviewer1), total2.1609334s; design audit1/1 consumed.
IMPORT-01 remains4/4 and MAT-01 preview3/3. The existing391 fixed-ranking diagnostic is disclosed,
not repaired by changing protected assets; this acceptance does not claim a fully green local suite.
The accepted presentation contract is [DISPLAY-01 #221](../onboarding/optional-reference-workspace-spec.md)
under [ADR0014](../decisions/0014-optional-reference-workspace.md), independently accepted and merged
in PR #223 at head `67e572757d7b055122799bdf7d95aea6d38cb912` (merge `3da2964e45046ee736936dee1751425458b6a29c`).
The new common entry links to the existing ISCT workflow and provides actual GSFS evidence browsing;
reports are optional explicit button actions, never a prerequisite of browsing. No teacher/student
role gate. Changed selections/conditions invalidate report/copy and late responses.
Pinned `teacher_preview` artifacts remain unchanged; neutral UI wording is a compatible presentation.
The delayed-evidence P2 is fixed and preserved in the [single review record](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/223#issuecomment-5869795291).
Independent179 focused tests passed,3 local symlink skips, CI green. Final real browser verification
covered two ready capabilities,3 topics/8 records/23 fragments,3 byte-identical reports, zero automatic
report POSTs and desktop/mobile copy, with22 input files unchanged. Old app/catalog/base-requirements
were exercised; embedding/QA were deliberately not exercised by the metadata-only provider.
After a user-authorized developer supplement, DISPLAY-01 is **3/3 service starts and7/7 covered
POSTs exhausted** (developer2/4, reviewer1/3). Final reviewer work0.609s, browser3.250s; cumulative
work about1.689s and browser9.109s. Evidence lives in `outputs/review223-real/`, without overwriting
developer artifacts. Old exhausted budgets stay closed. M15 is complete; no next task is Ready.
No new parser/model, GSFS index/QA, local PDF serving/highlighting or production promotion.
The user approved prioritizing a credible internal demonstration by2026-09-29: teacher reports
first, then dual-school UI/copy and optional coordinate highlighting under later bounded Specs.
No new admissions coverage, source downloads, highlighting or M13 work is released here.
DISPLAY-01's bounded local API/UI is accepted. Real winter-trial
schools/editions remain a later teaching-team selection.

The user configured heartbeat gpt6-agent for this existing design chat; each wakeup must re-read
GitHub, avoid overlapping work and release only one Ready task. Previous overnight authorization
was bounded to 2026-09-28 07:00 JST, not permission to implement all future tasks. Do not claim
direct cross-chat delivery: GitHub remains the shared handoff board. At M15 completion stop its
progression automation; M16 is not automatically released.
Keep #177 closed, 334/391 assets unchanged, assistant reference-only, and M13 paused.
