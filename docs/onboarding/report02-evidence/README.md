# REPORT-02 real-response comparison

This checkpoint uses the saved real HTTP responses from `outputs/ui02-real/final-head-cd09bd4` (UI-02). `replay.json` records each input SHA-256, the previous full-copy hash and opening excerpt, and the new copy hash. The old screenshots were taken in the earlier real-service session. The new screenshots run those same responses through the current four-step browser code; the replay route supplies only target selection metadata and does not run a service, model, search, or index build.

| Case | Previous report | Current desktop | Current mobile | Current copy |
| --- | --- | --- | --- | --- |
| ISCT, no profile | [old desktop](before-isct-no-profile-desktop.png) | [desktop](isct-no-profile-desktop.png) | [mobile](isct-no-profile-mobile.png) | [text](isct-no-profile-after-copy.txt) |
| ISCT, self-reported available and not prepared | Previous copy opening and hash in [replay.json](replay.json) | [desktop](isct-with-profile-desktop.png) | [mobile](isct-with-profile-mobile.png) | [text](isct-with-profile-after-copy.txt) |
| GSFS, employment unknown | [old mobile](before-gsfs-unknown-mobile.png) | [desktop](gsfs-unknown-desktop.png) | [mobile](gsfs-unknown-mobile.png) | [text](gsfs-unknown-after-copy.txt) |
| GSFS, condition applies | Previous copy opening and hash in [replay.json](replay.json) | [desktop](gsfs-required-desktop.png) | [mobile](gsfs-required-mobile.png) | [text](gsfs-required-after-copy.txt) |
| GSFS, condition does not apply | Previous copy opening and hash in [replay.json](replay.json) | [desktop](gsfs-inapplicable-desktop.png) | [mobile](gsfs-inapplicable-mobile.png) | [text](gsfs-inapplicable-after-copy.txt) |

The previous ISCT profile export was 33,346 characters; the corresponding current copy is 1,018 characters. The prior GSFS conditional export was 7,938 characters; its current copy is 429 characters. These counts describe the whole exported text, including target labels. The original report/canonical text and citation checks in `unified-core.mjs` remain unchanged.

## Reuse and differences

| Existing resource | Reuse point | Required change |
| --- | --- | --- |
| Two-school four-step `advanced.html` and report buttons | Same buttons, dialog, target/profile flows in `app.js` | Small theme selector and readable report sections inside the existing dialog |
| `mapLegacyBase`, `mapSliceEvidence`, `legacyReport`, `sliceReport` | Existing target match and evidence/citation validation before display | New `readerReport` projects validated topics into user-facing statuses and copy; legacy/canonical exports stay available internally |
| ISCT applicant comparison and GSFS condition report | Same real HTTP response objects | Distinguish self-reported prepared, explicit not prepared, unfilled, and unknown applicability |
| Existing cancellation, stale-result guard, and clipboard fallback | Same request and dialog lifecycle in `app.js` | Theme changes rebuild locally, clear old copy/fallback, and never POST again |
| 391 runtime and GSFS reviewed config | Read-only identity-only service check | No backend, rule, schema, asset, or provider edits |

## Validation and limits

- `node --test tests/unified_core.test.mjs`: 5 passed. UI-02, reference, unified, and material-condition/report directed pytest group: 101 passed, 2 skipped, 1 obsolete preformatted-report assertion corrected; that test then passed on its own. `ruff --no-cache`, JS syntax checks, and `git diff --check` passed.
- Saved-response browser replay: 5 reports, 10 desktop/mobile screenshots, matching preview copy, no horizontal overflow or browser errors. See [replay-browser-journal.json](replay-browser-journal.json). A synthetic UI-02 browser case also checked theme choice, empty selection, stale copy reset, clipboard fallback, and HTML text safety.
- Real-service budget used: 2 of 2 starts, 2 of 8 explicit report attempts, 3 of 12 base/comparison POSTs, 0 other POSTs, 0 paid calls. Both sessions used independent loopback ports and stopped. The real base and comparison HTTP objects matched saved responses. The browser check stopped on equality with replay copies because the initial replay scope used the sample's Chinese/Japanese title metadata instead of the 391 official English title and Japanese GSFS name. Those replay labels were corrected; no third service start was made. Thus the real-service full copy/screenshots remain unverified, while the saved real-response browser replay passed.
- Read-only pre/post SHA-256 comparison found no changes in 30 protected 334/391, GSFS source/candidate, and policy/plan/trust files. See [asset-check.json](asset-check.json) and [browser-journal.json](browser-journal.json) for the hashes and counted attempts.

Reproduce the no-service projection and screenshots with `docs/onboarding/report02-replay.mjs` and `docs/onboarding/report02-browser-replay.py`; both require the saved UI-02 response directory. `docs/onboarding/report02-real-browser.py` documents the exhausted bounded real-service attempt and will refuse a third start using the recorded journal.
