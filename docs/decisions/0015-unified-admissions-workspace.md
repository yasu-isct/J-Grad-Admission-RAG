# ADR 0015: One admissions workspace and optional reports for both capabilities

Status: Accepted on design merge, following the user's 2026-09-29 approval of the
[interactive prototype](../ui-prototypes/unified-workspace-v1.html).
Owner: [#191](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/191).
Audited base: `5fb98c413f0c75ed2bb59d4cdbdae8ba7e8b3a59`.

## Problem and product correction

The user originally wanted Science Tokyo and UTokyo in the existing school's dropdown, with
dependent organization/program choices and an optional report button on the same main page.
DISPLAY-01 instead linked two journeys and put only the GSFS report in the new entry. Its technical
acceptance in M15 did not establish product acceptance of that layout. The design-main agent owns
this mismatch; implementation followed the previous Spec. Preserve that historical acceptance.

The user approved the displayed prototype and instructed implementation on2026-09-29. This is an
explicit new M16 decision, not an automatic continuation of M15. This ADR supersedes ADR0014's
separate-entry, legacy-navigation and no-common-presentation decisions. Its evidence validation,
immutable snapshot, optional-report, privacy and protected-asset decisions remain in force.

## Decision

1. `/app` becomes the unified workspace. `/app/reference` remains a compatible alias/redirect
   into it, not a second required workflow. Use the existing service/static stack; no second app.
2. One school dropdown contains actual available schools. Organization/program and admissions
   dimensions come from validated server data. Single choices may auto-select. Science Tokyo
   retains all currently supported targets; UTokyo offers only GSFS Complexity Science and
   Engineering, the fixed2027 master's ordinary general/A/April2027 target. Display CBMS as the
   user-requested alias together with the official name; it never becomes an identity key.
3. Use small presentation adapters for `legacy_applicant` and `reviewed_material_slice`, not
   school-name branches. Keep legacy `DemoTargetRequest` and the GSFS full target as distinct
   typed backend requests. A common selector does not invent a GSFS legacy document ID or merge
   the two knowledge/index registries.
4. Both adapters display concise requirements/evidence in the same results area and expose the
   same optional report action. Keep official source title/pages/quotes accessible in a dialog.
   Show meaningful edition/coverage limits briefly, with details expandable. Hashes, record IDs,
   restart instructions and implementation terminology are excluded from the normal display.
5. A reference report defaults to the currently selected scope's loaded, covered requirements,
   not a transcript of one arbitrary question. Personal information is optional. With current
   personal data, include server-produced applicability/comparison and unknowns. Browsing and
   editing produce no report; generation and copying are explicit actions.
6. A shared visual report does not require a new authoritative report schema or rules engine.
   The legacy main-page report is a deterministic **presentation export** of the exact current
   `DemoBaseRequirementsResponse` plus optional `DemoApplicantComparisonResponse`. Preserve all
   relevant requirements, dates, conditions, warnings, comparison statuses and citations. These
   existing APIs already validate target and reviewed evidence. Do not send client-rendered
   conclusions to a server for certification. Do not present this export as a serialized
   `ApplicantReport` or a new approved artifact. The old `/v1/applicant-reports` and detailed
   applicant report tools remain available and compatible; they are not required to produce
   the broader main-page requirements summary.
7. GSFS generation still calls the accepted byte-bound report POST. Adapt its returned report
   into the same preview layout; preserve canonical report/Markdown bytes and trust pins.
   Distinguish condition non-applicability, missing information and material obligation exactly.
   Neither adapter promotes raw retrieval hits or `reference_only` answers into reviewed rules.
8. No-profile legacy export needs only current base requirements. When personal fields changed,
   explicitly generating can first call the existing comparison endpoint once and await it;
   a current same-input comparison may be reused. Unknown values are not false. If comparison
   fails, report failure explicitly rather than silently exporting a partial personal report.
9. Retain the main-page preparation/comparison functionality and supported ISCT search/QA.
   GSFS QA remains unavailable, with a short explanation at the common question area. Sharing
   the question area's location does not authorize GSFS retrieval or fallback to Science Tokyo.
10. Use separate state generations for target/evidence, profile/comparison, report and question.
    Any relevant change invalidates stale report and clipboard state; profile edits must not
    invalidate an unrelated evidence fetch. A late response, including A→B→A, cannot reappear
    under the wrong context. No profiles in URLs, storage, logs or third-party requests.

## Implementation boundaries

[UI-01 Spec](../onboarding/unified-workspace-spec.md) is the only next implementation. One task,
two checkpoints: data/report mapping, then complete main-page integration and real browser proof.
The approved prototype is the visual/interaction baseline, not a backend fixture or admissions
source. Its sample two-field profile and one Science Tokyo program are not coverage reductions.

Production `service/app.py` is pinned by the grounded-RAG gate. It can remain byte-identical:
existing static content and the additive `reference_app.py` wrapper are enough for this boundary.
Do not rehash release gates to accommodate a UI change. Old APIs, KB schemas, rules, index roles,
source paths and on-disk canonical artifacts remain compatible. Capability advertisement in the
additive catalog must truthfully reflect the newly implemented main-page export; existing legacy
entries must no longer claim that no reference report is available. No capability is advertised
solely because a school name is present.

No new source/model acquisition, parsing, KB/index building, GSFS production promotion, PDF
highlighting/export, paid API, M13 deployment, annual-update automation, or broader coverage.
Protect the334 frozen baseline and391 product runtime. M15's exhausted validation budgets remain
historical; the new Spec has a separately bounded UI integration allowance and ledger.

## Product acceptance and rollback

The reviewer must inspect desktop/mobile real-page screenshots beside the accepted prototype,
and walk the same-page two-school selection→evidence→optional report→copy sequence, with and
without personal data. Passing backend tests alone is insufficient. Material layout/flow changes
return to design/user confirmation; content lengths and accessible responsive refinements do not.

Rollback reverts the UI/adapter changes and restores the old local entry, preserving all APIs,
data and accepted assets. No destructive migration or source cleanup is part of the rollback.
