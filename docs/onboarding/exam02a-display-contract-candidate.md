# EXAM-02A #274：四步页展示与来源合同候选

**设计检查点；未批准为 #275 生产合同。** 审核材料：[36 目标矩阵](exam02a-target-matrix.csv)、[逐字段原文账本](exam02a-source-ledger.md)、[逐系中文候选](exam02a-source-matrix.md)。本次不改变 API、页面、报告、规则、知识库或用户正在使用的网页。

## 老师先看到什么

复用现有两校四步页：第一步选目标；第二步原有**关键时间、英语与材料**之后放考试卡；第三步现有个人核对不改；第四步沿用现有可选报告。考试卡首屏只有“是否笔试／哪天多久”“考什么／如何选答”“怎么评价（已载分值与英语方式）”三块。口述对象、公布、语言和特殊条件放进原有 `<details>`；“查看官方原文”走现有来源窗口。手机同序单列，入口和摘要不在窄屏横向挤压。科目、选答和时段的数量都是数组，不限 3 组；文字按真实长度换行。不能把原文、`fact_type`、页路径或证据链直接铺在正文。

候选整页：[システム制御系（简单笔试）](exam02a-four-step-candidate.html?sample=simple)、[建築学系（复杂分支）](exam02a-four-step-candidate.html?sample=complex)。这两个静态样例采用现有页面的四步顺序和 CSS 类；日期/材料/个人核对区域仅作**结构占位**，不可作为对应系的真实响应或迁入生产。候选考试字段来自固定 PDF 页，未批准的 B 日程只能标为“资料中列有 B 日程；当前目录尚未确认所选路线”。建筑专门科目 A/B 需要出愿时的导师共通指定，不能默认其中一项。报告样板在样例第四步，展示考试主题如何在已有报告选择中出现；未选择则不输出考试结论。

## 建议的通用只读记录形状

下列为供设计审核的**候选**，尚未冻结名称。每条记录只描述一个精确的 `(school_id, document_id, college_id, department_id, degree_id, intake, application_route)` 目标；`application_route=null` 必须通过明确审过的路线决定才能生成 B 安排，不能在前端以空值自动匹配 B。已验收信息工学系 B 响应维持 1.0 默认行为，新增结构只由审核后的新请求显式启用。

```json
{
  "schema_version": "candidate-2",
  "target_identity": {"school_id": "isct", "document_id": "isct_2027_4_2026_9_master", "college_id": "…", "department_id": "…", "degree_id": "master", "intake": {"year": 2027, "month": 4}, "application_route": null},
  "status": "available | route_unresolved | source_gap | not_covered | unavailable",
  "source_identity": {"source_pdf_sha256": "57f…", "source_kb_sha256": "7fa…"},
  "year_basis": {"exam_year": 2026, "kind": "reviewed_cross_page_context", "physical_pages": [1, 2, 60]},
  "pathways": [{"schedule_route": "b_schedule", "condition_zh": "B 日程是否适用，待学校路线确认", "written": {"status": "held | not_held | unknown", "sessions": [{"date": "2026-08-18", "start": "10:00", "end": "11:30", "minutes": 90}], "components": [{"label_zh": "共通科目", "subjects_zh": ["…"], "question_offer_count": 12, "answer_count": 12, "selection_rule_zh": "全部作答", "points": null}], "answer_language": null}, "english": {"assessment": "external_score | internal_written | unknown", "points": null, "submission_condition_zh": null}, "oral": {"status": "held | not_held | unknown", "dates": [], "eligibility_condition_zh": null, "announcement": null}}],
  "evidence": [{"fact_id": "fact:00309", "pages": [60], "scope_type": "department", "scope_targets": ["建築学系"], "parent_college": "環境・社会理工学院", "official_text": "…", "highlights": []}],
  "field_bindings": [{"field_path": "pathways[0].written.components[0].answer_count", "source_id": "fact:00309", "physical_page": 60, "printed_page": "60", "exact_text": "全問必答", "interpretation_zh": "共通科目 12 小题全部作答"}]
}
```

这段结构说明**约束**，不是示例招生 JSON：省略号字段不允许作为生产值。`held`、`not_held`、`unknown` 三态防止把没有查到笔试误报为“不举行”；没有英语配分时用 `null`，不能算出新总分。`sessions` 可表达数学、応用化学、土木的分时段，`components` 可表达化学共通与选答、融合理工上午／下午、建筑共通及导师指定的专门 A/B。`question_offer_count` 与 `answer_count` 独立，例如信息工学系出 3 题并未授权写“考生选 3 题”。`selection_rule_zh` 只能转述原文；未载时为 `null`。A/B **科目组、专门科目**分别用 `component` 标识，不拿 `schedule_route` 表示。

## 可信度、兼容与接入点

