# MinerU 4.0.7 isolated parser pilot report

Issue: #177. Date: 2026-09-27. Decision: **fallback**. This report covers an isolated
comparison only. It does not enable a parser, change the MS02 contract, or add facts, rules, KB
rows, vectors, APIs, UI, runtime dependencies, or activation pointers.

## Locked execution

The run used Python 3.12.14 in `outputs/parser-pilot/mineru-4.0.7/env`, MinerU 4.0.7,
Flash/native text and Basic/ONNX/CPU with `ocr_mode=txt`, and eight CPU threads. The committed
exact pre-parse execution lock is
`outputs/parser-pilot/mineru-4.0.7/execution-lock.json` (SHA-256
`5a096245ac1bc574398ecfd370a1478644a68efc8a30d2d696009553a0056529`). It contains the
resolver reports, every installed distribution and version, source and baseline report hashes,
and every required model file hash. `pip check` reported no broken requirements.

The model snapshot was fetched from `opendatalab/MinerU-4_models_onnx` at immutable revision
`358310b4f64b95f9fefc372ad899356e4111f376`. All 13 required files matched the locked byte
counts and SHA-256 values, and `mineru-kit models verify --tier basic --small-backend onnx`
reported the repository ready. The dedicated configuration fixes `source: local`, ONNX as the
small backend, CPU table execution, blank VLM server credentials, and both LLM-aided features off.

Acquisition and reproduction, from the repository root:

```powershell
.venv\Scripts\python.exe -m venv outputs\parser-pilot\mineru-4.0.7\env
outputs\parser-pilot\mineru-4.0.7\env\Scripts\python.exe -m pip install `
  --report outputs\parser-pilot\mineru-4.0.7\acquisition\pip-report.json mineru==4.0.7
outputs\parser-pilot\mineru-4.0.7\env\Scripts\python.exe -m pip install `
  --report outputs\parser-pilot\mineru-4.0.7\acquisition\psutil-pip-report.json psutil==7.1.3
# Fetch exactly the repo/revision/files in the resource lock into
# outputs/parser-pilot/mineru-4.0.7/models/MinerU-4_models_onnx, then verify them.
$env:PYTHONPATH = "$PWD\src"
outputs\parser-pilot\mineru-4.0.7\env\Scripts\python.exe `
  tests\run_parse01_pilot.py freeze
outputs\parser-pilot\mineru-4.0.7\env\Scripts\python.exe `
  tests\run_parse01_pilot.py run complex-master-a-additional flash 1
```

`freeze` is fail-closed and refuses replacement. `run` refuses an existing run directory and
output files. The remaining source/tier invocations use the same form. The runner strips secrets,
sets Hugging Face, Transformers and ModelScope offline flags, forces the local model source, and
the worker denies `socket.connect` and `socket.create_connection` before importing MinerU.

## Runs and resource evidence

Flash first parsed the one-page additional-material table, then the other three complete PDFs,
then repeated the one-page document. It completed all 83 locked pages plus the one-page repeat.
Every successful network audit recorded `network_disabled: true` and zero attempts. Every output
claimed `docvortex.middle` 2.0/full-document and passed exact source hash, complete ordered
zero-based page coverage, and physical-page `page_idx + 1` validation.

| Tier / source | Pages | Result | Wall seconds | Peak process-tree RSS | Comparison-view SHA-256 |
| --- | ---: | --- | ---: | ---: | --- |
| Flash / additional run 1 | 1 | pass | 3.093 | 250,028,032 | `ab34792e3b5d52a1eea40006ca086def3e9c5caba08b813f3343352486c45f14` |
| Flash / common master | 22 | pass | 5.687 | 382,967,808 | `6434f5f7992de5a118c8fcac7b2c4358d4db3dd4ccf72a633b4d6f74633b38c5` |
| Flash / complex guide | 45 | pass | 20.407 | 504,979,456 | `535d5af82f262ca9780600e567a400f10f13710f4861000bc97d44496d75e12b` |
| Flash / overseas flowchart | 15 | pass | 3.625 | 277,024,768 | `c4cf1d4d161c4c9c06c818ef2826ba5d33f3519864aca46a36c703c83587d162` |
| Flash / additional run 2 | 1 | pass | 2.844 | 252,022,784 | `ab34792e3b5d52a1eea40006ca086def3e9c5caba08b813f3343352486c45f14` |
| Basic / additional | 1 | pass | 4.422 | 771,047,424 | `9e33d166e952bc40d122a30fb18bc0576b64c01867a88434538b72d3fe44bac2` |
| Basic / common master | 22 | pass | 30.187 | 3,113,000,960 | `624e3186cb513731ede334fb6526836a2a353a8dd147917fd3bbb003893e59a1` |
| Basic / complex guide | 45 | **timeout** | 1,800.469 | 5,187,416,064 | not produced |

