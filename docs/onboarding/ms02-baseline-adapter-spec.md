# MS-02: Add an isolated legacy parser adapter for the GSFS pilot

## Status, owner and dependencies

Completed as #197 / merged PR #198 with design-main acceptance and exact-head Quality passing.
This file preserves the accepted implementation Spec. The user assigns a separate development
agent; design main provides architectural review. No agent is dispatched by this Spec.
Scope should fit within two focused development days. #177 remains the only MinerU A/B Issue.

Read [source-set contract](gsfs-source-set-contract-v0.1.md),
[parser pilot v0.1](parser-pilot-contract-v0.1.md), [source lock](utokyo-gsfs-complex-2027.sources.json)
and [development lessons](../development-lessons.md). Do not paste the full project history.

## Background and user-visible goal

The existing extractor returns useful page records but no common, versioned source/run envelope.
Its downstream KB builder injects ISCT-specific entities and scope assumptions. The GSFS pilot
needs an isolated comparison output before any school onboarding or parser replacement.

A reviewer must be able to inspect extracted material and know exactly which original PDF/page
and parser configuration produced it. This is a development/review capability; no new Demo target
or admissions answer is promised by this task.

## Scope

1. Add a small typed experimental input/output model and legacy adapter implementing pilot v0.1.
   Recommended placement: a new `parsing/` package; final filenames are an implementation choice.
2. Validate source SHA/page count and page selections before extraction. Preserve all returned
   legacy page payloads/diagnostics exactly in coarse page blocks; report unsupported precision.
3. Record deterministic run identity, actual installed dependency versions and output digest.
   Keep local path/timing outside public identity and deterministic content bytes.
4. Provide one explicit offline invocation (module/script or documented callable) that reads a
   source-lock entry and writes to a specified new ignored output location. No implicit downloads,
   workspace provisioning, source-directory scans, overwrites or runtime activation.
5. Provide focused tests and the bounded real-PDF evidence below, with a short adapter README.

## Non-goals and design constraints

- No MinerU/model install, candidate parser run, rule engine, new-school KB, embedding/index build,
  service/API/UI feature, source migration, cleanup or cloud/paid calls.
- Do not refactor legacy extractor/chunker/builder heuristics or add school-name branches.
- Leave `extract_pdf`, `ExtractedPage`, `SourcePage`, existing build entry points and v1 serialized
  formats compatible. Import the extractor; do not route GSFS through the legacy KB builder.
- Native bbox/heading graph/table cells/OCR may remain explicitly unsupported. A coarse page block
  is acceptable and must not be advertised as a clause locator.
- Physical pages are structured metadata. Do not parse `## Page` headings to recover identity.
- Full-document and subset runs have distinct context identities. Same bytes under different
  local paths must not change deterministic output identity.
- Detect unavailable/hash-mismatched sources, invalid requests and existing conflicting outputs;
  stop with bounded errors rather than creating another workspace or silently repairing artifacts.

## Existing assets and impact budget

Inputs: the four locked GSFS PDFs (22 + 45 + 1 + 15 = 83 pages, 12,006,807 bytes), plus the existing
ISCT PDF SHA `57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735` if needed for focused
page comparison. Locations are supplied explicitly; GSFS originals are already in the source lock's
ignored directory. Do not redownload them merely because a sandbox cannot read them.

Protected read-only assets: 334-vector frozen baseline (KB `b24f85ec...`, vectors `3aca31a6...`) and
391-vector product (KB `7fa46e49...`, vectors `56508cad...`). Do not load models or call their builders.

Authorized task impact: bounded CPU PDF extraction, synthetic fixture generation and small ignored
normalized reports only. Parse each full GSFS source once as a direct reference and once through
the adapter (at most 166 page extractions initially). Use synthetic runs for repeated determinism
checks; one focused retry after a diagnosed code fix is sufficient. Stop and report if one source
takes over 10 minutes or planned report output exceeds 100 MiB; no auto-escalation to GPU/OCR.
These are operational ceilings, not promises about runtime. No permanent production KB is built.

## Acceptance

- [ ] The same exact source/request produces deterministic canonical content and locators; changing
  source bytes, page-selection context or relevant config changes identity or fails validation.
- [ ] Wrong hash/count, empty/duplicate/out-of-range pages, missing/unreadable files and conflicting
  output paths fail explicitly before unsafe work; no partial output appears as complete.
- [ ] All 83 real source pages are represented with original physical numbers and exact source
  identity; returned legacy payload/diagnostics equal direct extraction under the same selection.
- [ ] GSFS department physical page 28 remains 28 even though its printed label is 26. Unknown
  printed labels/bbox/heading graph stay unknown. Empty/scanned pages have honest diagnostics.
- [ ] Marker-free or misleading synthetic text does not change structured physical-page identity.
- [ ] Adapter execution never calls the KB builder, entity/scope inference, embedding provider,
  index builder or network. No ISCT entities appear as added adapter metadata for a foreign source.
- [ ] Legacy extractor unit behavior passes unchanged. If any existing production path must change,
  stop and return to design review rather than broadening this Issue.
- [ ] Real source/run/version/digest/count/timing evidence is attached to the PR, with the 15-page
  sample's output limitations recorded. Missing real PDFs are an acceptance gap, not a passing skip.
- [ ] Only experimental text/metadata outputs are produced. Record no production asset mutation,
  no model download, no runtime activation and no claim of improved admissions-rule correctness.

## Required verification and review evidence

Run new focused adapter tests plus `tests/test_extractor.py` and `tests/test_document_identity.py`.
Use synthetic malformed/blank/page-marker cases for input and locator semantics. Real comparisons
check direct versus wrapped results, not newly invented expected output. Report actual package
versions and source hashes. Inspect selected normalized output against real page images for the
department p.28, checklist p.40 and additional table p.1; preserve baseline failures as findings.

Do not run tests that consume `real_document_kb`/`real_document_kb_bytes` fixtures merely for this
adapter: those fixtures rebuild a KB. A full semantic/model/browser suite is unnecessary because
no runtime route changes. Repository CI still runs its normal required checks; report its actual
evidence limits. Production assets must not be written by local acceptance.

PR review checks source/page lineage, honest coarse capabilities, school independence, deterministic
identity, bounded asset impact and unchanged legacy behavior in addition to test success. The
design main may request a focused correction; no widening to a general parser rewrite.

## Failure, rollback and next gate

On missing evidence, identity mismatch, schema incompatibility, resource overrun or unexpected
legacy behavior, retain experimental status and report the concrete reason. Revert only the new
adapter/model/tool code; existing assets and production routing need no migration or rebuilding.

After acceptance, design main checks #177's version/resource/gold readiness before releasing it.
That preparation is recorded in the [M14 pilot plan](mineru-4.0.7-pilot-plan.md).
Full legacy builder-profile isolation remains mandatory before any new-school KB build, but is
not bundled into this adapter-only task. No dependent implementation starts in parallel.
