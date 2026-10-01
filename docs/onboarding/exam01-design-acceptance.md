# EXAM-01 #260 independent acceptance

2026-10-01. Accepted PR #267 at exact head `9e43e6b3ce621357b23446ddc3115d71cf50bf69`; merge `c89363589e18ac9f3206af8e6b7d088de72b86b7`.
[Original review, updated in place](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/267#issuecomment-5924849645). R1 and R1.1 are closed.

## Delivered behavior and scope

The existing four-step page now shows the reviewed ISCT Information Engineering B examination schedule
in step two, with the existing official-source dialog and English-proof guide link. The same report dialog
offers an optional, initially unchecked exam topic. Both supported intakes use the reviewed2026 examination
year; no A-route, other-department or GSFS exam coverage is claimed.

Supplied personal details no longer force comparison before report-topic choice. Exam-only preview/copy
uses loaded base data. Personal report content is explicitly compared when required; a503 response leaves
exam-only output usable. Closing an in-flight personal comparison with X/Esc releases the dialog state;
request generations prevent late success/failure/finally from affecting a reopened window. Browser abort
does not imply cancellation of server processing; already-sent requests remain counted.

## Independent evidence and practical limits

- Initial exact-head review: seven focused Python checks and ten Node checks; existing391 KB source map,
  exact Fact quotations/scope/pages, both intake years, five nonmatching target cases, and saved response
  reproduction passed. All substantive presentation fields match the design-reviewed field map.
- Twelve protected asset hashes matched. The M9 policy changed only implementation_sha256, independently
  recomputed as `f0906681edf8bf657008a882888f62915ee1866a7734a97c773ae3bc748874b2`.
  AST differences in bound app.py were confined to startup and optional base-requirements adaptation;
  all17 offline gate checks passed. Retrieval/generation/qualification functions and frozen baselines unchanged.
- R1 review: fifteen Python and ten Node checks, saved-real-response desktop/mobile topic selection,
  failure recovery, successful personal report, reopening/reuse and school-switch invalidation passed.
- Final R1.1 review: fifteen focused Python checks, JavaScript syntax and patch whitespace passed.
  Four desktop/mobile X/Esc saved-response cases passed, plus four cases that deliberately ignore transport
  abort so old503/200 callbacks actually resolve. Reopening exam-only export sends no extra comparison;
  explicit personal retry sends one request and its successful result is reusable.
- Final head [Quality CI](https://github.com/yasu-isct/J-Grad-Admission-RAG/actions/runs/36818514245)
  succeeded; no unresolved review threads. Merge checked the expected head and unchanged base.

[Implementation evidence and screenshots](exam01-implementation-evidence.md) distinguish the developer's
one actual391 TestClient session from saved-response browser replay. Design used direct read-only KB checks
and intercepted browser requests, not a new real product session or online-model evaluation. Unchanged
source,gate and Node evidence was reused rather than repeatedly rerunning full experiments.
Local independent artifacts are in `outputs/design-followups-review/outputs/audit267/`, `audit267-r1/`
and `audit267-r11/`; the final directory also contains the `ignore-abort/` callback checks.

## Final cumulative resource ledger and handoff

Development: real product sessions1/1, base/applicantPOST4/4. Design: sessions0/1, POST0/4.
GSFS report, real Q&A, paid calls, PDF/model downloads, parser reruns, KB/index builds all0.
R1/R1.1 fixes used saved responses only; remaining review allowance is not authorization for another task.
Live8005/8004/8003 and other previews were not switched or stopped; merging does not update them automatically.
334 frozen and391 product assets, reference_only boundary and rollback versions are preserved.

This is deliberately a fixed-source compatibility slice. Repeated CS constants in configuration/Python/JS
remain a recorded limitation, not a generic multi-school exam framework claim. Before new school/year
coverage, consolidate reviewed data ownership rather than copy another school-specific branch.

#258 graduation/submission reminders, #259 advanced-tools cleanup and #260 exams are all accepted/merged.
No new implementation is Ready. M17 Main stops here; the next design activity is demonstration preparation.
QA #233/#236, GSFS ordinary-student expansion, M13 and MinerU remain paused. M17 as a whole is not
automatically closed, and this acceptance does not authorize new coverage or an architecture replacement.
