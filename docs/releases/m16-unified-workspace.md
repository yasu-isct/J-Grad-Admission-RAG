# M16 unified admissions workspace

## Current presentation after UI-02 correction

The user-requested restoration of the original v1 four-step page is accepted in PR #231 at
head `cd09bd43abbc276c2f5fb1bc2fdae40aa82eb166`, merge `40cd25d84c15d4ccaace610d5158875632dd428c`.
Both schools now use that retained workflow: prominent dates and material cards, personal details
in the main flow, and an action summary after comparison. Optional reports are available in
steps 2 and 4. `/app/advanced` is a compatible entry to the same flow, retaining advanced tools;
`/app/reference` still redirects. [Independent evidence](../onboarding/ui02-final-acceptance.md).
The data, coverage, authority and local-operation boundaries below are unchanged. UI-01's initial
layout is superseded; its technical acceptance remains historical. M16 is complete with no next
implementation released.

## Original UI-01 acceptance and continuing boundaries

Accepted 2026-09-29. [PR #227](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/227), exact
head `f1b7b5c7a3cded5749c49de38355364c2732114f`, merge `fe83493ba1108167dd9de3a1a352714033f01e9b`.
[Independent acceptance](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/227#issuecomment-5880980500)
retains the four resolved findings. [Evidence and ledger](../onboarding/unified-workspace-acceptance.md).

## Delivered user journey

Open `/app` on the configured local service. Choose Science Tokyo or UTokyo in the same school
dropdown, then its supported organization/program, degree, edition/intake and route. Read the
requirements and open their official evidence without generating a report. Optionally add
personal details and use the common report action to preview/copy a cited reference document.
Both capabilities stay on the main page; `/app/reference` redirects to `/app`.

Science Tokyo retains its full currently supported catalog, base requirements, personal
comparison/preparation and reference-only question behavior. Its main-page report is a
presentation export of existing reviewed requirements and optional comparison, not a new
authoritative artifact schema. The original detailed report/search tools remain at `/app/advanced`.

UTokyo remains GSFS Complexity Science and Engineering (display alias CBMS), 2027 master's
ordinary general selection/A/April 2027: English score-sheet submission, checklist form submission,
and employment-related work/study plan only. Sources remain the accepted historical three-document
slice. The common report preview uses the existing byte-bound server report; canonical payloads
and Markdown are unchanged. Personal unknowns stay unknown, and condition non-applicability does
not become a general exemption. Source/title/physical and available printed pages remain visible.

## Boundaries

This is local operation with existing read-only assets; no public deployment, accounts or storage.
GSFS keyword/vector retrieval and natural-language answers are not implemented. Full GSFS
eligibility/material/date coverage, exact PDF-coordinate highlighting, report PDF export and
automatic annual updates are not delivered. Unknown/uncovered content is not an admission decision.
Paid online generation was not used in this acceptance; question presentation was verified with
synthetic responses, and actual semantic routing with one fixed-cache local query.

M13 remains paused, MinerU #177 closed, assistant reference_only, 334 frozen baseline and 391 product
runtime separate and unchanged. M16 is complete; no next implementation is released automatically.

An already-running old server does not reload these changes. The independent acceptance server
was stopped, and the user's existing old preview on port 8000 was deliberately left untouched.
