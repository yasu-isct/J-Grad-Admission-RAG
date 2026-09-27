# ADR 0009: Keep MinerU 4.0.7 Flash as a reviewed checklist fallback only

- Status: Proposed pending design-main review
- Date: 2026-09-27
- Issue: #177
- Decision: fallback

## Context

The locked University of Tokyo pilot compared the existing MS02 legacy adapter with MinerU 4.0.7
Flash/native text and Basic/ONNX/CPU over four exact PDFs. Adoption required 33/33 critical,
39/41 overall, 90% table/structure, reproducibility/resource compliance, and recovery of D13 and
D14. A hybrid required a reviewed explicit page map meeting the same gate.

## Decision

Do not adopt MinerU and do not create a production hybrid map. Retain Flash only as experimental
evidence for a future, human-reviewed fallback on complex-guide physical p40 checklist recovery.
It recovered D13-D16 and was byte-identical on the locked repeat sample, but scored 35/41,
28/33 critical, and 15/20 table/structure. The flowchart relations F01-F02 and schedule table
D03-D05 remain critical blockers. Basic is rejected as a candidate for this pilot because the
45-page guide exceeded the locked 1,800-second per-PDF limit, leaving the tier incomplete.

No production parser selection, dependency, runtime pointer, KB, vector, fact, rule, API or UI is
changed. The MS02 contract is not loosened. There is deliberately no production page-to-adapter
map; creating one would require a separate reviewed change.

## Consequences

The next onboarding stage may use the p40 evidence to design a narrowly reviewed fallback while
preserving exact source/page provenance. It must not treat raw parser output as reviewed rules or
claim GSFS answer readiness. Diagram edges, visual-table date order, multi-column order, OCR and
bbox accuracy remain unresolved. Standard/Advanced, VLM, CUDA and scanned-source OCR are untested,
not disproven.

The full execution/resource record is in
`docs/onboarding/mineru-4.0.7-pilot-report.md`; the immutable unit record is in
`docs/onboarding/mineru-4.0.7-pilot-scorecard.json`.
