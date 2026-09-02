# BGE-M3 Semantic Baseline

This is the first semantic characterization for the frozen 34-query Japanese admission-retrieval
benchmark. It is evidence for a later threshold decision, not a quality gate or a pass/fail claim.
The model, benchmark, retrieval configuration, and input KB were held fixed throughout.

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
| Current KB, schema `0.5`, 298 Facts/Units | `8223fb91628a5c2d52536075057a4b954fee0f0abf0640db017c4acf8013f66d` |
| Frozen benchmark | `3b2d0452c1d81be5a0da78ed05a4d09684bed174e5a621af79a4b2a9109845fd` |
| Payloads | `f1530da8b93f7ae0e816e43bbde0464c453b4d308743f28a2b03029ca0e4beb3` |
| Semantic vectors | `2ea4241fc7a9242d8e4d26f01fb5b40c5c831b13802fc9756b27a6e1ad96e95e` |
| Index manifest | `99f275eb9f766fd703097317c646550bfe4e823319a1aca4ca43472282e89b19` |

The semantic index is a new absent-directory build with 298 normalized vectors. It binds the model
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

All three Windows-produced reports had SHA-256
`86624fdcca3e939bfb4ce341135349d5415738e0acfd3a09d431be7d60edc40a` and were byte-identical.
For cross-platform CI, RET-09 commits the evaluator's canonical LF JSON representation; its SHA-256
is `0599df0e7b8f8838b872e959a9f755265071a83302599fef19dfbdf4de1895a8`.
Each reports `semantic_evaluation=true`, `quality_eligible=true`, and `gate_status=not_evaluated`.

| Queries | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR | Zero hits |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Overall, 34 | 0.4194 | 0.7569 | 0.8564 | 0.9417 | 0.9608 | none |

The values above are display-rounded only. The canonical report and its SHA retain full precision.
Independent recomputation from the emitted primary Fact IDs matched all 34 per-query values and the
macro values exactly.

| Breakdown | Queries | R@1 | R@3 | R@5 | R@10 | MRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| category: application_dates | 2 | 0.2500 | 0.7500 | 0.9167 | 1.0000 | 1.0000 |
| category: contacts_forms | 2 | 0.6667 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| category: department_requirements | 4 | 0.7500 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| category: documents | 5 | 0.4250 | 0.6500 | 0.8000 | 0.9000 | 1.0000 |
| category: eligibility | 3 | 0.2056 | 0.5333 | 0.6444 | 0.7667 | 1.0000 |
| category: enrollment | 3 | 0.2333 | 0.7000 | 0.9333 | 0.9333 | 0.7778 |
| category: fees | 3 | 0.2778 | 0.7222 | 0.8333 | 1.0000 | 0.7778 |
| category: language_tests | 4 | 0.6667 | 0.8750 | 0.9583 | 1.0000 | 1.0000 |
| category: results | 2 | 0.2667 | 0.6333 | 0.8333 | 1.0000 | 1.0000 |
| category: selection_exams | 6 | 0.3250 | 0.7250 | 0.7583 | 0.9028 | 1.0000 |
| style: exact_term | 7 | 0.2667 | 0.6690 | 0.6976 | 0.8452 | 0.9048 |
| style: identifier | 6 | 0.3889 | 0.7222 | 0.9167 | 1.0000 | 0.8889 |
| style: paraphrase | 21 | 0.4790 | 0.7960 | 0.8921 | 0.9571 | 1.0000 |
| scope_sensitive: false | 25 | 0.3603 | 0.7127 | 0.8347 | 0.9307 | 0.9467 |
| scope_sensitive: true | 9 | 0.5833 | 0.8796 | 0.9167 | 0.9722 | 1.0000 |
| multiple_clause: false | 27 | 0.4778 | 0.8160 | 0.9000 | 0.9877 | 0.9506 |
| multiple_clause: true | 7 | 0.1940 | 0.5286 | 0.6881 | 0.7643 | 1.0000 |
| reference_expansion: false | 33 | 0.4245 | 0.7646 | 0.8672 | 0.9551 | 0.9596 |
| reference_expansion: true | 1 | 0.2500 | 0.5000 | 0.5000 | 0.5000 | 1.0000 |

