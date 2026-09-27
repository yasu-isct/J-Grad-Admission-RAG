# Post-single-school Design Handoff

Verified 2026-09-27 against GitHub `main` at merge commit `744d9dd`. Always re-read current GitHub
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
- #177 remains open as the future MinerU 4.x Tokyo University A/B experiment.
- #191 is the durable design authority/workflow entry for the next design-main agent.
- #192 is the documentation-only single-school closeout that produced this checkpoint.
- No open PR existed when #192 began.

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

## Unique next design action

After #192 merges, start #191 in a fresh design-main thread and perform a read-only audit of every
single-school assumption across identity schemas, parser/builder, reviewed configuration, rules,
corpus/index selection, APIs, UI, and tests. Produce the multi-school compatibility ADR before
downloading MinerU, acquiring a new PDF, changing schemas, or implementing Tokyo University support.
