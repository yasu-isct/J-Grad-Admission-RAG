# RPT-01 implementation and review evidence

Issue [#217](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/217). Base main `0bbf3c2183f197c1f4872964731e8fb7f2f81797`; implementation branch `codex/rpt-01-reviewed-material-report`.

## Checkpoint 1: reviewed evidence gate

The additive `material_slice_report.py` validates exact-byte plan/policy/seed pins, complete nested plan sections, approved topics/records/relations and the MAT-01 policy's full context bindings. The bytes-based gate reads exactly five pinned candidate files and three pinned PDF byte arrays. It validates candidate/build/lineage/source identities and hashes, canonical KBs, raw failed quality and unknown-scope state, all approved Fact text/page/fragment links, separate scope/section/stage reviews and relation endpoints. The filesystem reader rejects missing/extra candidate files and links/reparse ancestors; PDF hash and page count use the same captured bytes, without extraction or rendering. Existing IMPORT-01 commands and asset writes are untouched.

Pure/synthetic verification at checkpoint 1: one-page, two-Fact candidate/PDF positive case; changed KB/PDF bytes, missing Fact, extra file, changed lineage, plan pin, scope page, binding, stage, table header and topic effect negatives. The existing source/policy/legacy tests also run without real asset tests. At this checkpoint the focused suite is **450 passed, 8 skipped** (including later report/CLI synthetic tests), Ruff check and format pass. The first checkpoint did **not** call the real report CLI: **RPT-01 0/3**, developer **0/2**, design **0/1**. IMPORT-01 remains **4/4**, MAT-01 preview **3/3**.

## Checkpoint 2: report and CLI

The new report assembler maps the shared MAT-01 condition status and reviewed policy effect to four report dispositions. It returns no evidence or topics for uncovered target/profile conflicts. A loader recomputes from external trusted plan/policy/request/candidate/PDF bytes to reject forged status, digest or quotation. Markdown separates Chinese review prose from Japanese Fact fragments, labels physical and printed pages and table-cell roles, keeps E07 as enrollment-stage context, and escapes raw HTML/Markdown controls. The local `python -m` CLI preflights every request before asset I/O, audits a matched batch once and buffers all output before stdout.

The exact report command for **each** of the two developer attempts was:

```powershell
.\.venv\Scripts\python.exe -m jgrad_admission_rag.reasoning.material_slice_report_cli --plan docs/onboarding/material-slice-report-plan-v1.json --trust docs/onboarding/material-slice-report-trust-v1.json --policy docs/onboarding/material-condition-policy-v1.json --policy-trust docs/onboarding/material-condition-trust-v1.json --seed docs/onboarding/gsfs-material-evidence-seed-v1.json --candidate-root outputs/reviewed-source-candidates/f1721e7c231140957a884b4bf6c35527c25ef053990736295be7f0f9afb68ff2 --pdf-dir outputs/source-documents/utokyo-gsfs/2027 --request tests/fixtures/material_condition_employed_and_retaining.json --request tests/fixtures/material_condition_not_employed_unknown_intention.json --request tests/fixtures/material_condition_employment_unknown.json
```

An ignored local `outputs/material-slice-report/evidence_runner.py` ran that command as a subprocess with a strict 60-second timeout. It fingerprinted the five candidate files and three PDFs before and after each attempt. The first attempt at `2026-09-28T07:30:25.206967Z` returned code 2 with zero stdout in **0.810187 s** because the new reviewer converted a lineage relation using its Python field name `from_id` instead of JSON alias `from`. This was an implementation defect, not an asset mismatch. It counts as real call **1/3**. A read-only, candidate-only diagnostic after failure identified the alias mismatch and confirmed 8 records/23 Facts; it read no PDF, ran no report CLI or old importer. The original failure summary is retained as `outputs/material-slice-report/audit-summary-first-failure.json` (SHA-256 `c63a748a7a91242381f34244e94d71aeb3f3e7729acba61b39340299036beb7`). The relation fix has a targeted synthetic regression test.

The second identical batched command at `2026-09-28T07:36:39.590877Z` succeeded in **0.673310 s**. Its three canonical JSONL envelopes total **137,963 bytes**, SHA-256 `ee27b3be0669fe05576542bc5c9b123ff91e4732884f888f00b4cf52613fa956`, retained at the ignored `outputs/material-slice-report/three-reports.jsonl`. Individual lines (including LF) are **45,924 / 46,012 / 46,027 bytes**, with SHA-256 values `15f625c674d093d8da5eb3c99b0072e062100564a774dbd5aadd8b801aec1e17`, `52fc73e9b519af712ab21c0d148feafe9b753d0a75e286333e47d41d9346e061`, and `40502ef3c80d3e65e268397c5fddc11f212991a806b0931ad010b180a5053071`. Each is below 512 KiB; the batch is below 2 MiB. The successful before/after fingerprint ledger is `outputs/material-slice-report/audit-summary.json` (SHA-256 `929570288080082b8fd3db7c8a9417face55c691628b701ea3af1d44887b6bd1`). Both attempts together used **1.483497 s** of the 3-minute cumulative wall-clock budget; no timeout occurred. Developer calls **2/2 used**, shared calls **2/3 used**, design **1/1 reserved**. No further developer real report call is authorized.

| Pinned input / retained artifact | SHA-256 |
| --- | --- |
| report plan | `11e3690efec73f8dae81b35ebf63d92055982891147040d20bca165b496c8b4c` |
| condition policy | `3a43af563ebb66840fa804a186779553b451b7474033fbc824f34398ebcf0bb8` |
| employed=true / retain=true request | `dbca460832e9408ebd6084cc0bd8f28e32cd6be899f4d78e40af6e0f535d8e74` |
| employed=false / retain=null request | `9f478214a293ca76f14d67f236bb0d063c3e686376aad38930ec98048b352247` |
| both employment facts null request | `809ef40d766c14b7ab5b7511340b4697cfa0f3a430a771904b6a353f90957d1c` |
| three-report JSONL | `ee27b3be0669fe05576542bc5c9b123ff91e4732884f888f00b4cf52613fa956` |
| first-envelope teacher Markdown sample | `9ba418a6b446d72ff98d534cccdb9e7133997340deeaf13594f0cc3f9e1cbfe8` |

The readable [teacher report sample](material-slice-report-sample.md) is the unedited Markdown field from the first real envelope. It has no raw Fact IDs or local paths. All three reports have 23 qualified Fact citations and three source identities, including full E08 table roles and E07 as enrollment-stage context. In request order, the work-plan dispositions are `submission_required`, `rule_not_applicable` (the unknown retention fact is visible without claiming an exemption), and `needs_information` (both facts listed). English and checklist-form dispositions are `submission_not_required` only for this target and those material items. No extra fourth topic, full-materials claim, eligibility claim or fabricated source quotation is emitted.

| Reviewed record | Source / physical page (printed) | Report role and stage | Exact fragments |
| --- | --- | --- | ---: |
| E01 | common guideline / 6 (6) | English context, application | 2 |
| E02 | program guide / 28 (26) | English basis, application | 2 |
| E03 | additional materials / 1 (none) | English context, application | 2 |
| E04 | program guide / 28 (26) | Checklist context, application | 2 |
| E05 | program guide / 40 (38) | Checklist basis, application | 2 |
| E06 | program guide / 28 (26) | Work-plan basis, application | 3 |
| E07 | program guide / 28 (26) | Work-plan context, enrollment only; not an application duty | 3 |
| E08 | additional materials / 1 (none) | Work-plan basis, application; table group/row/cell retained separately | 7 |

All eight protected candidate/PDF files had identical SHA-256, size and `mtime_ns` before and after both calls. The five candidate hashes are `51b7e0c7aa50ca77d252cd173fd3ff63fa11ffdd5577a919ea077c03e630eafc`, `e1a24a5611f80521ad81935c7f1355b14f30f3d6d72a6ec6c45ee2b7f5c33d73`, `81d6a9581ed02ed215fc575790a194eeed210d91ab60fd4e9f568efa8f883484`, `a7c84f35b39f2e0005dfcf7592f3828228e3fc86541fbcd8204590d5ab45ac72`, and `703412fe4d42366552ee9fed55b1e4d4c073e83d3434391a8b144e9695857775`; the PDF hashes are `6063571d2ea0318d9af038340da0e8568cdabf18b03f788d41be59bf96e16fab`, `3539ac01805f345592ec391c7b5c7ec4c9dbf21cee738f6ac5e3dfb27592e7ae`, and `a7a87219903c333b4fe687a3231a2346a195f7a8d8e7859b3f9e902147070026`. The ignored ledger has the exact paths, sizes and mtimes for independent review. No PDF extraction/OCR/rendering, candidate regeneration, IMPORT-01 command, MAT-01 preview or paid/model call occurred.

The retained JSONL was re-read without a CLI run: all three lines are canonical, contain 23 distinct qualified citations, have quote-text SHA-256 values matching every reported binding, and use HTTPS source URLs. The current renderer reproduces the retained Markdown fields byte-for-byte from the three retained report objects. After the successful real run, the reader was tightened to reject in-read file identity/mtime/size changes and incomplete descriptor identities; this does not alter report assembly or output for unchanged inputs. The real output above therefore documents the successful pre-hardening head, while the design-reserved call must independently reproduce the **final PR head**. The latest targeted synthetic/legacy suite is **454 passed, 10 skipped** (local Windows symlink setup is unavailable); Ruff check/format and diff checks pass. No developer real call remains to rerun the final head.

Limitations: this is a historically fixed, partial three-topic teacher reference, not a complete checklist, eligibility decision or current admissions window. The candidate's raw scope remains `unknown`, its full-KB quality gates remain failed, and the separate reviewed locator is only for this selected target. No API/UI, PDF highlighting, model, parser, index or protected ISCT asset is activated.