The Basic failure report has SHA-256
`70527f74f48d2e11318cb54a7d9169281ed3addbdb5200cc3201469f8ebd70b4`.
At the locked 1,800-second limit, the supervisor terminated the complete process tree and retained
the report. It did not attempt the remaining Basic document or repeat, so Basic is an incomplete
tier and receives no quality score. It is not retried with a relaxed limit.

The two Flash repeats have identical raw JSON, marked Markdown, and comparison-view hashes. Their
wall time differs by 0.249 seconds and peak RSS by 1,994,752 bytes. Total candidate wall time was
1,870.734 seconds. The attempted workload was 152 page-passes, below the 168-page cap. Peak RSS
was 5,187,416,064 bytes, below 12 GiB; the 4 GiB available-memory guard never fired. Initial
available RAM was 17,808,314,368 bytes. Model plus pip-cache acquisition occupied 1,120,130,486
bytes, below 3 GiB. The whole pilot directory occupied 1,943,241,146 bytes, below 8 GiB, and run
reports/logs occupied 18,400,387 bytes, below 512 MiB.

The product environment was not modified. The canonical product KB remained
`7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce`; the frozen/product
identity registry still declares vectors `3aca31a683e2145fa9e24566abd3af40540bba8473b0d6a895e0cf6297f67f58`
and `56508cad1dbf13c5e3258353676608cf4b6a174ac9c879983be9bdc8cd415df7`.
No builder or model for either protected index was loaded. The Git diff contains no knowledge,
index, runtime-pointer, dependency-manifest, API, or UI change.

## Manual comparison

The locked 15 pages / 41 atomic units / 33 critical units were scored without fractional credit.
The complete three-column record, exact page/block locators and per-unit reasons are in
`mineru-4.0.7-pilot-scorecard.json`.

| Candidate | Total | Critical | Table + structure | Broad gate |
| --- | ---: | ---: | ---: | --- |
| Legacy MS02 | 32/41 | 27/33 | 15/20 | fail |
| Flash | 35/41 | 28/33 | 15/20 | fail |
| Basic | not scored | not scored | not scored | fail: incomplete tier |

Flash provides a real, bounded gain. On complex-guide physical p40, block 0 recovers “this
checklist need not be submitted” (D13), blocks 7-8 recover the upper checklist exactly once (D14),
block 9 recovers the graduation-certificate conditions (D15), and blocks 9-10 avoid the legacy
lower-half duplication (D16). Its native HTML also preserves the additional-material table's
`colspan`/`rowspan` ownership and empty right-hand cells at p1 block 4 (A01-A04). It also improves
the p4 three-column laboratory page enough to pass D02.

The gain is not broad. On complex-guide p27, Flash block 4 reverses/scrambles visual year, month
and day tokens, failing ordinary, special-oral and doctoral schedules (D03-D05). On the overseas
flowchart p1, blocks 4-21 retain nodes and loose yes/no labels but no edges, so nationality,
residence, scholarship and final-no outcomes cannot be bound (F01-F02). The p3 two-column
introduction remains interleaved/garbled (D01). There was no invented critical content, but the
candidate misses five critical units, six units overall and five of 20 table/structure units.

## Handoff and unresolved capabilities

The accepted handoff is **evidence for a future reviewed fallback**, not runnable production
configuration: Flash/native text may be considered only for complex-guide physical p40's
checklist-recovery class, with source/page provenance preserved and human review required. There
is no page-to-adapter production map in this change. MS02 remains unchanged and authoritative
on neither the failed legacy pages nor the unreviewed candidate output.

Unresolved capabilities are diagram-edge extraction, reliable visual-table date ordering,
multi-column reading order, scanned-source OCR, reviewed bbox accuracy, and acceptable Basic CPU
latency. Standard/Advanced tiers, VLM, CUDA, cloud parsing, and scanned-source OCR were not tested
and are not disproved. Any future onboarding stage must keep parser output separate from reviewed
admission rules and must not treat this fallback decision as GSFS readiness for authoritative
answers.
