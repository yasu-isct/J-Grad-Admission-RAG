# MAT-01 implementation evidence

Issue: [#213](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/213). Base main: `ceb1f05828825ca1b30cfeeb8c4b3074a59f262b`. Branch: `codex/mat-01-condition-preview`.

## Checkpoint 1: shared core and old behavior

The private old applicability comparison and ALL/ANY helpers delegate to one pure comparison/three-state core. Existing field extraction, type/date validation, scope, and evidence binding stay with the old wrapper. The old public models, imports, serialized profiles/rules/decisions, and ISCT five-item materials policy are unchanged. Focused applicability, rule resolution, old application materials, profile and applicant report tests passed (`190 passed, 3 skipped`) after the delegation. The new core tests cover all nine operators, unknown, ALL/ANY and empty sets. No real MAT-01 preview command was run at this checkpoint: **0/3**.

## Checkpoint 2: pinned policy and synthetic previews

The new request keeps the original ApplicantProfile 1.0 and adds a full exact target and two strict bool/null employment assertions. The policy and separate trust file were read from versioned small JSON; the official candidate bindings are policy prerequisites only, never read from a runtime KB. Both entry points use the same shared core. No material obligation or official evidence claim is emitted. The three small request fixtures under `tests/fixtures/material_condition_*.json` are canonical extractions of the three synthetic requests in `material-condition-examples-v1.json`, without its expected values.

The exact preview command for each developer call was:

```powershell
.\.venv\Scripts\python.exe -m jgrad_admission_rag.reasoning.material_condition_cli --policy docs/onboarding/material-condition-policy-v1.json --trust docs/onboarding/material-condition-trust-v1.json --request tests/fixtures/material_condition_employed_and_retaining.json --request tests/fixtures/material_condition_not_employed_unknown_intention.json --request tests/fixtures/material_condition_employment_unknown.json
```

An outer Python runner imposed a 60-second `subprocess.run` timeout, captured stdout bytes, and wrote/checked the single ignored `outputs/material-condition-preview/previews.jsonl` file. It ran this same command twice. The first preview process succeeded and produced three canonical lines; the outer evidence script then exited 1 because its *hash-reporting slice* mistakenly treated `--request` as a path **after the file had already been written**. This call counts as **1/3** despite that reporting error. A read-only audit confirmed the saved JSONL has three valid lines, SHA-256 `4ed106a8b6bf2511b127e4ef52c093be2ac8348b334868d88421ea25df1e46c5`, 4,801 bytes. The file mtime was `2026-09-28T03:28:52.694681Z`. The second identical preview command succeeded at `2026-09-28T03:29:24.610117Z`–`03:29:25.029162Z`, 0.422 s, returned exactly those bytes, and left the saved bytes and mtime unchanged. No duplicate output was created. Both outer calls completed in under one second, so even a conservative 2-second cumulative count is below the 3-minute limit.

| Input/output | SHA-256 |
| --- | --- |
| reviewed policy | `3a43af563ebb66840fa804a186779553b451b7474033fbc824f34398ebcf0bb8` |
| request employed=true, retain=true | `dbca460832e9408ebd6084cc0bd8f28e32cd6be899f4d78e40af6e0f535d8e74` |
| request employed=false, retain=null | `9f478214a293ca76f14d67f236bb0d063c3e686376aad38930ec98048b352247` |
| request employed=null, retain=null | `809ef40d766c14b7ab5b7511340b4697cfa0f3a430a771904b6a353f90957d1c` |
| three-line JSONL output | `4ed106a8b6bf2511b127e4ef52c093be2ac8348b334868d88421ea25df1e46c5` |

Per-line canonical preview SHA-256 (including LF), in the same case order: `9b876386fb9f46c805e68538f51ea7f09d951f1ef50566e1ac2b42cbb569b549`, `a2c56e38d579afc1093b1b6ce6d1027cc78aa7c42bc61eff5db91bcbb0be3e7f`, and `34429cb316f414ea32567ae3118d1ed56590a2e3c2d80d0f99c2fd587454305d`.

Each line is below 256 KiB (1,538, 1,600, and 1,660 bytes without LF). English score sheet and checklist form conditions are `matched` in all cases, without implying submission is required. The work-plan condition is respectively `matched`, `not_matched` with the unknown intention still listed, and `needs_information` with both unknown fields listed. None contains `required`/`not_required` as an action or an official citation. The nine true/false/null combinations, exact target dimensions, profile conflicts, untrusted policy/result, duplicate/contradictory rules, and a different school's synthetic policy are covered by tests.

**Budget:** MAT-01 developer calls **2/2 used**; shared calls **2/3 used**, with **1/3 reserved for independent design review**. IMPORT-01 remains exhausted at **4/4**. No PDF, KB, index, model, parser, registry, network or paid call occurred. The old API/UI and formal report remain unchanged. This preview is condition-only and does not verify official scope, runtime evidence or a material obligation.

Final focused verification before PR: `295 passed, 5 skipped` across new conditions, legacy applicability, rule resolution, existing application materials, profile, applicant report, reviewed report plan, and the semantic implementation-fingerprint gate. Ruff check and formatting check on `src tests` passed; CI results are recorded in the PR. The exact final commit head is recorded in the Issue/PR handoff after commit. The three preview lines are held in one ignored local JSONL, and no real applicant data is present.

## Design review follow-up: complete reused context records

The design Agent found that the first PR head compared only `(document_id, fact_id)` keys when one context record appeared in multiple rules. A duplicate could therefore change `source_pages` or `authoritative_fact_text_sha256` and still pass structural policy validation. The revised graph check compares the complete normalized `ContextRecord` bytes (all binding fields, record ID and revision) for every reused record ID, after the existing source/Fact and duplicate-binding checks. Identical reuse remains valid; changed pages, text fingerprint, revision or Fact key fail in synthetic policy/trust tests. The pinned policy bytes, trust file and preview computation did not change.

Review-fix verification used only pure/synthetic tests: `339 passed, 6 skipped` with the design-focused test selection and `not real_pdf and not model_integration` marker exclusion; Ruff check/format and diff checks passed. No additional real preview command was run. MAT-01 remains **2/3** total, developer **2/2**, design **0/1**. The original three-line output hash above is unchanged; its independent reproduction remains for design review.
