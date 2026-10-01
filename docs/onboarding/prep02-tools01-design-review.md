# M17 overnight work: independent design review, 2026-10-01

## EXAM-01 design closeout (supersedes historical Blocked contract statements below)

2026-10-01: source review is complete and [the final contract](exam01-written-exam-spec.md) freezes
the optional API response, configuration validation, B-only card/report projection and bounded acceptance.
[Machine-readable source mapping](exam01-reviewed-field-map.json) contains five existing KB Fact records,
one explicitly identified cover-page context, and13 field bindings. All exact text anchors were independently
matched against the unchanged391 KB SHA256. Earlier full-page visual review supplies the table-cell and year context.
No parser/model/product service was run for this design closeout; no implementation was accepted here.
After #264 merges and #191 records Ready, only #260 is released to M17 Main. #258/#259 remain accepted.
The following sections preserve earlier review decisions and budgets; their then-pending #260 contract is now resolved.

## TOOLS-01 incremental re-review: Accepted/merged

2026-10-01: reviewed exact head `b9058ff906f5358986d1e0f7b3ee49e58dc57d08`; merge `5d5e30a5cba655a7355f375811d57896cada93ca`.
[Original review updated in place](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/263#issuecomment-5920735734).
R1 is closed. Delta from1bd4c95 contains only the three-line QA input listener and one real-DOM browser test.
Independent exact-head test passed: initial0, type5, edit6, clear0/1000. JavaScript syntax, diff check and exact-head
Quality CI passed; no unresolved review threads. Previous30 targeted checks, eight before/after browser cases
and12 protected hashes remain applicable to unchanged code. No repeated full experiment or new product service.
PR #263 was marked ready only after design acceptance and merged with expected-head validation; #259 is closed.
Developer/design real service,productPOST,paid,download,parser/index-build counts remain0 for this task.
This is saved/synthetic browser verification, not a new live online-model quality result. User previews unchanged.
Next responsibility: design finalizes #260 optional API/config fields and source validation contract before Ready.
#260 candidate PR #264 remains Draft; no exam implementation is released by this acceptance.
This section supersedes the historical Changes requested result below.

## PREP-02 #258 / PR #262 — Accepted/merged

Reviewed exact head `5dc887846268fbceac8b21db328e381c40d26ab9`; merge `6b59cb3392625c58998ed8d53f48d223dd4db2c8`.
[Independent acceptance](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/262#issuecomment-5920677185).
Graduation dates and submission progress now use the existing reviewed rules in an optional response extension.
Only the date condition is checked, not whole-person eligibility; September special contact remains distinct.
Dispatch does not prove arrival, online completion does not prove school acceptance, and review progress is self-report.
Old response shape/counts remain compatible; English and application preparation share one reviewed report.

Independent verification: 37 actual391 rule tests, nine Node tests, two saved HTTP requests recomputed into identical
complete JSON responses, additional completed-graduation branches, desktop1440/mobile390 browser replay with
actions/focus/filters/source dialog/report topics/copy, and12 protected asset hashes. Exact-head Quality CI passed.
No new live product service or product POST; saved-response replay is not online-model quality verification.
Development cumulative sessions1/1, base/comparisonPOST3/6; design0/1,0/6. GSFS reports,paid,downloads,parser/builds0.

## TOOLS-01 #259 / Draft PR #263 — Changes requested

Reviewed exact head `1bd4c95fe8e39efef220b6ce43787bb637a4c49e`.
[Single review and narrow repair](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/263#issuecomment-5920735734).
After #262 merged, PR base was changed to main without changing head. It remains Draft, not accepted or merged.
Removal of old advanced DOM/initializers passed independent27 UI/browser and3 QA-display checks, plus two schools
at desktop/mobile with before/after replay. ISCT uses PREP-02 real saved responses; GSFS uses synthetic fixtures.
The live QA textarea input counter listener was accidentally removed with legacy events: typing 托业是什么
shows5/1000 before and0/1000 after. Restore that listener and verify typing/edit/clear with a DOM-event browser test.
No real service, paid request or broad retest is needed for this repair. Development/design real service/POSTs0;
per-role allowed budget remains in the Spec and is not reset by review.
The first reproduction attempt used an unavailable generation-status fixture and therefore could not type;
the corrected before/after reproduction used the same configured mock status, with no external model call.

## EXAM-01 #260 / Draft PR #264 — source review decisions, implementation blocked

Candidate head `f98619ee1980006d249cc1c32f16b8eaee0cb6e4`.
[Design source decisions](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/264#issuecomment-5920736505).
Independent read-only visual review of full PDF p.1,p.2,p.52 and actual KB facts confirmed the candidate table.
Fixed source: PDF SHA256 `57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735`,
KB SHA256 `7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce`.

- The examination year is2026 by reviewed cross-page inference within this fixed booklet: p.1 publication/application
  year, p.2 application/exam/intake sequence, and p.52 department dates. Neither p.2 nor p.52 explicitly prints the
  year; do not present this as a verbatim year on p.52. Keep p.1/p.2/p.52 provenance and do not invent a cover Fact.
- Current CS target catalog only exposes B for both supported intakes. Implement only that route when later released;
  A stays in official source, not a new selectable supported target or an extra main/report card.
- p.52 B:2026-08-18 09:30–12:00,150min; groups A calculus/linear algebra/probability-statistics,
  B mathematical logic/automata/formal languages, C data structures/algorithms/programming; one question set from
  each group, three questions. This is the examiner's question setting, not a candidate choice rule.
- Specialist900/English100; written specialist answers in Japanese. English uses the existing external-score rules,
  not a waiver of score-sheet submission. Secondary notes: oral-candidate announcement8/20 around17:00; B oral8/24,
  selected candidates only. No new past-paper link this slice.
- fact:00288 is typedenglish but contains the table; fact:00292 duplicates/mixes rows. Bind each display field to
  precise page/scope/Fact, not fact_type or mixed OCR text. fact:00002/00004 are context only; fact:00289 supports
  the announcement; fact:00287 retains the English submission requirement. Do not alter frozen KB/index.

Candidate PR stays Draft; final optional API/config contract still requires design completion. #260 is not Ready.
This source decision narrows the earlier EXAM-01 A/B display proposal; no new target coverage is authorized.

## Handoff and preserved state

Only next implementation: M17 Main repairs #259 R1; design performs incremental re-review.
Then finalize #260 field/API contract and release it explicitly; no automatic implementation from source notes.
Keep user online8005 atcd4064 and8004/8003/other live worktrees unchanged. No service switch was performed.
334/391,PDF/model assets,rollback tag,reference_only unchanged. QA233/236,GSFS ordinary-student expansion,M13/MinerU paused.
This review performed no paid calls/downloads/parser reruns/KB or index builds and no production-code edits.
