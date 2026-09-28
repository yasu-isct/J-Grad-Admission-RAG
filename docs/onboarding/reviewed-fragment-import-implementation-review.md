# IMPORT-01 implementation evidence

Issue: [#209](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/209). The candidate is local, isolated, and non-production. Independent design acceptance remains pending.

## Checkpoint 1: strict contract and pure mapping

Base: main `55609e43cfaad702874f6dde0e34026a08c4a831`; branch `codex/import-01-reviewed-fragments`.
At this checkpoint the implementation was uncommitted. The exact EVID-01 seed and review pin, source manifest, target contract, and pinned import config were loaded without any PDF access. Three canonical KBs map the 23 original fragments one-to-one; five reviewed relations retain both endpoints' complete required context. The production quality gate fails on missing official section paths and unknown scope in every KB. No registry, index, model, parser, network, legacy build, or protected asset was touched.

Validation: `121 passed, 1 skipped` across importer, EVID-01, build profile, KB serialization, and embedding-text focused suites; Ruff check passed. Real candidate calls used: **0/4** (developer allowance **0/2**); candidate artifact not yet published.

## Checkpoint 2: real candidate publication and reuse

Candidate root: `outputs/reviewed-source-candidates/f1721e7c231140957a884b4bf6c35527c25ef053990736295be7f0f9afb68ff2`. It contains one `candidate.json`, one `lineage.json`, and three document KBs; no sibling build was created. The five files total 65,030 bytes, below the 8 MiB limit. They are local and ignored by Git.

Both calls used this exact command on base head `55609e43cfaad702874f6dde0e34026a08c4a831` plus the uncommitted #209 implementation (the final implementation head is recorded in the PR):

```powershell
.\.venv\Scripts\python.exe -m jgrad_admission_rag.reviewed_import_cli --profile reviewed-source-v1 --mode publish --bundle docs/onboarding/gsfs-material-evidence-seed-v1.json --manifest docs/onboarding/utokyo-gsfs-complex-2027.sources.json --target-contract docs/onboarding/gsfs-source-set-contract-v0.1.examples.json --import-config docs/onboarding/reviewed-fragment-import-v1.json --trust docs/onboarding/reviewed-fragment-import-trust-v1.json --candidate-root outputs/reviewed-source-candidates --source gsfs-master-2027=outputs/source-documents/utokyo-gsfs/2027/a7a87219903c333b4fe687a3231a2346a195f7a8d8e7859b3f9e902147070026.pdf --source complex-guide-2027-revised=outputs/source-documents/utokyo-gsfs/2027/6063571d2ea0318d9af038340da0e8568cdabf18b03f788d41be59bf96e16fab.pdf --source complex-master-a-additional=outputs/source-documents/utokyo-gsfs/2027/3539ac01805f345592ec391c7b5c7ec4c9dbf21cee738f6ac5e3dfb27592e7ae.pdf
```

| Developer call | Start UTC | End UTC | Result | Wall time |
| --- | --- | --- | --- | --- |
| 1/2 | 2026-09-28 01:17:31.168093 | 01:17:31.198814 | generated | 0.031 s |
| 2/2 | 2026-09-28 01:18:31.223122 | 01:18:31.244467 | reused | 0.021 s |

Each call audited exactly three existing local PDFs (SHA-256 and physical page counts 22, 45, 1). Both calls completed below the 60-second ceiling. Cumulative real wall time was 0.052 s of the 10-minute allowance. **2/4 shared calls are used; 2/4 remain for independent design review.** The process peak RSS was not captured on Windows, so the 1 GiB limit lacks a measured proof for these two calls; the remaining review calls should instrument it. No further developer real call is authorized.

Input exact-byte SHA-256: seed `a5b2bc4e294c52b14c94946886e43928b46fc7f3ff7724ee08a3aa1067aa0b85`; source manifest `0065233d6179e25d1896de3252946fea82dc430c7101d872093948bef42625d7`; target contract `b86e7b61aa43cfc4705234a450fd8993e0c1ac86a6b730ca10d750b6427238e3`; import config `49782ecb7bdb0c6e9fcbff230c7150587dc80ab769a2f86286f50eb2aaedb7b1`. All three PDF hashes match the pinned [source manifest](utokyo-gsfs-complex-2027.sources.json). The import config digest is separately pinned in [trust](reviewed-fragment-import-trust-v1.json).

| File below candidate root | Bytes | SHA-256 |
| --- | ---: | --- |
| `candidate.json` | 4,233 | `51b7e0c7aa50ca77d252cd173fd3ff63fa11ffdd5577a919ea077c03e630eafc` |
| `documents/complex-guide-2027-revised/document_kb.json` | 20,746 | `e1a24a5611f80521ad81935c7f1355b14f30f3d6d72a6ec6c45ee2b7f5c33d73` |
| `documents/complex-master-a-additional/document_kb.json` | 15,760 | `81d6a9581ed02ed215fc575790a194eeed210d91ab60fd4e9f568efa8f883484` |
| `documents/gsfs-master-2027/document_kb.json` | 5,640 | `a7c84f35b39f2e0005dfcf7592f3828228e3fc86541fbcd8204590d5ab45ac72` |
| `lineage.json` | 18,651 | `703412fe4d42366552ee9fed55b1e4d4c073e83d3434391a8b144e9695857775` |

All five byte hashes and their UTC mtime values were unchanged after the reuse call. The first-call mtimes were `01:17:31.1880086` for candidate, common KB and lineage, `01:17:31.1854925` for guide KB, and `01:17:31.1875003` for additional-table KB; the second inspection returned the same values.

## Full document identity and mapping audit

The pinned [identity config](reviewed-fragment-import-v1.json) contains the complete `DocumentIdentity` 1.0 JSON. In all three identities, institution ID/name are `utokyo` / `東京大学`; edition is `2027`; publication and revision dates are `null`, not the HTTP Last-Modified value. The complete document coverage is:

| Document / family | Degree levels | Intake terms | Official title / URL | PDF SHA-256 |
| --- | --- | --- | --- | --- |
| `gsfs-master-2027` / `utokyo-gsfs-master-guidelines` | master | 2026-10, 2027-04, 2027-10 | 令和9（2027）年度 東京大学大学院新領域創成科学研究科 修士課程学生募集要項 / https://www.k.u-tokyo.ac.jp/assets/files/2027guidelines_for_applicants_to_mc.pdf | `a7a87219903c333b4fe687a3231a2346a195f7a8d8e7859b3f9e902147070026` |
| `complex-guide-2027-revised` / `utokyo-gsfs-complex-guide` | doctoral, master | 2026-10, 2027-04, 2027-10 | 東京大学大学院 新領域創成科学研究科 複雑理工学専攻 2027年度 入試案内／志望調査票 / https://www.k.u-tokyo.ac.jp/complex/html/examinee/2027guidebook_rev.pdf | `6063571d2ea0318d9af038340da0e8568cdabf18b03f788d41be59bf96e16fab` |
| `complex-master-a-additional` / `utokyo-gsfs-complex-master-a-additional` | master | 2026-10, 2027-04 | 令和9年度（2027）年度 修士課程入試（入試日程A）出願に関する専攻独自の追加提出物一覧【複雑理工学専攻】 / https://www.k.u-tokyo.ac.jp/assets/files/03CSE_AM_j.pdf | `3539ac01805f345592ec391c7b5c7ec4c9dbf21cee738f6ac5e3dfb27592e7ae` |

The following 23 identifiers were checked against the original fragment text and physical page. The test asserts each KB Fact text equals the corresponding seed fragment character for character; it also checks the page and generated Unit binding. Same words in different fragments retain separate Facts.

| Document ID | Record | Fragment | Physical page | Fact ID |
| --- | --- | --- | ---: | --- |
| complex-guide-2027-revised | E02 | E02-1 | 28 | `fact:reviewed:complex-guide-2027-revised:E02:r1:E02-1` |
| complex-guide-2027-revised | E02 | E02-2 | 28 | `fact:reviewed:complex-guide-2027-revised:E02:r1:E02-2` |
| complex-guide-2027-revised | E04 | E04-1 | 28 | `fact:reviewed:complex-guide-2027-revised:E04:r1:E04-1` |
| complex-guide-2027-revised | E04 | E04-2 | 28 | `fact:reviewed:complex-guide-2027-revised:E04:r1:E04-2` |
| complex-guide-2027-revised | E05 | E05-1 | 40 | `fact:reviewed:complex-guide-2027-revised:E05:r1:E05-1` |
| complex-guide-2027-revised | E05 | E05-2 | 40 | `fact:reviewed:complex-guide-2027-revised:E05:r1:E05-2` |
| complex-guide-2027-revised | E06 | E06-1 | 28 | `fact:reviewed:complex-guide-2027-revised:E06:r1:E06-1` |
| complex-guide-2027-revised | E06 | E06-2 | 28 | `fact:reviewed:complex-guide-2027-revised:E06:r1:E06-2` |
| complex-guide-2027-revised | E06 | E06-3 | 28 | `fact:reviewed:complex-guide-2027-revised:E06:r1:E06-3` |
| complex-guide-2027-revised | E07 | E07-1 | 28 | `fact:reviewed:complex-guide-2027-revised:E07:r1:E07-1` |
| complex-guide-2027-revised | E07 | E07-2 | 28 | `fact:reviewed:complex-guide-2027-revised:E07:r1:E07-2` |
| complex-guide-2027-revised | E07 | E07-3 | 28 | `fact:reviewed:complex-guide-2027-revised:E07:r1:E07-3` |
| complex-master-a-additional | E03 | E03-1 | 1 | `fact:reviewed:complex-master-a-additional:E03:r1:E03-1` |
| complex-master-a-additional | E03 | E03-2 | 1 | `fact:reviewed:complex-master-a-additional:E03:r1:E03-2` |
| complex-master-a-additional | E08 | E08-1 | 1 | `fact:reviewed:complex-master-a-additional:E08:r1:E08-1` |
| complex-master-a-additional | E08 | E08-2 | 1 | `fact:reviewed:complex-master-a-additional:E08:r1:E08-2` |
| complex-master-a-additional | E08 | E08-3 | 1 | `fact:reviewed:complex-master-a-additional:E08:r1:E08-3` |
| complex-master-a-additional | E08 | E08-4 | 1 | `fact:reviewed:complex-master-a-additional:E08:r1:E08-4` |
| complex-master-a-additional | E08 | E08-5 | 1 | `fact:reviewed:complex-master-a-additional:E08:r1:E08-5` |
| complex-master-a-additional | E08 | E08-6 | 1 | `fact:reviewed:complex-master-a-additional:E08:r1:E08-6` |
| complex-master-a-additional | E08 | E08-7 | 1 | `fact:reviewed:complex-master-a-additional:E08:r1:E08-7` |
| gsfs-master-2027 | E01 | E01-1 | 6 | `fact:reviewed:gsfs-master-2027:E01:r1:E01-1` |
| gsfs-master-2027 | E01 | E01-2 | 6 | `fact:reviewed:gsfs-master-2027:E01:r1:E01-2` |

## Production limit and asset effect

The candidate covers reviewed fragments only. Every Fact has `scope_type=unknown` and an empty official section path. Quality gates fail on those two metrics; this is a structurally valid review artifact, not a production KB or an admission/material conclusion. PDF reference resolution was not run; zero counters do not assert absence of references. The API/UI, reference-only assistant, corpus registry, rules, indexes, existing KBs, frozen 334 baseline, product 391 runtime, source PDFs, seed, and pin were not changed. The importer made no MinerU/model/parser-extraction or network call.

## Verification and open review points

Focused verification after the final source edit: `121 passed, 1 skipped` for importer, EVID-01, build-profile, KB serialization, and embedding-text tests. The skip is the Windows symlink negative test because this host cannot create a test symlink; Ubuntu CI can run it. `ruff check --no-cache src tests` and `ruff format --check --no-cache src tests` passed. The whole local offline suite was diagnostic-run with `-x` and stopped at its first failure: `tests/test_real_pdf_regression.py::test_real_pdf_vector_search_matches_independent_numpy_ranking_and_cli` expects hard-coded row order `[172, 390, 322, 336, 309]`, while both the live search and its independent NumPy ranking returned `[172, 390, 347, 322, 336]`. The fixture's 391-vector hash and payload hash assertions passed before that row-order assertion. This code path and gold were not modified for #209. The GitHub Ubuntu CI result remains a separate review gate; no protected fixture or baseline was changed to make the local assertion pass.

Peak RSS for the two developer calls was not instrumented, so the 1 GiB ceiling has no measured local proof. This is an explicit evidence limit for design review. The two remaining real calls belong to the independent design Agent; the developer must not rerun a real candidate to fill this gap.

## Response to PR #211 design changes requested

Design reviewed the initial head `b0aed8cc05eb0a585ad2d2fb3a8a612665197536` and requested two bounded corrections. The existing real candidate and its five bytes/mtime values were not changed. No developer real call was added.

1. `read_context` now requires the raw bundle/manifest/contract/config plus the separately pinned import trust. At the public reading boundary it reloads the pins, recomputes the canonical mapping, validates the complete disk candidate tree including ancestor symlinks/junctions, and compares the supplied lineage exactly with the reviewed lineage bytes. It then uses the verified mapping bytes to read Facts, avoiding a later file replacement shrinking the result. Synthetic negative tests reject an in-memory lineage with removed relations, changed role/page/manual anchor, forged qualified Fact, disk lineage and candidate with self-updated hashes but changed audited relation, missing KB, and a linked parent. The valid E02/E03 read proves bidirectional closure and per-record fragment order. The Windows host skips two symlink-creation tests; GitHub Ubuntu CI can execute them.
2. Removed the optional `pyproject.toml` console entry. The required local entry remains `python -m jgrad_admission_rag.reviewed_import_cli`; neither the frozen implementation fingerprint nor semantic policy/gold/index was changed. The previously failing `test_checked_in_manifest_matches_the_current_implementation_contract` now passes locally.

Post-fix focused/importer/semantic-gate validation: **123 passed, 2 skipped**. Ruff check and format on `src tests` passed. The earlier local whole-suite ISCT 391 hard-coded ranking mismatch remains a separate Windows result; it is not the PR's original CI failure.

Design's first independent real audit used call **3/4**, UTC 2026-09-28 01:54:55.574490–01:54:56.005897, 0.4331884 s supervised wall time and Windows peak working set 89,731,072 bytes. It rechecked the three PDF identities and existing five files without altering them. Total shared calls used: **3/4** (developer 2, design 1); **1/4 remains exclusively for final design acceptance**. The two developer peak RSS values remain unmeasured; the design measurement does not retroactively prove them.