## Partial-Coverage Diagnostics

There are no zero-hit queries. The six rows below have missing gold Facts at primary Top-10. IDs
are evidence references only; no benchmark question or admission text is reproduced here.

| Query | Category/style/flags | Gold IDs | Primary Top-10 IDs | First rank | Reference-only | Classification and evidence |
| --- | --- | --- | --- | ---: | --- | --- |
| `rq:0008` | eligibility / paraphrase / multi | `24,25,28,29,31` | `24,31,28,88,106,103,89,105,271,25` | 1 | none | `multi_clause_partial`: `fact:00029` is fused rank 12. |
| `rq:0012` | eligibility / exact_term / multi, reference | `57,59,64,66` | `57,64,75,83,63,81,106,70,77,88` | 1 | `59,66` | `reference_only_recovery`: attached resolved targets recover `59` and `66`; their primary fused ranks are 31 and 32. |
| `rq:0019` | selection_exams / exact_term | `2,4,6,95,100,101` | `95,100,225,166,177,168,193,2,4,178` | 1 | none | `semantic_candidate_missing`: `fact:00006` is absent from the 50-result fused candidate set; `101` is fused rank 17. |
| `rq:0021` | enrollment / paraphrase / multi | `2,5,6,103,105` | `5,2,105,103,109,31,27,54,271,280` | 1 | none | `lexical_only_candidate_lost_in_fusion`: `fact:00006` lexical rank 6, vector rank 17, fused rank 11. |
| `rq:0024` | documents / paraphrase / multi | `110,111,112,113,114,115,116,117` | `113,117,109,110,114,119,87,118,91,89` | 1 | none | `semantic_candidate_missing`: `112` and `116` are absent from the fused top 50; `111` and `115` are ranks 36 and 37. |
| `rq:0031` | selection_exams / exact_term / scope | `106,233,234,235` | `234,235,233,236,238,186,237,177,241,178` | 1 | none | `lexical_only_candidate_lost_in_fusion`: `fact:00106` lexical rank 5, vector rank 31, fused rank 12. |

Fact IDs in compact cells omit `fact:` and leading zeroes. These classifications are a closed,
evidence-backed description of the observed run. They do not edit annotations, revise Fact
boundaries, or tune ranking.

## Comparison And Next Decision

The prior deterministic-fake plumbing report had Recall@1/3/5/10 of
`0.0926 / 0.1181 / 0.1230 / 0.5044` and MRR `0.3109`; it was non-semantic and
quality-ineligible. The semantic result demonstrates why a semantic baseline was needed, but its
values are not targets and do not establish thresholds.

RET-09 reviewed these full-precision results, the six diagnostic rows, and the approved tolerances.
The resulting offline semantic regression gate binds this report, its runtime inputs, and the
retrieval-affecting implementation set without loading the model in CI. See
[ADR 0003](../decisions/0003-semantic-retrieval-regression-gate.md). Model files, the PDF, semantic
index, and the three local reports remain untracked.

## Verification

All commands ran after acquisition with the external cache already populated and offline variables
set. No Python source file changed in RET-08, so changed-file formatting had no target.

| Check | Result |
| --- | --- |
| `pytest -m model_integration` | 1 passed, 484 deselected |
| `pytest -m "not model_integration"` | 482 passed, 2 skipped, 1 deselected |
| `pytest -m real_pdf` | 21 passed, 464 deselected |
| `ruff check . --no-cache` | passed |
| `compileall -q src tests` | passed |
| `git diff --check` | passed |

The model integration run emitted a third-party future-API warning and the known Windows pytest-cache
permission warning. Neither changes the model identity, offline mode, or test result.
