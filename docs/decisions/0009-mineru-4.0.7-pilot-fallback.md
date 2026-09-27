# ADR 0009: Reject the MinerU 4.0.7 pilot execution

- Status: Accepted as failed-experiment / reject closeout in PR #200; no parser adoption authorization
- Date: 2026-09-27
- Issue: #177
- Decision: reject (supersedes the earlier fallback proposal)

## Context and decision

The main-linked PARSE-01 Spec permits rejection for operational or reproducibility
failure. A retrospective audit found 388 attempted candidate page-passes across
three generations, exceeding the shared 168-page cap. The previous report counted
only generation one and mixed it with generation-three provenance.

Reject this pilot as a basis for adoption, hybrid routing **or fallback authorization**.
Freeze all real candidate entry points; retain historical artifacts and their hashes.
Do not rerun to repair exhausted-budget evidence or relax the locked gold.

Flash's observational score is 33/41 overall, 28/33 critical and 13/20 table/structure,
below the locked gates. D13–D16 checklist recovery is a real observed benefit, but
does not override the failed execution gate. C10 and C13 both fail for unproven
cross-page table ownership. Basic remains unscored: supervisor PIPE starvation may
have contributed to its timeout, so CPU/MinerU performance cannot be blamed conclusively.

## Consequences

No production parser selection, page map, dependency, runtime pointer, KB, vector,
fact, rule, API or UI is changed. MS02 is not loosened. The evidence is not GSFS
answer readiness and does not authorize the next onboarding stage automatically.

Provider values were not measured per session; short-run RSS, cumulative network
transfer, complete network denial and historical protected pre/post state have
evidence gaps. A separately authorized future experiment may investigate these,
but this pilot is closed without additional downloads or candidate parsing.
Scanned OCR, bbox accuracy, Standard/Advanced, VLM and CUDA remain unvalidated.

See the [report](../onboarding/mineru-4.0.7-pilot-report.md),
[audit](../onboarding/mineru-4.0.7-pilot-audit.json) and
[scorecard](../onboarding/mineru-4.0.7-pilot-scorecard.json).
The existing filename is retained to preserve links; it no longer recommends fallback.
