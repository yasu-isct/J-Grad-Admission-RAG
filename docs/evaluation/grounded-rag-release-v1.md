# Grounded RAG Release Evaluation v1

M9-05 closes the local end-to-end RAG release with checked-in, deterministic evidence. It does not
turn model output into authority: official Facts and pages, reviewed applicability state, and
server-hydrated citations remain the trust boundary.

## Reviewed inputs

- 20 Japanese/Chinese grounded-answer cases covering education, individual review, dates, English,
  Japanese, common materials, department scope, missing profile data, unsupported scope, unsafe
  conclusions, and no-evidence refusal.
- A 42-query Japanese/Chinese retrieval benchmark bound to the current formal KB and exact PDF.
- Pinned `BAAI/bge-m3` revision
  `5617a9f61b028005a4858fdac845db406aefb181`, loaded cache-only with 1024-dimensional embeddings.
- One fixed Science Tokyo master's target for April 2027, Information Science and Engineering,
  Department of Computer Science, B schedule.

Categories outside the current human-reviewed answer plan remain in the suite but must fail closed.
This separates retrieval quality from authority to answer: a query may retrieve relevant text while
the answer layer still refuses because no reviewed rule is allowed to support the conclusion.

## Accepted metrics

| Metric | Observed | Gate |
| --- | ---: | ---: |
| Release-subset Recall@10 | 0.7121 | >= 0.70 |
| Release-subset MRR | 0.5114 | >= 0.50 |
| Citation correctness | 1.0 | 1.0 |
| Citation completeness | 1.0 | 1.0 |
| Unsupported claim rate | 0.0 | 0.0 |
| Groundedness | 1.0 | 1.0 |
| Refusal correctness | 1.0 | 1.0 |
| Missing-information correctness | 1.0 | 1.0 |
| Chinese-to-Japanese hit rate at 10 | 0.75 | >= 0.50 |

The MRR gate is intentionally scoped to the 11 retrieval-linked release cases, including difficult
Chinese safety/refusal cases. It is not the overall retrieval benchmark MRR. Across all 42 queries,
the same report records Recall@10 `0.8495` and MRR `0.8312`.

The accepted observations contain 8 answered cases, 2 needs-information cases, and 10 refusals.
They are recorded from real loopback HTTP responses, not copied from expected values. Only public,
validated `GroundedAnswer` state is retained; raw provider responses and hidden reasoning are not.

## Offline gate

The default Quality workflow runs without a model cache or API credential:

```powershell
jgrad-check-grounded-rag-gate `
  --suite tests\fixtures\grounded_rag_evaluation_suite_v1.json `
  --observations tests\fixtures\grounded_rag_observations_v1.json `
  --retrieval-report tests\fixtures\grounded_rag_retrieval_report_v1.json `
  --report tests\fixtures\grounded_rag_evaluation_report_v1.json `
  --policy config\grounded_rag_release_gate_v1.json
```

The policy binds the canonical suite, observations, retrieval report, and recomputed report by
SHA-256. Any changed evidence identity, citation, expected behavior, metric, or threshold fails the
gate until the reviewed baseline is deliberately regenerated and rebound.

## Real acceptance

The formal run used the exact official PDF, the pinned BGE-M3 cache in offline mode, the installed
FastAPI service, and headless Chrome. Desktop 1440px and mobile 390px flows selected the reviewed
target, asked `出願期間と書類必着日はいつですか。`, received the reviewed page-9 answer, opened
both citations in the evidence drawer, verified the local PDF `#page=9` link, and checked for
horizontal overflow. A student-housing vacancy question produced no claim and was safely rejected as
outside the reviewed scope. Invalid-citation fail-closed behavior is covered by deterministic API
and orchestration tests.

## Paid provider boundary

`.github/workflows/manual-paid-generation-evaluation.yml` is workflow-dispatch only. It requires an
environment approval, the exact one-run authorization phrase, an explicit model snapshot, a bounded
case count, an API key supplied only through secrets, and synthetic inputs. It persists no raw
responses. M9-05 acceptance did not execute this workflow and incurred no paid API calls.
