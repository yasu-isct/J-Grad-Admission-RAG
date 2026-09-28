# M15 reviewed materials preview

Accepted2026-09-28. Implementation PR #223, head `67e572757d7b055122799bdf7d95aea6d38cb912`,
merge `3da2964e45046ee736936dee1751425458b6a29c`.
[Independent acceptance](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/223#issuecomment-5869795291).

## What users can do

Open `/app/reference` on the locally configured service and select a real supported capability:

- Science Tokyo: open the existing `/app` applicant-check workflow, with its unchanged coverage.
- University of Tokyo / GSFS / Complexity Science and Engineering: browse reviewed official
  quotations and physical/printed pages for English score-sheet submission, checklist form
  submission, and the employment-related work/study plan. This is the fixed2027 master's ordinary
  general selection A / April2027 intake, a historical reference rather than an open application window.

Browsing requires no profile or report. The optional “生成参考报告” button uses two employment
conditions (yes/no/unknown), then offers explicit copy with citations and limitations. Users are
not restricted to teachers or students. Changed selection/conditions invalidate old results;
late responses cannot refill them. No profile/report persistence or account is introduced.

## Local setup boundary

The existing demo launcher adds `--reference-workspace-config ABSOLUTE_PATH`; use the
[example](../onboarding/reference-workspace-config.example.json) with original asset locations.
The checked product runtime is `outputs/m10-09-deepseek-live/runtime-v1`; the demo `--workspace`
argument uses its parent. Do not assume the older `outputs/demo/...` directory is the391 product.
Restricted execution may require the tool's approved execution context, not filesystem ACL changes.
No service is left running by acceptance. Normal launch remains reuse-only, no build/rebuild flags.

## Evidence and limits

Independent179 focused tests passed with3 local Windows symlink skips and exact-head CI success.
The real final-head loopback browser session read original assets, exposed both capabilities,
browsed3 topics/8 records/23 fragments, and sent exactly3 report POSTs from explicit clicks.
All three inner reports and Markdown matched the accepted RPT-01 output byte for byte.
Desktop/mobile screenshots and real clipboard readback passed;22 source/runtime/retained-output
files retained their hashes, sizes and mtimes. The service stopped cleanly.

Real ISCT evidence covers its app/catalog/base-requirements; the harness's metadata-only provider
forbids model/embedding calls, so retrieval and natural-language generation were not rerun.
The earlier391 fixed-ranking diagnostic remains disclosed, not hidden by changing assets/tests.
The delayed-evidence-loading P2 was reproduced synthetically, fixed and independently retested.

This is not full GSFS eligibility, dates or materials coverage, a production-approved GSFS KB,
a GSFS search/QA index, an annual automatic update pipeline or a public deployment. PDF highlighting
and further schools remain unimplemented. Preserve334 frozen/391 product assets and reference_only.

## Milestone exit and resources

M15's bounded chain is complete: EVID-01 -> BUILD-01 -> IMPORT-01 -> MAT-01 -> RPT-01 -> DISPLAY-01.
All six implementation Issues are accepted. No successor implementation is Ready. Stop M15
progression monitoring; M16 or optional highlighting needs a separate bounded Spec and release.
#191 remains the long-lived governance entry; M13 paused, #177 closed.

DISPLAY-01 validation budget, including the recorded user supplement, is fully spent:3/3 starts,
7/7 covered POSTs. Old RPT-01 CLI3/3, source design audit1/1, IMPORT-01 4/4 and MAT-01 CLI3/3 stay
closed. Do not rerun acceptance scripts under a new chat to reset these limits. Retained developer
evidence is in `outputs/display-01/real-run-2/`; independent evidence is in `outputs/review223-real/`.