| 现有模块 | 审核后最小必要变化；本 PR 不实施 |
|---|---|
| `service/exam_presentation.py` 的 `load_exam_presentation` / `exam_response` | 将目前写死的 CS B scope、单一配置哈希、固定 3 组/题数/时段拆为经设计审核的只读记录集合；按精确目标与 route 匹配，核实已登记语料、PDF/KB 哈希、Fact 文本哈希、页、学院/系 scope、每条字段的原文 anchor。缺件 fail closed。保持原 1.0 CS B 行为和 `not_covered`/`unavailable`。 |
| `service/static/unified-core.mjs` 的 `validateExamInformation` / `examReportRows` | 1.0 原响应仍按现有白名单校验；新版本按 `status`、路径和变长 `sessions/components` 校验。`not_held` 只在原文明确“不举行”时展示；未知空值不可当 0 分或无要求。报告按已审字段组装，不依赖第 0/1/2 个来源数组位置。 |
| `service/static/app.js` 的 `renderExamCard` / 第二步顺序 | 标题由有效 route 给出；`route_unresolved` 只显示条件提示与已核对的资料候选，不能冒充本人考试安排。按组件循环显示三块摘要，口述折叠；来源按钮由字段绑定标识找证据，复用 `openDemoEvidence`，保留焦点返回。其他现有两校组件、问答、报告按钮不动。 |
| 报告主题和来源窗口 | 考试主题仍可选；生成与复制采用同一映射。每个报告句子只取已验证字段，来源后台保留，不向正文输出 `fact_type` 等内部字段。打开原文展示对应页／引文、可返回及关闭。 |

新记录不得直接从 KB 运行时搜索决定展示；先由设计审核中文和作用域，再发布固定版本配置。配置中的 `source_identity`、每个 Fact 的 scope/页/text SHA 与 `field_bindings.exact_text` 均要与登记语料比对；封面无 Fact 时明确使用 `pdf_page` 锚点，不捏造 ID。`fact_type` 不能决定是否是考试事实：现有信息工学系 `fact:00288` 和电气电子 `fact:00230` 的类型均可能因表格抽取而不匹配。

可观察的回归验收建议：旧 CS B 两批次 1.0 精确兼容；其余 34 目标在没有审核路线前不声称已选 B；数学无需外部成绩单，物理考试日提交，社会・人間无笔试，建筑需导师/科目条件；多时段、多选答、原文按钮和报告复制；来源 hash/页/scope/anchor 错配降级；两校切换、桌面/手机、未选考试报告不输出考试段落。以上是 #275 候选验收维度，不是本 PR 已运行的测试。

## 待设计决断

1. 17 个 `application_routes=[]` 的目标如何明确用户所处 A/B 日程。若不能从已审核规则推定，生产只显示“本册有 B 安排，路线待核对”，不得默认选 B。
2. 建筑学系导师指定的专门 A/B 科目如何表示“尚未填写”和“已确认”；与 A/B 日程分开。地球生命课程的外部册缺失时应停用该课程分支。
3. 跨页 2026 年核验如何复用 #260 已审核结论至其他 17 系；需逐系确认同册页作用域、不能机械替换年份。
4. 物理、土木、数学的特殊英语提交要求与现有英语规则的相交方式；不能让考试卡覆盖正式出愿规则。

## 本检查点的可复核证据与资源

- 已逐页目视核对 18 系主表：PDF 物理页 p.19、21、23、25、27、31、33、37、40、42、46、50、52、55、60、63、66、70；另看 p.1 封面、p.2 共通流程和续表 p.34、41、61，共 **23 个既有 PDF 页**。页图仅在忽略的本地缓存中渲染供检查，未复制或修改 PDF。CSV 有 **36 条精确目录目标**，其中 34 条当前 route 为空，2 条信息工学系为 `b_schedule`。
- 既有 PDF 85 页、5,088,401 字节；既有 391 Fact KB 3,361,076 字节。按上列 SHA-256 只读核对；所有生成的日文账本行已程序校验为原 Fact `text` 的精确子串，并核对 Fact 页。原件中的混合表格行另以目视 PDF 行列校准。
- 静态四步页在 Edge/Playwright 用 **1440×900 和 390×844** 对简单与复杂样例各回放一次，四张截图：[简单桌面](exam02a-evidence/simple-desktop.png)、[简单手机](exam02a-evidence/simple-mobile.png)、[复杂桌面](exam02a-evidence/complex-desktop.png)、[复杂手机](exam02a-evidence/complex-mobile.png)。验证目标下拉内容、考试卡显示、原文示意窗口开关、无页面错误／横向溢出、手机上第四步位于第三步之后。样稿只本地打开静态 HTML；日期/材料/个人核对为结构占位，**不能用来证明实际 API 或 #275 生产体验**。
- 本项累计资源：真实服务启动 **0**；真实产品 POST **0**；付费模型 **0**；下载 **0**；PDF 解析重跑 **0**；KB/向量构建 **0**；受保护资产写入／复制 **0**。仅只读 PDF、391 KB、保存目录响应及本地静态浏览器。没有切换在线预览。
