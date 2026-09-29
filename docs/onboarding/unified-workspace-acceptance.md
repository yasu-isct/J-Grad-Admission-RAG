# UI-01 independent final acceptance

Review date 2026-09-29. Accepted implementation head `f1b7b5c7a3cded5749c49de38355364c2732114f`,
merge `fe83493ba1108167dd9de3a1a352714033f01e9b`. Issue #225 / PR #227 / [ADR0015](../decisions/0015-unified-admissions-workspace.md).
This is design-main's independent review, not the developer's earlier evidence renamed.

## Four findings resolved

1. The actual `jgrad-serve` factory now serves unified dependencies/catalog and preserves no-GSFS
   operation. The pinned `service/app.py` and gate configuration remain unchanged.
2. An offline local wheel actually contains `unified-core.mjs` plus the page dependency closure.
   `MANIFEST.in` adds the resource without modifying the frozen pyproject input.
3. Question rendering retains actual scope/zero-hit limits, answer-specific missing information,
   unsupported parts, source links and delivery mode. The original independent browser probe now
   shows every previously omitted field and both official/local source links.
4. Personal report preview and copy share the complete presentation model. The original probe
   confirms next action, per-item limitation, official applicability and self-reported preparation
   in both outputs; state enums are translated without changing official quotations.

Independent tests: **56 passed**, including local Edge browser and offline wheel checks, plus
Node adapter **3/3**. [Exact-head Quality CI](https://github.com/yasu-isct/J-Grad-Admission-RAG/actions/runs/36503353617)
passed; no unresolved review thread. Original findings and resolution share
[one review comment](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/227#issuecomment-5880980500).

## Independent real final-head run

Code path asserted to the design worktree; exact SHA asserted. The script reused existing source
paths and imported the same factory used by formal CLI. A new ephemeral loopback port 60816 was
owned by the reviewer. Metadata provider was lazy; the existing pinned BGE-M3 cache loaded only
for the single explicitly counted query. HF offline settings and no-download config were active.

Six report activations: ISCT April 2027 without personal data, with personal data, September 2026
after clearing the old target/profile/report; GSFS unknown/unknown, yes/yes, no/unknown employment.
Two base requirements POSTs, one comparison POST and three GSFS report POSTs; none automatic.
Each actual personal comparison item's next action and limitation occurs in preview and copy.
Source quote clipboard checks passed, including Windows newline normalization. GSFS evidence
remains 3 topics/8 records/23 fragments; all three canonical reports/Markdown match retained RPT-01
outputs exactly. The advanced page returned 200 and reference alias 307. GSFS QA is disabled with
no fallback request. One local `/v1/corpus/query` returned 200, semantic=true and nonempty hits.

Desktop 1280 px and mobile 390 px screenshots were inspected against the approved prototype, including
report dialogs. No mobile horizontal overflow or browser page error. Real result length differs
from placeholder examples, but the common selector/result/report/profile/evidence structure is kept.

- [Actual GSFS desktop](../assets/m16/gsfs-desktop.png)
- [Actual ISCT desktop](../assets/m16/isct-desktop.png)
- [Actual personal report mobile](../assets/m16/isct-personal-report-mobile.png)
- [Actual GSFS report mobile](../assets/m16/gsfs-report-mobile.png)
- [Approved prototype](../ui-prototypes/README.md)

All 25 explicitly referenced protected files had identical SHA-256, bytes and mtime before/after.
Startup 0.484 s; real session 13.125 s; highest sampled RSS 2,101,403,648 bytes; after-run available
memory 16,182,431,744 bytes. The reviewer service stopped. User preview port 8000 / PID 24728 was not
stopped or replaced. No new model/PDF, parser, paid call, KB/index build, copy/migration or gate edit.

Raw private/local evidence remains in `outputs/review227-final-real/`: journal, per-case responses,
before/after identities and screenshots. Independent synthetic reproductions remain under
`outputs/design-main-worktree/tmp/review227-fixed-probe/`. The developer evidence branch
`codex/ui-01-evidence` records the earlier 561a4a6 run and is historical; its executable-source
identity is not used as final-head proof.

## Final ledger and evidence limits

| Resource | Developer | Independent reviewer | Cumulative |
| --- | --- | --- | --- |
| Real service startup | 3/3 | 1/1 | 4/4 |
| Explicit reference export/report | 8/12 | 6/8 | 14/20 |
| Base/comparison/detail report POST | 5/24 | 3/16 | 8/40 |
| Local semantic query | 1/1 | 1/1 | 2/2 |

All prior failed developer attempts count. Startup/query allowances are exhausted; remaining
report/POST counts authorize no extra startup or new task. Old M15/import/report budgets stay
closed. Browser network journal has 6 GETs / 6 POSTs; extra reviewer API GETs and the one counted
query use Playwright's request context and are recorded separately by script actions/results.

The known 391 ranking diagnostic remains unchanged. A single real query proves routing/cache use,
not renewed retrieval quality characterization. Online model answers were not called; successful,
zero-hit, fallback, partial-unsupported and empty-result display behavior was checked synthetically.
This acceptance does not certify more GSFS admissions coverage or production deployment.
