# Parser pilot contract v0.1

Status: implementable experimental contract under MS-01; not a production KB/schema migration.
Inputs and meanings come from the [GSFS source-set contract](gsfs-source-set-contract-v0.1.md).
The first implementation [MS-02](ms02-baseline-adapter-spec.md) is accepted in PR #198. Final block/table contract is
reviewed after [#177](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/177).

## Input and output boundary

`parse(exact_source, parse_request) -> NormalizedDocument`

- Exact source: local read-only PDF path, source ID, expected SHA-256 and physical page count.
  Revalidate bytes/count before parser execution. Local paths are acquisition inputs, never public IDs.
- Parse request: explicit `all` or a nonempty, sorted, unique list of 1-based physical pages. Reject
  duplicates, zero, negatives and out-of-range values. Empty list does not mean all. MS-02 supports
  `all` for the real A/B baseline; subset behavior is covered by synthetic tests.
- Record contract version, adapter ID/code revision, actual parser/dependency versions, model
  revision (explicitly not applicable for the legacy parser), configuration digest and requested
  pages/context. No floating version or implicit model is recorded as a reproducible identity.
- A document contains source binding, total physical page count, processed-page records,
  parser provenance, normalized output digest, coverage/diagnostics and an experimental-only role.
- Every requested page has a record, including blank/scanned/unreadable pages. Missing/error pages
  cannot be counted as successful text extraction. An unrecoverable failure returns a typed error;
  never return a deceptively complete document.

The parse/run identity hashes canonical source SHA, contract version, adapter implementation
revision, dependencies/model, configuration and the effective page selection/context. Use a defined
canonical encoding (sorted-key compact UTF-8 JSON, finite numbers, LF) and SHA-256. Source ID is also
bound in the result. Machine paths, timestamps and durations are observations, excluded from content
identity. Keep an output digest separately so differing results for one run identity are detectable.

## Pages, blocks and honest capability reporting

| Field | Meaning / invariant |
| --- | --- |
| physical_page | Positive page in the original complete PDF, never the offset in a sampled file |
| printed_page_label | String or unknown; do not calculate with a universal offset |
| block_id | Deterministic within the same source/run/page/block order; qualified by run ID |
| block_type | Text, heading, table, image, unknown, or `legacy_page`; never infer reviewed admission scope |
| text / text_format | Exact normalized payload, with explicit plain/Markdown format |
| reading_order | Ordered within page plus known/unknown/coarse quality; no false semantic guarantee |
| source_span / bbox | Optional; unknown stays null with a reason. Known bbox must declare coordinates |
| relationships | Explicit available heading-parent/table-continuation relations; unknown remains unknown |
| capabilities / diagnostics | State page coverage, block granularity, table-cell fidelity, bbox, OCR and missing information |

For future native coordinates, use top-left origin on the displayed rotated/cropped page, normalized
to `[0,1]`, with page dimensions and rotation recorded. Require positive bounded rectangles and
test transformation before claiming support. MS-02 reports bbox unknown and need not implement this.
Tables with native structure can retain cell row/column spans and cross-page relationships later;
Markdown alone does not establish merged-cell fidelity.

The first legacy adapter wraps current `extract_pdf` without changing its heuristics. It preserves
each `ExtractedPage.markdown` byte-for-byte in one **coarse `legacy_page` block**, along with the
original char/table/scanned diagnostics. Physical page comes from `ExtractedPage.page`, never from
Markdown. Its stable locator can use run-qualified `p00028-b00001`; this is a page aggregate, not an
exact clause highlight. Printed labels, native table cells, heading graph and bbox remain unknown
unless separately evidenced. Block reading order within that single aggregate is coarse/unknown.

This limited adapter permits a fair baseline without inventing precision. It does not add Facts,
entities, rules, embeddings or index rows. Richer MinerU output may use finer blocks under the same
document/page envelope; evaluation compares semantic units and capability coverage, not block counts.
The same parser contract does not imply all adapters have identical capabilities.

## Context stability and source preservation

Current `extract_pdf(pages=...)` computes repeated lines using the selected pages. Thus parsing one
page and parsing the complete PDF can produce different text. The page-selection/context is part
of run identity. Do not compare full-document output from one adapter to subset-context output from
another or reuse one as a cache hit for the other. For the first real pilot parse all 83 pages of
the four locked PDFs, then score the fixed evaluation pages below. Never slice/renumber source PDFs.

No adapter may route the new source through `build_document_kb`, `build_entities`, ISCT chunk/scope
policies or Demo provisioning. School-specific policy isolation is a later pre-KB gate. Existing
production entry points retain their path, schemas and behavior. No parser winner is preselected.

## Manual sample plan

The following 15-page evaluation selection is frozen for #177. The later
[M14 pilot plan](mineru-4.0.7-pilot-plan.md) and [41-unit gold](mineru-4.0.7-pilot-gold-v1.json) provide
bounded manual acceptance criteria. An exhaustive block/table transcription or bbox gold dataset
is **not** claimed to exist.

| Source alias | Physical pages | Required gold review |
| --- | --- | --- |
| Common guideline | 2,3,4,5,6 | Intake/eligibility including referenced notes, route tables, cross-page materials and delegated English rules |
| Department guide | 3,4,27,28,29,30,40 | Classify research pages before assigning negative labels; mixed route/degree blocks, printed labels, checklist |
| Additional table | 1 | Row/column ownership, conditional applicant group, merged/empty cells and reference-only footer |
| Intake FAQ | 1,5 | Graph branches plus note references; other-program notes and no eligibility inference |

Each gold unit records exact PDF hash, physical page, optional printed label, manual anchor/span,
expected text or table relation, scope/purpose and reviewer status. Pair related units across pages
and documents. Include negative scope examples even where their text resembles a supported rule.
Fix unit denominators and quality gates before candidate outputs are inspected. Verify whether any
page is actually scanned; otherwise OCR quality is untested, and no synthetic scan is presented as
real scanned-document evidence.

Required pilot reporting: requested/returned page coverage; correct physical-page bindings; critical
clause completeness; table row/column/merged-cell accuracy; reading order; duplicate/lost text;
scope-confusion opportunities; locator/bbox capabilities; time, peak resources, disk use and repeat
stability. Missing critical clauses or incorrect page identity cannot pass because Markdown looks
better. Record weaknesses in the baseline too; MS-02 is not expected to repair its semantics.

#177 must pin real MinerU release/backend/model availability, license, device and maximum resource
budget. Download permission exists, but execution readiness still requires those records and gold.
Do not install anything under MS-02. Stop on resource overrun, missing source, identity mismatch or
unreproducible configuration. Store experimental output only in ignored pilot directories; never
activate it in corpus, replace the 334/391 artifacts or trigger an index rebuild.
