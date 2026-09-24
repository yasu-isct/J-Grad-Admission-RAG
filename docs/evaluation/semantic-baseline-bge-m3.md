# BGE-M3 Semantic Baseline

This is the semantic characterization for the frozen 38-query Japanese/Chinese
admission-retrieval benchmark. The first 34 Japanese queries remain the quality-gated cohort; four
Chinese queries characterize cross-language retrieval without weakening the accepted Japanese
thresholds. The model, benchmark, retrieval configuration, and input KB are fixed throughout.

## Provenance

- Model: [BAAI/bge-m3 at the pinned revision](https://huggingface.co/BAAI/bge-m3/tree/5617a9f61b028005a4858fdac845db406aefb181), MIT license.
- Pinned revision: `5617a9f61b028005a4858fdac845db406aefb181`.
- Embedding identity: `sentence-transformers`, `BAAI/bge-m3`, revision above, dimension `1024`.
- Runtime packages: Sentence Transformers `6.0.1`, Transformers `5.16.1`, Hugging Face Hub
  `1.29.0`, PyTorch `2.13.0`, NumPy `2.5.2`.
- Snapshot: 30 files, 4,587,317,404 bytes; canonical file-inventory SHA-256
  `1222b4c0ceebdfabaf7319d7c5ad9e8ae7646d3c89b0c6b48baefcddbb4b9a9a`.
- Principal weight `pytorch_model.bin` SHA-256:
  `b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38`.

The snapshot is acquired once into an external, untracked cache. After acquisition, build and
evaluation set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`; no later model download or network
access is permitted. Windows cache storage may not use deduplicating symlinks, so capacity planning
must allow the full snapshot size. The cache-hosting drive had about 170.0 GiB free before
acquisition and 165.7 GiB after; the approximately 4.27 GiB difference matches the snapshot.

## Fixed Inputs

The current KB was rebuilt from the hash-verified local PDF into an isolated, untracked baseline
area. The older 382-unit `outputs/kb/isct_master` artifact was not used.

| Binding | SHA-256 / value |
| --- | --- |
| Source PDF | `57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735` |
| Current KB, schema `0.6`, 334 Facts/Units | `b24f85ecc0400a7d6e6e0fac94e078b2515a0c378b5bc35383efcd05977dedf6` |
| Frozen benchmark, canonical LF bytes | `47be02726a2091e352bc8d0a9037be97d429eb7c8b260c63e9130ee1b733de20` |
| Payloads | `6d49c6d579216846749672a4fdd7520eb0ab1405cda9c976372ed413554214aa` |
| Semantic vectors | `3aca31a683e2145fa9e24566abd3af40540bba8473b0d6a895e0cf6297f67f58` |
| Index manifest | `ff2dc4f94abafb85cc60f9af9da94c52daa3d305b25e3843a8010dedd7e6523b` |

The semantic index is a new absent-directory build with 334 normalized vectors. It binds the model
identity above and uses `hybrid`, `bm25-v1`, `rrf-v1`, `RRF_K=60`, `top_k=10`, and
`candidate_k=50`. Every request has empty metadata filters and empty scope preferences.

## Reproduction

Use an external cache root and newly absent output directories. The placeholder below intentionally
does not name a machine-local path.

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'

jgrad-build-index <current-kb.json> `
  --output <new-semantic-index> `
  --provider sentence-transformers `
  --model BAAI/bge-m3 `
  --revision 5617a9f61b028005a4858fdac845db406aefb181 `
  --dimension 1024 `
  --cache-folder <external-cache-root> `
  --batch-size 8

jgrad-evaluate-retrieval <new-semantic-index> `
  --current-kb <current-kb.json> `
  --benchmark tests\fixtures\retrieval_queries_v1.json `
  --retrieval-mode hybrid `
  --top-k 10 `
  --candidate-k 50 `
  --provider sentence-transformers `
  --model BAAI/bge-m3 `
  --revision 5617a9f61b028005a4858fdac845db406aefb181 `
  --dimension 1024 `
  --cache-folder <external-cache-root> `
  --batch-size 8
```

The evaluator rejects model-download authorization. Run the command three times without rebuilding;
the canonical stdout bytes must remain identical.

## Three-Run Result

The report is stored as canonical LF JSON on Windows and in the committed Git blob. Both have
SHA-256 `1ba6fb5d0b74b35d13bb5bbf503849b5e1545be7c45d3aa5c8300b884b77623b`.
Each reports `semantic_evaluation=true`, `quality_eligible=true`, and `gate_status=not_evaluated`.

| Queries | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR | Zero hits |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Overall, 38 | 0.3691 | 0.6810 | 0.7810 | 0.8635 | 0.8781 | `rq:0037`, `rq:0038` |
| Japanese quality cohort | 0.4125 | 0.7464 | 0.8533 | 0.9405 | 0.9608 | none |
| Chinese cross-language cohort | 0.0000 | 0.1250 | 0.1667 | 0.2083 | 0.1750 | `rq:0037`, `rq:0038` |

The values above are display-rounded only. The canonical report and its SHA retain full precision.
Independent recomputation from the emitted primary Fact IDs matched all 38 per-query values and the
macro values exactly. The report also retains category, style, scope, clause, and reference slices.
The semantic gate declares `quality_query_language="ja"`, so the accepted Japanese thresholds and
count caps remain unchanged while the Chinese slice is visible for later M9 improvement work.

## Partial-Coverage Diagnostics

The Japanese cohort retains six partial Top-10 queries and no zero-hit query. Of the four new
Chinese queries, dates and English-score requirements retrieve some gold evidence; the education
eligibility and common-material queries are zero-hit at Top-10. These are measured limitations, not
permission to change gold labels, Fact boundaries, rules, or accepted Japanese thresholds.

## Comparison And Next Decision

The prior deterministic-fake plumbing report had Recall@1/3/5/10 of
`0.0926 / 0.1181 / 0.1230 / 0.5044` and MRR `0.3109`; it was non-semantic and
quality-ineligible. The semantic result demonstrates why a semantic baseline was needed, but its
values are not targets and do not establish thresholds.

The offline semantic regression gate binds this report, its runtime inputs, the Japanese quality
cohort, and the retrieval-affecting implementation set without loading the model in CI. See
[ADR 0003](../decisions/0003-semantic-retrieval-regression-gate.md). Model files, the PDF, semantic
index, and the three local reports remain untracked.

## Verification

All model-dependent commands ran with the existing cache populated and both Hugging Face and
Transformers forced offline. The formal Demo used the fixed real PDF and an isolated generated
workspace; neither the model snapshot nor generated index/report files are committed.

| Check | Result |
| --- | --- |
| BGE-M3 index build plus three offline evaluations | 334 vectors; all three reports byte-identical |
| Dedicated cache-only model integration | passed; three evaluator outputs byte-identical |
| `pytest -m "not model_integration and not real_pdf" -q` | 1,301 passed, 17 skipped, 282 deselected |
| Formal real-PDF BGE-M3 Demo | live, ready, and `/app` returned HTTP 200 |
| `ruff check src tests --no-cache` | passed |
| `ruff format --check src tests --no-cache` | passed |
| `compileall -q src tests` | passed |
| `git diff --check` | passed |

The non-model run emitted one Starlette/httpx deprecation warning. It does not change the model
identity, offline mode, or test result.
