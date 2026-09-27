# MinerU 4.0.7 isolated parser pilot: rejected execution

Issue: #177. Date: 2026-09-27. Decision: **reject**, pending design-main review.
This closes an isolated comparison as an operational failure; it does not authorize
adoption, hybrid routing, a fallback, or GSFS answer readiness.

## Authority and scope

The authority is the main-linked [execution Spec](mineru-4.0.7-pilot-plan.md),
[resource lock](mineru-4.0.7-pilot-lock.json), and unchanged
[gold v1](mineru-4.0.7-pilot-gold-v1.json).
Four fixed GSFS PDFs contain 83 physical pages; existing MS02 output supplies the
baseline without a new baseline extraction during this takeover. The locked gold
contains 41 atomic units, 33 critical units, on 15 selected pages. No school/source
expansion, production parser integration, or dependency-manifest change is proposed.

## Cumulative execution audit — blocking failure

The takeover found three retained generations, not one. Every attempted complete PDF
counts against the shared candidate page budget, including repeats and timed-out PDFs.

| Generation | Runs | Attempted page-passes | Recorded worker seconds |
| --- | ---: | ---: | ---: |
| runs | 8 | 152 | 1870.734 |
| runs-v2 | 5 | 84 | 51.093 |
| runs-v3 | 8 | 152 | 1892.078 |
| **Total** | **21** | **388** | **3813.905** |

The 168-page cap was exceeded by 220 page-passes. Resetting a per-generation ledger
does not reset the Spec budget. The earlier report incorrectly counted only the first
152 pages and mixed first-generation timings/digests with the third-generation lock.
It is superseded by this report. These are all retained supervision records, not proof
that unrecorded execution never occurred; the budget violation is already conclusive.

No real parsing or downloads were performed during this takeover. The runner's
`freeze` and `run` and the direct worker entry now fail before output creation,
model loading or parsing. They must not be reopened to repair this pilot's evidence.
Any future experiment needs a separately approved Spec and budget.

The committed [retrospective audit](mineru-4.0.7-pilot-audit.json) contains all 21
run inventories, individual output hashes/sizes, original execution-lock digests,
and the complete parsed v3 execution lock. Raw PDFs, models, environments and large
run outputs remain ignored local evidence; their availability to a clean checkout
is limited to this hash manifest and the embedded lock, not their full contents.

## Environment and evidence binding

The v3 lock records Python 3.12.14, MinerU 4.0.7, Flash/native text and Basic/txt
with requested ONNX/CPU, eight CPU threads, local model configuration and disabled
LLM features. It records all 13 required model files at revision
`358310b4f64b95f9fefc372ad899356e4111f376`, source hashes/page counts, MS02 report
hashes, OCR dictionary, installed distributions, resolver artifact URLs/hashes,
readiness and successful `pip check`. See the embedded lock for exact values.

Original v3 execution-lock file SHA-256:
`6165ad4a179f6a37c6f34b875b1caa1c987e5ec0aa7ce7ccbc49ebef30191cba`.
Its evidence digest is
`bd073e28c46591ab0cecc8458dfc8ae31594519374e6d1df262dd6261b694fbe`.
The original ignored file is not claimed to be committed byte-for-byte: its parsed
payload is embedded in the audit JSON, whose serialization has a different hash.
The old tracked `outputs/parser-pilot/mineru-4.0.7/execution-lock.json` belongs
to generation one and must not be used to bind the v3 scorecard.

The scorecard's Flash bindings refer exclusively to v3; legacy bindings refer to
the reused MS02 reports. Comparison-view identities include source/raw/runtime/config/
environment/lock digests, model revision and repetition. Physical page is raw
`page_idx + 1`, once; complete ordered page coverage is required. Bboxes remain
explicitly unknown rather than asserting an unvalidated coordinate conversion.
Post-run adapter, supervisor and closure fixes do not retroactively validate the
historical code hashes in the execution lock.

## Third-generation observations (not a compliant rerun)

| Tier / source | Attempted pages | Result | Seconds | Sampled peak tree RSS bytes |
| --- | ---: | --- | ---: | ---: |
| basic / complex-guide-2027-revised run-1 | 45 | timeout | 1803.219 | 5168082944 |
| basic / complex-master-a-additional run-1 | 1 | completed | 7.266 | 730423296 |
| basic / gsfs-master-2027 run-1 | 22 | completed | 31.656 | 3128938496 |
| flash / complex-guide-2027-revised run-1 | 45 | completed | 22.843 | 486010880 |
| flash / complex-master-a-additional run-1 | 1 | completed | 5.969 | unsampled |
| flash / complex-master-a-additional run-2 | 1 | completed | 5.875 | unsampled |
| flash / gsfs-master-2027 run-1 | 22 | completed | 8.594 | 385875968 |
| flash / gsfs-overseas-intake-a-20260305 run-1 | 15 | completed | 6.656 | 281444352 |

Basic is incomplete and receives no aggregate quality score. Both generation one
and three timed out on the 45-page guide; the remaining Basic source and repeat
were not completed. The historical supervisor waited for process exit before
draining stdout/stderr PIPEs. A verbose child can block on a full pipe, so a
supervisor-induced stall cannot be excluded. These timeouts do **not** establish
unacceptable MinerU/CPU parsing performance. Concurrent pipe draining is now covered
by a synthetic child-process regression; there is deliberately no real-parser rerun.

