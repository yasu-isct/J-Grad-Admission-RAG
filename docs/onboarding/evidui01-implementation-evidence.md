# EVID-UI-01 implementation and evidence

## Existing resource → reuse → necessary difference

| Existing resource | Reuse location | Necessary difference |
| --- | --- | --- |
| `verify_evidence_bytes` and `ReviewedMaterialSliceEvidence.relations` | `reference_workspace._presentation` uses the same validated bundle as the original evidence GET | Project only relations whose endpoints are visible records of that topic; no new inference or source files |
| `ReferenceEvidenceResponse` and `/v1/reference-slices/{id}/evidence` | Same snapshot, target, plan revision, records and GET | Optional `topic.relations`, defaulting to empty for old payloads; validation rejects invisible endpoints |
| `mapSliceEvidence` and the original four-step material cards | Existing target/snapshot checks, source mapping and card rendering | Preserve record role, stage, page and per-topic relations; one compact relation button replaces multiple source buttons only for reviewed GSFS topics |
| `openDemoEvidence` and `#evidence-drawer` | Original source text, pages, official link, close/Escape and focus return | The same dialog first displays source nodes and reviewed arrows, then switches to original text and back; no second dialog or route |
| REPORT-02 `readerReport` and original report buttons | Existing validated report and local preview/copy | Unchanged; a real browser check opened the report without adding another POST |

The existing repository callers (`app.js` and `reference.js`) accept the additive GET field. The Python response model remains closed for unknown fields, while an old response with no `relations` still validates and renders independent source cards. A strict external client that rejects new fields would need its own additive-field update; no such client is present in this repository.

## Reviewed relationship mapping

The five rows below come from the verified plan/seed relation set. The [real GET response](evidui01-evidence/gsfs-evidence-real.json) carries the same five directed edges under the three topics, bound to the same snapshot and revision. `E` identifiers are audit labels here; the user window shows titles, pages and Chinese meanings.

| Topic | Reviewed direction | Record/page binding | User meaning |
| --- | --- | --- | --- |
| 英语成绩单 | E03 → E01, `cross_reference` | 专攻追加材料表 PDF 1 → 研究科共通要项 PDF 6 | 送付方法参照；不新增普遍提交义务 |
| 英语成绩单 | E01 → E02, `department_specific_detail` | 共通要项 PDF 6 → 专攻入试案内 PDF 28 / 印刷 26 | 具体要求按专攻确认；E02 是本条直接依据 |
| 提交书类检查表本身 | E04 → E05, `consulting_is_distinct_from_submitting` | 同一入试案内 PDF 28 / 印刷 26 → PDF 40 / 印刷 38 | 参照检查表与提交表本身不同；两个页面分别保留 |
| 学业与职务両立计划书 | E07 → E06, `shares_employment_context_but_separate_enrollment_stage` | 入试案内 PDF 28 入学手续上下文 → 同页出愿条款 | 虚线标明入学手续相关，不当成出愿必交义务 |
| 学业与职务両立计划书 | E08 → E06, `corroborates_condition_with_submission_method` | 专攻追加材料表 PDF 1 → 入试案内 PDF 28 / 印刷 26 | 补充在职条件与上传方式共同说明 |

An unknown relation kind keeps the source nodes and shows that some relations could not be displayed. Missing relations leave independent nodes. Invalid endpoints are rejected by the server DTO and ignored by the client. The existing scope/snapshot checks also reject a mismatched response before display; a revision mismatch now fails closed when a revision is advertised.

## Validation and resource ledger

- Synthetic tests: 18 targeted reference/API/browser tests passed; 5 Node projection tests passed. They cover missing relations, old-field absence, invisible endpoints, unknown kind, same-file records, stage styling, original/back/Escape, target/snapshot mismatch and the preserved report flow. Ruff, JavaScript syntax and diff checks passed.
- Real local browser: the original two-school four-step page was used with existing read-only 391 and GSFS assets. [Journal](evidui01-evidence/real-browser-journal.json) records three GSFS material cards, five matching plan edges, graph → original → back → close/Escape in one dialog, GSFS step 4, ISCT step 2, zero automatic report POSTs while viewing graphs, no browser errors and no horizontal overflow. See [GSFS step 2 desktop](evidui01-evidence/gsfs-step2-desktop-full.png), [mobile](evidui01-evidence/gsfs-step2-mobile-full.png), [three graph captures](evidui01-evidence/gsfs-1-graph-desktop.png), and [ISCT step 2 desktop](evidui01-evidence/isct-step2-desktop-full.png). The other two graph cases and mobile captures are alongside these files.
- The first real session stopped after the three relation flows because an assertion expected one particular status phrase in step 4. The second and final service session replaced that assertion with the actual three-card result and completed the two-school flow. Cumulative developer use: **2/2 service starts, 3/3 GSFS report attempts, 1/4 base/comparison POST, 0 other POSTs, 0 paid calls**. Both services stopped. The same 30 protected files matched before/after SHA-256 values; see the journal. Design allowance remains unused.
- The live session captured GSFS step 2 at 1440/390, GSFS step 4 at 1440, and ISCT step 2 at 1440. [GSFS step 4 mobile](evidui01-evidence/gsfs-step4-mobile-replay-full.png) and [ISCT step 2 mobile](evidui01-evidence/isct-step2-mobile-replay-full.png) were captured by a separate [saved-response replay](evidui01-evidence/replay-journal.json), with zero live service starts or POSTs. No further real service start is available in the developer budget.

The implementation did not alter reviewed plan, seed, trust, policy, canonical report, PDF, KB, index or model artifacts. A rollback can remove the optional DTO projection and graph UI while leaving the original source viewer and REPORT-02 report intact.
