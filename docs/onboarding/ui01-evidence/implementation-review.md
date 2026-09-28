# UI-01 implementation review for #225 / PR #227

This evidence branch is based on final implementation PR head `a9c4938dc4af591d41862a768500093b9a1890bb`. It adds only review artifacts and leaves that PR head unchanged. The browser session used its source-identical parent `561a4a65f0ca1b2d977d90cbb9685c3420f05670`; the final commit changes only two CI test expectations. The independent reviewer has the reserved startup for literal final-head browser verification. The approved layout reference is [unified-workspace-v1](../../ui-prototypes/README.md).

## Visual comparison

The implementation keeps the approved single selection card, requirements list, official-source dialog, optional report/profile area, formatted report dialog, and mobile card flow. The real ISCT list has 11 reviewed items for the chosen target, rather than the three prototype examples. GSFS has the three fixed material topics and its actual historical coverage text. Real source text replaces the prototype's sample summaries.

| Scenario | Real screenshot | Approved reference |
| --- | --- | --- |
| ISCT desktop requirements | [view](isct-desktop.png) | [prototype](../../ui-prototypes/unified-workspace-v1-desktop-isct.png) |
| ISCT desktop report | [view](isct-report-desktop.png) | [prototype](../../ui-prototypes/unified-workspace-v1-report-preview.png) |
| GSFS desktop requirements | [view](gsfs-desktop.png) | [prototype](../../ui-prototypes/unified-workspace-v1-desktop-utokyo.png) |
| GSFS official evidence | [view](gsfs-evidence-desktop.png) | source-dialog interaction in approved HTML |
| GSFS mobile requirements | [view](gsfs-mobile.png) | [prototype](../../ui-prototypes/unified-workspace-v1-mobile-utokyo.png) |
| GSFS mobile report | [view](gsfs-report-mobile.png) | responsive form of approved report preview |

The 390 px mobile page passed `document.documentElement.scrollWidth <= innerWidth`. The mobile report keeps a fixed dialog header and scrollable content. The opened profile in the GSFS mobile capture reflects a prior report interaction, not a default required step.

## Browser and data evidence

The final real session used Edge with code head `561a4a65f0ca1b2d977d90cbb9685c3420f05670`. It started in 0.5 s, lasted 14.125 s, and stopped its owned service. Maximum measured process RSS was 2.096 GiB; available physical memory after the browser cases was 16.406 GiB.

- `/app` initially listed two schools and retained multiple ISCT organizations/programs/intakes. Selection and browsing sent no report POST. Switching to GSFS kept `/app`, disabled QA, cleared the old report, and sent no ISCT fallback query.
- ISCT 2027 April base requirements: 200, 11 displayed reviewed items. The no-profile export copied the same Japanese official quotation shown in the source dialog. A supplied credential and missing official English score report produced a 200 applicant comparison and its statement appeared in the copied report. Switching to 2026 September cleared the personal fields and old report before a second base requirements POST and no-profile export.
- GSFS evidence GET returned 3 topics, 8 records, and 23 fragments. The source dialog showed a quotation from its first reviewed fragment. Unknown/unknown, yes/yes, and no/unknown each triggered one explicit report POST and returned 200. Their canonical report payloads and raw Markdown matched the retained accepted `three-reports.jsonl` artifacts exactly. The copied report contained the raw Markdown and verified original quotation; the preview retained condition status and unknown limitations.
- The old detailed ISCT tool still served at `/app/advanced`; `/app/reference` returned a 307 redirect to `/app`. One offline, pinned-cache BGE-M3 `/v1/corpus/query` smoke returned 200 with semantic hits; no model download or index build ran.

No report POST occurred before an explicit click. The browser's current-session network log recorded exactly 2 base-requirements POSTs, 1 comparison POST, and 3 GSFS report POSTs. The ISCT presentation exports used no new backend report contract.

### Raw response hashes

These files remain in the ignored local `outputs/ui01-real` evidence directory; they contain real reviewed content and were not copied into this branch.

| Artifact | SHA-256 |
| --- | --- |
| ISCT 2027 base response | `098ad23a57542437e477c08e8745184147545e730f18142f0b4bf428ba45f8f0` |
| ISCT comparison response | `45087625e3882866ff15055e3cff0766f4e9f41aa3b34610b5c3abe4e9bc0c02` |
| GSFS unknown/unknown response | `1db26d222a30deeac1c71b4c790ad87f7508692463de450ebea494354ca576b7` |
| GSFS yes/yes response | `1b759b3a8bf9cfaebf70c772578970c5d0dfa9a19b3bcf7d928b809c676fbc19` |
| GSFS no/unknown response | `79a2a71836428e449f723ce7f5a3a5ad5d29f54c30cfc04aab8d40e3c2464351` |

The 25 explicitly referenced protected runtime, source, report, and frozen baseline files had identical SHA-256, byte size, and mtime before and after. The check did not recursively scan or change them.

## Test and resource ledger

Before real service use, three Node adapter tests, 59 focused Python/API/browser tests, Ruff check and format, and whitespace checks passed. Synthetic tests cover a second capability slice, invalid citation/target responses, profile distinctions, request mapping, and browser state isolation/failure behavior. The first [Quality run](https://github.com/yasu-isct/J-Grad-Admission-RAG/actions/runs/36461768537) found two stale assertions for the old page/startup sequence. Both were updated without changing executable source. Final-head [Quality run 36463327414](https://github.com/yasu-isct/J-Grad-Admission-RAG/actions/runs/36463327414) is the required CI gate.

| Developer attempt | Head | Service starts | Explicit exports | Base/comparison/detail POSTs | Search | Outcome |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Browser script 1 | `c08c3e8` | 1 | 1 | 1 | 0 | Script selector failed after ISCT no-profile copy; no product error |
| Browser script 2 | `c08c3e8` | 1 | 1 | 1 | 0 | Script missed a nested profile disclosure; assets unchanged |
| Final executable-source run | `561a4a6` | 1 | 6 | 3 | 1 | All browser/data/copy/cache-only search cases passed; assets unchanged; service stopped |
| **Developer cumulative** | | **3/3** | **8/12** | **5/24** | **1/1** | Reviewer reserve untouched |

Reviewer reserve: 1 service startup, 8 explicit report activations, 16 base/comparison/detail POSTs, and 1 local search smoke. No developer service starts or searches remain. The M15 and earlier experiment budgets remain closed.

Known limit: the prior 391 ranking diagnostic has not been changed or hidden. GSFS still covers only the accepted fixed historical material slice; its search/QA remain unavailable. The literal final PR hash differs from the successful developer browser hash only because of test assertions. The independent design Agent must verify the final implementation PR head with its reserved browser session before acceptance or merge.
