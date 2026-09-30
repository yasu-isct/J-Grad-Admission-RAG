# PREP-01 independent acceptance

2026-09-30: [#254](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/254) accepted through
[PR #256](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/256).
Reviewed head `358abd6ea0c382dbb0b07ed244c2c8efe8c46a36`; implementation merge
`3afa83c4acfa97f9e2148f284749fdefd985bd57`.
[Single maintained independent review](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/256#issuecomment-5907184038).

## Accepted behavior

- Five existing ISCT material cards explain preparation in Chinese using the reviewed p.10 evidence;
  page, source drawer and optional report reuse the same bounded guidance.
- Five optional English-proof fields reach existing `LanguageTestResult` and the reviewed report
  engine. The new opt-in projection distinguishes reported match, missing proof, unknown input,
  mathematics exemption and unsupported coverage. No new authority rule or index was introduced.
- Detailed English results replace the legacy English card in visible actions, filters and display
  counts. Mathematics has no external-score preparation task; QR=false remains visible under
  action-required; an unspecified test kind is pending confirmation. Priority links focus real cards.
- Old API items/counts/status semantics remain intact and old requests omit the new extension.
  Related English evidence is enriched, so old response JSON is not claimed byte-identical.
  UI counts describe displayed checks; the five material cards are still five materials.

## Independent verification

Initial review at `73310f4`: 21 Python tests passed (19 PREP-01, including 16 real-asset cases,
plus two existing interface cases), eight Node tests, desktop 1440/mobile 390 saved-response replay,
copy parity, source inspection, 12 protected-asset hashes and the 17-check M9 gate.
The original tests used an inaccessible historical temporary asset path; design substituted the
existing product runtime path without copying assets or changing permissions. All 16 skipped cases
then ran. The final PR adds `PREP01_REVIEWED_ASSET_ROOT` for reproducible asset selection.

Final-head incremental review: 14 UI/browser tests and eight Node tests passed. Three cases were
computed from the existing product 391 reviewed data and replayed against the exact frontend:
mathematics, TOEIC QR=false, and unspecified test kind. All four filters, action links, focus,
display counts, five-material separation and report consistency passed. The original independent
QR reproduction changed from zero visible action cards to one. All 12 asset hashes remained equal.
Exact-head Quality CI passed; no unresolved formal review threads.

Backend/rules/report text were unchanged by the final UI repair, so prior source/rule and M9 checks
were reused. The accepted M9 implementation digest is
`189705ee88842578093fb1f181c3120bb0d5ed9faee5010b3a6f5d52cd59f222`; the bound app.py delta only adds
field-specific validation errors, without changing thresholds or evaluation fixtures.

Final verification uses actual reviewed rules plus browser response replay, not a fresh live service
roundtrip or an online-QA quality claim. Developer evidence distinguishes the original two real POSTs
from subsequent replay. No QR authenticity, ETS account state, school receipt or final eligibility
is verified by this feature.

## Cumulative resources and handoff

| Role | Real sessions | Base/comparison POSTs | GSFS report POSTs | Paid calls |
| --- | --- | --- | --- | --- |
| M17 Main | 1/1 | 2/6 | 0 | 0 |
| Design | 0/1 | 0/6 | 0 | 0 |

No downloads, parser reruns, KB/index builds or protected-asset writes. Static replay and direct
read-only rule evaluation are recorded separately; repeated reviews do not reset this ledger.

No new Ready implementation. Design prepares the current product for user acceptance and the school
demonstration. Stage B (graduation/submission reminders and advanced-tool migration/removal) and C
(written-exam information) still need separate release. QA #233/#236, ordinary-student GSFS expansion,
M13 and MinerU remain paused. M17 stays open.

Existing preview 8004 remains at `1a36683` in `outputs/design-usability`, and 8003 remains at `29a91ac`
in `outputs/design-report02`; merging does not update either running preview. Preserve 334/391,
the rollback tag and `reference_only`.
