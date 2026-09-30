# PREP-02 #258 实施与验证

实施分支 `codex/prep02-graduation-submission` 基于 main `304243df805032a6a030aa82bf85bc05cbcdf355`。仅扩展原两校四步页的 ISCT 毕业与提交进度，保留 GSFS 三主题、高级工具、问答和原报告按钮。未改 `service/app.py`、M9 摘要、领域 `ApplicantProfile`、已审核规则或来源资产。

## 字段、规则、证据与中文输出

客户端只传可选 `application_preparation`；旧请求不带此组时响应仍不含 `application_preparation_result`。新组存在且全空时返回待确认项。服务器依当前目标选择已审核资料，并在同一次 `build_applicant_report` 轨迹中复用 `source_decisions`、`predicate_outcomes`、冲突和覆盖结果；与英语准备同时请求时不重复执行报告引擎。日期判断使用对应规则谓词结果，前端不另算官方截止日。

| 新字段 → 旧 Profile | 已审核规则与来源 | 用户可见结果 |
| --- | --- | --- |
| `completion_date` → `academic_credentials[0].completion_date` | `isct-master-direct-path-1-university-{apr,sep}-completed` 或 `direct-path-3-foreign_16_year` 对应规则；p.6–7 `fact:00056/00059/00060/00062` | 仅说该毕业日期是否在本批次期限内；整体学历资格仍待其他条件核对 |
| `expected_completion_date` → `academic_credentials[0].expected_completion_date` | 同路径的 `expected`；9月 `sep-special-contact`，另见 `fact:00085` | 9/28–9/30 显示出愿前联系学校，不按一般超期处理 |
| `individual_review_status` → `eligibility_facts.individual_review_status` | 仅两条已支持个别审查路径，沿用对应资格路径证据；此字段为办理进度自报，不是学校审查决定 | 尚未申请／等待结果／流程已完成均不写成审查通过 |
| `materials_dispatched_date` → `application_submission.materials_dispatched_date` | 寄出为自报；结合 `materials-arrival-window-{apr,sep}` 与 p.9 `fact:00100` 提醒必着 | 已寄出但到达未知时，请确认实际送达；不以寄出日推断按时送达 |
| `materials_arrival_date` → `application_submission.materials_arrival_date` | `materials-arrival-window-{apr,sep}` 的上下界谓词；p.9 `fact:00100` | 区分接收期前、期间内、必着截止后；即使期间内也只说自报到达，不说学校受理 |
| `online_steps_completed` → `application_submission.online_steps_completed` | `online-steps-not-completion-{apr,sep}`；p.9 `fact:00100` | true/false/null 分别为自报完成、明确尚未完成、待确认；始终单独核对纸质材料 |

日期只在 `completion_state` 对应时允许提交；到达早于寄出返回字段校验错误，页面在到达输入旁说明。资格审查进度只对外国15年、大学在学满3年两条已支持路径显示。浏览器切换毕业状态清空相反日期，切换路径清空旧审查进度，换目标重置个人输入和旧结果。未根据学历标签补写国家、受教育年数或“审查通过”；规则缺少的这些条件仍保持未知。

固定来源身份为 `isct_2027_4_2026_9_master`，PDF SHA-256 `57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735`，KB SHA-256 `7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce`。其他资料身份或哈希不显示肯定结论。服务端证据与规则 ID 保留用于验证和原文入口；可选报告正文及复制不展示这些内部字段。

## 实际响应与页面样张

[单次真实服务日志](prep02-evidence/journal.json)记录 1 次启动、1 次基础要求 POST、2 次个人对照 POST，均 HTTP 200；服务已停止。代表场景为2027年4月信息工学系 B 日程：预计2027-03-20毕业、2026-06-09寄出、送达日期未知、网上手续自报完成。实际[请求](prep02-evidence/dispatched_unknown_arrival-request.json)、[基础要求](prep02-evidence/base.json)、[个人对照响应](prep02-evidence/dispatched_unknown_arrival-response.json)保存于仓库；另一份[晚毕业及实际送达响应](prep02-evidence/late_graduation_arrival-response.json)供审核不同状态。

同一实际响应在静态页回放（拦截基础／对照 POST，产品服务与产品 API 调用均为 0）：

| 页面 | 桌面 1440px | 手机 390px |
| --- | --- | --- |
| 第三步输入 | [截图](prep02-evidence/desktop-step3.png) | [截图](prep02-evidence/mobile-step3.png) |
| 第四步提醒 | [聚焦截图](prep02-evidence/desktop-step4-focus.png) | [聚焦截图](prep02-evidence/mobile-step4-focus.png) |
| 仅“材料与待办”报告 | [聚焦截图](prep02-evidence/desktop-report-materials-focus.png) | [聚焦截图](prep02-evidence/mobile-report-materials-focus.png) |
| 仅“关键时间”报告 | [截图](prep02-evidence/desktop-report-dates.png) | [截图](prep02-evidence/mobile-report-dates.png) |

[桌面复制文本](prep02-evidence/desktop-materials-copy.txt)与[手机复制文本](prep02-evidence/mobile-materials-copy.txt)逐字一致，SHA-256 均为 `21ce0d875ab9c530ae49dc35a2a641918fe11a49f3bb56ff55bddd129117608b`。仅选关键时间时无个人毕业、寄送、英语或材料准备结论；仅选材料与待办时显示寄送提醒。浏览器还核对优先链接目标与键盘焦点、四种筛选、五项材料数量、原文窗口、输入冲突提示、切校清空状态和零水平溢出。

## 验证与预算

- 真实391只读集成：`tests/test_prep02_application.py` **18 passed**，覆盖请求→Profile→原有规则→证据→中文结果、April/Sep毕业边界和特殊联系、到达首末日及早晚、空值/false、两条个别审查路径、旧请求兼容和数学英语例外。PREP-01 既有英语集成 **19 passed**。
- 四步、第四步与报告回归 **12 passed**；Node 展示／报告主题 **9 passed**。Ruff、JavaScript 语法和补丁空白检查通过。GitHub CI 以最终 PR head 结果为准。
- 12 项受保护资产前后哈希一致，详见日志。开发累计真实服务 **1/1**，基础／个人对照 POST **3/6**，GSFS 报告 POST **0**；付费、问答调用、下载、解析重跑、KB/索引构建 **0**。设计预算未动。8005/8004/8003 等预览及其源目录未改。

本核对不证明学校已受理、个别资格审查通过或最终出愿资格成立。#259、#260 尚未开始。
