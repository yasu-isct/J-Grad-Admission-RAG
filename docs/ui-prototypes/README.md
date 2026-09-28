# Unified workspace v1 — user-approved interaction reference

The user approved [unified-workspace-v1.html](unified-workspace-v1.html) on2026-09-29 and asked
to implement the displayed design. Open the HTML locally in a browser; it has no external assets,
service calls, model calls or PDF/KB dependency. Inline CSS/JS are for this standalone prototype
only; production must retain existing CSP and use external static assets.

The artifact is authoritative for main-page layout/interaction, not admissions content, identity
metadata or coverage. All report text is marked illustrative, including clipboard output. The
one-program/two-profile-field ISCT sample is not permission to remove existing product features.
UTokyo's question box demonstrates placement; actual GSFS QA remains unavailable. Formal data
labels, supported options, coverage, source quotes/pages and conditions come from reviewed data.

- [Science Tokyo desktop](unified-workspace-v1-desktop-isct.png)
- [UTokyo desktop](unified-workspace-v1-desktop-utokyo.png)
- [UTokyo mobile](unified-workspace-v1-mobile-utokyo.png)
- [Report preview](unified-workspace-v1-report-preview.png)

Original prototype verification used installed Edge/Playwright: same-page selection, explicit
load, no automatic report, both report previews, evidence dialog, optional personal input and
390px layout without horizontal overflow; zero page errors and zero external requests. These
are prototype checks, not real production acceptance evidence.

Implement under [ADR0015](../decisions/0015-unified-admissions-workspace.md) and
[UI-01](../onboarding/unified-workspace-spec.md). Keep an actual-page versus prototype comparison
in the implementation review. Material visual/flow deviations require design/user review.
