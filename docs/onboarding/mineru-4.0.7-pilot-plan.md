# M14 / PARSE-01: bounded MinerU 4.0.7 comparison

Design owner: #191. Execution Issue: [#177](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/177).
Milestone: [M14 - Multi-school Foundations and Parser Pilot](https://github.com/yasu-isct/J-Grad-Admission-RAG/milestone/14).
Status: approved execution specification after this document merges; no candidate has run yet.
The user assigns the development agent and may reuse the current M14 development chat.

## Goal, dependencies and non-goals

Determine whether fixed MinerU output improves the selected GSFS sources enough to justify a
new-school adapter. Finish with `adopt`, `hybrid`, `fallback`, or `reject`, exact evidence and an
onboarding/parser-contract handoff. This decision is bounded to these sources, tiers and resources;
it does not establish quality for other schools or authorize production replacement.

MS-01 #195 / PR #196 and MS-02 #197 / PR #198 are accepted. Reuse their four locked PDFs and four
canonical baseline reports; do not regenerate the 166-page direct/adapter comparison. The baseline
report identities are recorded in PR #198 and local `outputs/parser-pilot/ms02/evidence-summary.json`.
Missing/incompatible reports are an evidence gap, never permission for a new workspace build.

No production KB/Fact/rule/index generation, app/API/UI changes, dependency edits to the production
environment, official-PDF redownload, VLM/GPU setup, cloud calls, paid APIs, document upload or M13
activity belongs here. Do not turn a parser weakness into another school-specific extraction rule.
No new umbrella or duplicate parser Issue is required. Timebox implementation/evaluation to two
focused development days; if larger, record progress and return to design for a bounded split.

## Verified release and resources

The [resource lock](mineru-4.0.7-pilot-lock.json) contains exact software/model/gold identities.
Official references were checked on 2026-09-27:

- [Release 4.0.7](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.0.7-released), published
  2026-09-23; tag commit `175f031cbcded6b527ddb2045ccec460ffecfa26`.
- [Pinned package dependencies](https://github.com/opendatalab/MinerU/blob/175f031cbcded6b527ddb2045ccec460ffecfa26/pyproject.toml)
  require `openai<3`; this repository requires `openai>=3.17,<4`. Use a separate Python 3.12
  environment, never install MinerU into the working project's `.venv` or edit its dependency set.
- [Pinned tier guide](https://github.com/opendatalab/MinerU/blob/175f031cbcded6b527ddb2045ccec460ffecfa26/docs/en/usage/tiers.md):
  Flash native text needs no inference weights; Basic uses small models and supports ONNX CPU.
  Standard/Advanced need additional VLM resources and are explicitly untested in this pilot.
- [Pinned model repository](https://huggingface.co/opendatalab/MinerU-4_models_onnx/tree/358310b4f64b95f9fefc372ad899356e4111f376):
  858,220,651 bytes for all repository files reported by the model API. The lock lists the 13
  required model/config files with their published SHA-256 values and OCR dictionary identity.
- [MinerU license](https://github.com/opendatalab/MinerU/blob/175f031cbcded6b527ddb2045ccec460ffecfa26/LICENSE.md)
  is Apache 2.0 with additional commercial-threshold and online-service attribution terms.
  The [ONNX model card](https://huggingface.co/opendatalab/MinerU-4_models_onnx/blob/358310b4f64b95f9fefc372ad899356e4111f376/README.md)
  retains upstream model licenses. All five upstream repository/revision card metadata records in
  the lock declare Apache 2.0. Retain downloaded notices; this local comparison makes no model
  redistribution or future public-service licensing determination.

Observed device: Windows 11 build 26200; Ryzen 9 8940HX (16 cores / 32 logical processors), about
31.2 GiB usable RAM (16.6 GiB free at inspection), RTX 5060 Laptop 8151 MiB VRAM, driver 610.88,
about 393 GiB free on D:. Existing Python 3.12.14 / Torch 2.13.0 is CPU-only (`cuda_available=False`).
This is a capacity observation, not proof of MinerU runtime performance. CPU ONNX is the selected
configuration; do not spend the task installing CUDA, replacing Torch or enabling a VLM.

## Isolation, acquisition and reproducibility

Use one explicitly named ignored pilot root, for example `outputs/parser-pilot/mineru-4.0.7/`,
with separate environment, config/model cache, reports and logs beneath it. Reuse compatible exact
assets if already present; never scan/copy unrelated model caches. Preserve the production `.venv`,
source PDFs, 334-vector baseline and 391-vector runtime. Record before/after protected identities.

1. Resolve `mineru==4.0.7` in the isolated environment. Capture the resolver report, all installed
   distributions and artifact hashes into a complete run lock **before parsing**. Require `pip check`
   (or equivalent) success. Pin the actual DocVortex/ONNX Runtime versions, not only MinerU's ranges.
   Package installation permission is within the authorized local pilot; no global upgrades.
2. Prepare the fixed ONNX snapshot with an explicit Hugging Face `revision` and local destination.
   MinerU 4.0.7's convenience downloader does not expose a revision argument; do not use its floating
   default as the lock. Verify all 13 paths, bytes and SHA-256 values against this lock, plus the
   packaged OCR dictionary hash. Then use official local readiness verification; never fabricate a
   completion marker. Network/model availability errors remain explicit, with no silent mirror/revision switch.
3. Set dedicated `MINERU_HOME`, `MINERU_CONFIG`, `model.base_dir`, `model.source=local`,
   `model.small_backend=onnx`, `MINERU_TABLE_DEVICE=cpu`. Keep `model.vlm.server_url` empty and both
   `llm_aided.features.title_leveling` / `cross_page_table_cell_merge` false. Supply no API keys.
   Use a child-process environment without inherited remote-service/LLM overrides; do not print secrets.
4. Use the stateless local SDK, not the document library, WebUI, API server or background service.
   Enable offline dependency/cache settings after acquisition; record that the parse child makes no
   network requests. No document-library telemetry service should be started. `DO_NOT_TRACK` alone
   is not evidence that an upstream component obeys it; verify the actual stateless path/network behavior.
5. The experimental result records exact source hash, package/model/config/run identity, full physical
   page context, actual tier/mode/provider, raw result digest, timings and observed resource use.
   Machine-local paths/timestamps remain outside deterministic content identity.

Download limit: 3 GiB total new model/package transfer; pilot disk limit: 8 GiB; result/log limit:
512 MiB. The fixed model snapshot is about 0.80 GiB before package/runtime overhead. If resolver
downloads exceed the ceiling or source installation needs an unexpected build toolchain, stop and
report rather than widening dependencies. Permission is already established; these stops are resource
or reproducibility decisions, not requests to reauthorize the same downloads.

## Candidate matrix and bounded runs

| Candidate | Explicit configuration | Input context |
| --- | --- | --- |
| Legacy reference | Accepted MS-02 outputs: pdfplumber 0.11.10 / PyMuPDF 1.28.0 | Reuse all four existing full-document results |
| MinerU Flash | `tier=flash`, `ocr_mode=txt`; no inference model | Original complete PDFs, all 83 pages |
| MinerU Basic | `tier=basic`, `ocr_mode=txt`, ONNX CPU; fixed small-model snapshot | Same complete originals, all 83 pages |

Use [local SDK](https://github.com/opendatalab/MinerU/blob/175f031cbcded6b527ddb2045ccec460ffecfa26/docs/en/usage/sdk_api.md)
`parse(..., tier=..., ocr_mode="txt")` with full-document context. Do not use `mineru parse`'s default
first-ten-page document-library workflow. The SDK / `mineru-kit parse` full-document behavior is
documented in the [quick start](https://github.com/opendatalab/MinerU/blob/175f031cbcded6b527ddb2045ccec460ffecfa26/docs/en/quick_start/index.md).

Start each tier with the complete 1-page additional table. If successful, retain that result and
process the other three PDFs once. This smoke input counts toward the 83-page run, not another pass.
One repeat of that 1-page PDF per successful tier tests repeatability (maximum 168 candidate page
extractions for two full runs plus repeats). Record raw and normalized digest differences; native
timestamps/unstable identifiers may be isolated, but semantic text/order/table/page differences may
not be hidden by normalization. One narrowly diagnosed rerun needs a recorded reason and stays in
the total time/resource ceiling; do not repeatedly tune against a failing sample until it passes.

Run one document at a time; target eight CPU threads. Supervise child processes: kill the child tree
at 10 minutes per Flash PDF or 30 minutes per Basic PDF, 2 hours total candidate parse wall time,
12 GiB process-tree RSS, or less than 4 GiB available system RAM. Record actual peaks and incomplete
outputs as failed runs. Check before each phase and monitor during execution; checking elapsed time
only after an unbounded call returns is insufficient. Do not increase limits or enable GPU/VLM automatically.

## Structured evidence adapter boundary

The [pinned output contract](https://github.com/opendatalab/MinerU/blob/175f031cbcded6b527ddb2045ccec460ffecfa26/docs/en/reference/output_files.md)
defines `docvortex.middle` / `schema_version=2.0`, original zero-based `page_idx`, producer metadata
and actual tier/mode. Retain the raw `ParseResult` JSON (and necessary local assets for image-based
review) before deriving a repository-owned experimental comparison view. Verify `is_full_document`
and original page coverage; convert `page_idx + 1` exactly once. Do not infer pages from Markdown,
output array position or a renumbered sample. Unknown/unexpected schemas fail explicitly.

MS-02's v0.1 Python models intentionally allow only a coarse `legacy_page` block and no model
revision/bbox. Do not force native MinerU blocks into those literals or loosen old loaders. Add a
separate versioned experimental comparison view or sidecar, retaining v0.1 unchanged. It must bind
source/run/page/block IDs, text/type/order, raw block pointers, optional validated bbox/geometry and
available table/heading relations. No claims beyond the raw evidence: an HTML table can establish
some cell ownership, not automatically a verified cross-page join; a graph image alone is not a
machine-readable branch graph. No public KB/API schema change is authorized by this view.

Validate coordinate convention with page geometry before claiming highlight support; otherwise
report bbox unknown. Native index/locator IDs are qualified by source and run. The pilot produces
no Facts, so report physical-page completeness at parsed-page/block level; do not report fictitious
Fact-page metrics. Final Fact/Citation integration remains a later task.

## Frozen gold and scoring

[Gold v1](mineru-4.0.7-pilot-gold-v1.json) contains 41 review units / 33 critical, covering the previously
fixed 15 physical pages. It was reviewed against source text and page images before any MinerU output
was inspected. The locked hash is in the resource lock. This is a finite acceptance set, not complete
rule coverage, exhaustive transcription, pixel-perfect bbox gold or an OCR benchmark.

For each candidate and each unit, record pass/fail, exact output block/locator, and a short reason.
Pass requires every stated qualifier, negation and relationship in the unit to survive with correct
source/page/context; no fractional credit. Required structure that the parser cannot express is fail,
not removed from the denominator. A failed/unavailable run is separately marked not-run/failed and
cannot receive a passing quality percentage. Automate hashes/page/locator checks; semantic review
uses the PDF and output, not growing keyword lists or an LLM grading call.

Parsing retains the source's special/doctoral/research content and its distinguishing context.
Negative scope labels test that those contexts remain identifiable; the parser must not silently
delete every negative page or decide admissions applicability. Mixed common/conditional pages are
not globally allowed or excluded. Score text versus table/structure groups separately and show all
failures, duplication/loss observations, resource costs and capability limitations.

Minimum broad acceptance: exact page identity/coverage, all 33 critical units, at least 39/41 units
overall, at least 90% of table/structure units, no new critical duplication or invented content, and
resource/reproducibility compliance. A gain must recover at least two known baseline failures,
including checklist non-submission notice D13 and upper checklist D14;
do not amend gold after seeing candidate results. Baseline is scored
with the same denominators; existing weaknesses are not treated as expected-correct content.

- `adopt`: one candidate meets the broad gate and documented improvement; name exact tier/config.
- `hybrid`: a **reviewed explicit page-to-adapter map** meets the same gate as a combined result;
  preserve per-page provenance and reroute only already evaluated outputs, with no production change.
- `fallback`: a candidate reliably recovers identified failure classes/pages but the broad gate is
  not met. Name the limited supported subset and remaining blockers; this does not declare GSFS
  ready for authoritative answers when legacy output still loses critical clauses.
- `reject`: no compliant useful gain, or operational/reproducibility failure prevents a defensible
  candidate. Report Standard/Advanced and scanned-source OCR as untested, not disproven.

## Deliverables, tests, failure and rollback

Deliver one PR referencing #177: isolated acquisition/run instructions and exact execution lock;
experimental comparison view/validation; 3-column legacy/Flash/Basic per-unit scorecard; resource
and repeatability report; source/locator examples; baseline and candidate failures; and an ADR with
one of the four decisions. Include the accepted normalized handoff and unresolved capabilities so
the following onboarding stage can proceed without treating parser output as reviewed rules.

Focused synthetic tests cover wrong source/page mapping, zero-based conversion, unexpected schema,
missing/duplicate pages, dishonest complete flags, output conflicts, resource timeout/cancellation,
unsupported bbox and run identity. Keep MS-02 tests passing unchanged. Mocked units prove plumbing;
the real four-PDF reports and manual scorecard establish pilot evidence. No full KB/model/browser
regression build is required locally; normal CI remains required. Do not upload PDFs/model weights.

Failure leaves outputs experimental and records the gate that failed. Revert only new pilot code or
configuration; remove nothing automatically and mutate no existing runtime pointers. Design main
reviews before merge and marks M14 complete only after the decision and handoff are accepted.
Until then, the sole released development task is #177; future KB/rule/UI tasks remain unissued.
