# UX-02 independent design acceptance

2026-09-30: #250 / [PR #252](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/252) accepted.
Reviewed head: `ea4379808ba68251c1d59a1a73ae7b29340262bf`.
Implementation merge: `fa99392860b51bfa92cc4abdd1268f2199a43bd2`.
[Single review record, including resolved findings](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/252#issuecomment-5902718350).

The original two-school four-step page now uses consistent typography, concise user wording,
eight scoped Chinese/Japanese material explanations shared by cards, personal inputs, comparison
and copied reports, and safe paragraph/list answer rendering. Unknown preparation remains distinct
from explicitly missing materials; backend rules and source access remain intact.

## Incremental review

- R1 resolved: presentation metadata requires the registered ISCT school/document or GSFS
  institution/organization/program/snapshot identity. Same-kind/code mismatches retain the input
  name and an unverified explanation status. The validated scope reaches all rendering paths.
- R2 resolved: the old checklist sentence is not rendered verbatim in step four. Unconfigured
  generation uses a generic availability label, preserving actual online/offline/failure state.
- Independent final-head pytest: 11 passed (`test_ui02_browser`, `test_grounded_answer_ui`,
  `test_ux03_ui`); Node: 6 passed. These cover the direct regressions and identity fallback.
- Independent saved-response replay checked ISCT base requirements, input labels, personal
  comparison, reader report/copy and an explicitly synthetic unconfigured provider status.
  Step-four screenshots at 1440/390 had no horizontal overflow or browser script errors.
- Exact-head Quality CI succeeded; no unresolved formal review threads. Incremental changes
  affect only presentation, related tests and evidence; prior 31-asset independent hash evidence
  remains applicable. Saved response digests are unchanged.

Independent replay: `outputs/design-usability/outputs/ux02-design-audit/rereview/journal.json`.
ISCT saved base digest: `d1ac46581a57e9a07ddc1edc6a20be54fddaef1a359c56a9de0622dbf3736236`;
comparison digest: `3744f08dad012f8286c609cb5370807f81c6593f6f7ad8642310d6b7e09e87a1`.
[Implementation evidence and before/after views](ux02-implementation-evidence.md).

## Evidence limits and handoff

This is saved-response presentation acceptance, not a new live-service or online-answer-quality
acceptance. UX-02 developer and design each used 0/1 real service starts, 0/4 base/comparison POSTs,
0/1 GSFS report POSTs; paid calls, downloads and builds are zero. Historical budgets are unchanged.
The first review already independently checked 31 protected assets; no repeated asset build or
index migration occurred. 334/391, PDFs, production schemas and authoritative rules are unchanged.

No new implementation is Ready. Design prepares the existing demonstration and school presentation;
M17 Main waits. QA #233 / Draft #236 and GSFS ordinary-student expansion remain paused, M13 remains
paused, and MinerU #177 remains closed. M17 is not declared fully complete by this UI acceptance.
The existing 8003 user preview stays on rollback commit `29a91ac`; this merge does not upgrade it.
Keep [the rollback tag and procedure](../checkpoints/demo-before-usability-20260930.md).