The v3 additional-material Flash repeat has identical raw JSON and marked Markdown:
raw SHA-256 `0ad2a4a54502b2ce13518a12f1de2f9dfcf345d5409a5c2c82734df0f3410282`;
Markdown SHA-256 `4e79da8352f5c94977c15510d92fc3a8291a69214affed6432787c2d4f433454`.
Comparison-view hashes differ intentionally because repetition participates in run identity:
run 1 `fcf472e2a42117232c8d9369ab7b8ec4803a6b8688390a5bf35e92f5880c516d`;
run 2 `89270a9a79239cd20243174e05ca58214b2acd54da0b26010745e81df48bd935`.
This is narrow output repeatability, not complete execution reproducibility.

## Resource and isolation limitations

- Recorded worker wall time sums to 3813.905 seconds versus a 7200-second cap.
  This excludes acquisition, manual scoring and unrecorded overhead.
- Largest sampled RSS is 5,187,416,064 bytes versus 12 GiB; recorded free-RAM
  guards did not fire. v2/v3 short runs with zero RSS were not sampled before exit:
  scanning the pilot directory after spawning could miss them. Full memory-limit
  compliance is therefore unproven, not zero memory usage.
- At audit, pilot disk footprint was 1,979,893,697 bytes
  versus 8 GiB; the 21 retained run directories total 54,935,451
  bytes versus the 512 MiB report cap. These are point-in-time observations, not
  a complete historical high-water mark for all acquisition/report files.
- Previously recorded model plus pip-cache footprint was 1,120,130,486 bytes.
  Cache occupancy is not cumulative transfer: the 3 GiB download limit is unverified.
- Historical `actual_provider` fields contain configured expectations derived from
  provider availability, not per-session observations. Some Basic stderr entries
  report CPU table sessions, but comprehensive provider attestation is absent.
  Flash's no-ONNX-session assertion is likewise not measured.
- Offline flags and Python `socket.connect/create_connection` hooks were configured.
  Zero recorded hook attempts do not prove OS-wide network denial; alternative
  native/subprocess paths and interrupted workers are not fully covered.
- No production KB/index build or protected-model load was performed during this
  takeover. This PR changes no production KB, index, runtime pointer, dependencies,
  API or UI. The historical report's registry declarations are insufficient proof
  of measured pre/post protected-index hashes or unchanged environments throughout
  earlier execution. That gap is explicitly unresolved; no rebuild is used to fill it.

## Manual comparison, observational only

The [scorecard](mineru-4.0.7-pilot-scorecard.json) retains all 41 units, exact
candidate-specific run/page/block bindings and atomic pass/fail reasons. No gold
change, fractional credit, source-specific correction or LLM grading was introduced.
The revision applies the same conservative structural standard to C10 and C13:
surviving text/repeated headers do not prove explicit cross-page table ownership.
C13 is consequently fail for both candidates, without changing its gold requirement.

| Candidate | Total | Critical | Table + structure | Gate |
| --- | ---: | ---: | ---: | --- |
| Legacy MS02 | 30/41 | 26/33 | 13/20 | fail |
| Flash | 33/41 | 28/33 | 13/20 | fail |
| Basic | not scored | not scored | not scored | incomplete |

Broad adoption requires 39/41 overall, 33/33 critical, at least 90% table/structure,
D13/D14 recovery and compliant reproducibility/resources. Flash misses eight units,
five critical and seven table/structure units, as well as the execution gate.

A real bounded benefit remains visible: complex-guide physical p40 recovers the
non-submission notice D13, upper checklist D14, certificate conditions D15 and
once-only lower checklist D16. Additional-material p1 retains native spanning-cell
ownership (A01); D02 laboratory column structure also improves.
Counterexamples remain C10/C13 cross-page ownership, D01 two-column reading order,
D03–D05 p27 schedule relationships, and F01–F02 flowchart edges. This is not a
globally superior parser or proof that the legacy output is authoritative.

## Decision and handoff

**Reject this pilot for adoption, hybrid and fallback authorization.** Preserve the
observed checklist gains as research evidence only. Do not produce a production
page-to-adapter map, assert GSFS readiness, or automatically advance onboarding.
Basic performance attribution, provider/network/memory attestation and protected
before/after state remain unresolved. Scanned OCR, bbox accuracy, Standard/Advanced,
VLM, CUDA and cloud parsing were not validated.

The scope is a failed isolated experiment and decision report, which the Spec permits
to close without a successful parser. [ADR 0009](../decisions/0009-mineru-4.0.7-pilot-fallback.md)
supersedes its earlier fallback proposal. PR #200 is submitted to the design-main
Agent for review, not merged by this implementation agent.

## Takeover verification

- Focused synthetic/contract suite: `tests/test_mineru_pilot.py` and
  `tests/test_legacy_parser_adapter.py`: **55 passed**. This includes the verbose
  child PIPE regression, closed worker/runner entry points, duplicate block IDs,
  score arithmetic, embedded lock digest, gold hash and v3 artifact bindings.
- Ruff lint and format check: all **238 tracked Python files** pass.
- `git diff --check`: pass. No full production/model-backed test suite was rerun
  locally; historical full-suite observations are not used as acceptance evidence.
- Independent design-review Agent rehashed all **130 inventoried files**, finding
  no hash/size mismatch, and approved submission as a failed experiment/reject report.
  This is a design review outcome, not a claim of GitHub platform approval or merge.
