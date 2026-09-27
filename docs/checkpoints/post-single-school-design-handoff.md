# Post-single-school Design Handoff

Updated 2026-09-27 after merged PR #200 (`1d3b3e8`); original release audit was PR #193.
Design continuation below was recorded after the user's GSFS target/download decision.
Always re-read current GitHub
state before acting; this checkpoint is a compact starting map, not a higher authority than `main`.

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
  [source lock](../onboarding/utokyo-gsfs-complex-2027.md). No new-school runtime is enabled.

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
- no assumption that MinerU 4.x improves real data until #177 produces comparative evidence.

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

#202 does not complete M15. The sole next implementation is
[BUILD-01 #206](../onboarding/build-profile-isolation-spec.md), under
[ADR 0011](../decisions/0011-explicit-build-profiles-and-reviewed-lineage.md): isolate the three
legacy ISCT policy seams and guard a new explicit build entry. Preserve old build API behavior
and canonical ISCT outputs; old wrappers remain legacy-only and are not new-school entry points.
Extractor/chunker heuristics remain in the legacy pipeline. No GSFS KB is built in this task.

The later reviewed import will map eight records / 23 separate fragments into existing per-document
Facts with bound lineage and required-context closure. Its exact wire/publication contract, scoped
material conditions and local presentation remain unreleased. No production Schema change is chosen.
Reuse one M15 chat: baseline/refactor/guard tests, then bounded real parity and PR handoff.
Keep #177 closed, 334/391 assets unchanged, assistant reference-only, and M13 paused.
