# EXAM-02A #274：四步页展示与来源合同候选

**#277 来源与 #278 隔离实现正在集中增量复审，尚未验收或合并。** 审核材料：[36 目标矩阵](exam02a-target-matrix.csv)、[187 项字段绑定](exam02a-field-bindings.json)、[原文账本](exam02a-source-ledger.md)、[逐系中文候选](exam02a-source-matrix.md)。#277 是来源候选，#278 已另设依赖分支实施只读 v2；规则、知识库及用户正在使用的网页未切换。

## 老师先看到什么

复用现有两校四步页：第一步选目标；第二步原有**关键时间、英语与材料**之后放考试卡；第三步现有个人核对不改；第四步沿用现有可选报告。考试卡首屏只有“是否笔试／哪天多久”“考什么／如何选答”“怎么评价（已载分值与英语方式）”三块。口述对象、公布和语言放进原有 `<details>`；三系课程另册排除必须在默认考试摘要可见；“查看官方原文”走现有来源窗口。手机同序单列，入口和摘要不在窄屏横向挤压。科目、选答和时段的数量都是数组，不限 3 组；文字按真实长度换行。不能把原文、`fact_type`、页路径或证据链直接铺在正文。

候选整页由[当前页面回放脚本](exam02a-current-page-candidate.py)直接加载 main 的 `advanced.html` 与 `app.css`，只把考试候选插入既有第二步 `#requirements-output`，保留 `flow-step`、完成步骤摘要、第三步修改、第四步准备清单、已有报告 drawer。システム制御系与建築学系各有桌面/手机的第二步、第四步截图；日期/材料/个人核对仅作当前结构的明确占位，不能作为对应系真实 API 响应。考试字段来自固定 PDF 页。第二步用“学校公布的 A/B 日程”查阅，不把 B 变成本人路线；报告主题默认不勾选。

## 建议的通用只读记录形状

下列对应 #278 当前隔离实现的**只读 v2 字段形状**，仍待设计验收。当前 `POST /v1/base-requirements?include_examination_information=true` 的 1.0 响应保持原样，包括信息工学系 B 日程两批次。只有新调用显式请求 `include_examination_information=true&exam_presentation_version=2` 时返回下面的 v2 考试信息；不带参数、旧 `true` 请求、两校既有基础规则及报告 API 均不变。可选 `course_id` 也只在显式 v2 查询参数中提供（例：`&course_id=地球生命コース`），不加入旧 `DemoTargetRequest` 的目标身份；缺省为 `unspecified`。未知课程 ID fail closed，不能通过改写部门 ID 绕过排除。本设计不要求第一步新增路线或课程必填项。

```json
{
  "schema_version": "2.0",
  "status": "available_official_paths",
  "target_identity": {"school_id": "isct", "department_id": "建築学系", "application_route": null},
  "applicability": {"catalog_route": null, "personal_route_state": "unconfirmed", "course_state": "unspecified", "covered_course_ids": [], "excluded_course_ids": []},
  "year_basis": {"exam_year": 2026, "kind": "reviewed_cross_page_context", "physical_pages": [1, 2], "department_page": 60},
  "pathways": [
    {"source_route": "a_schedule", "label_zh": "学校公布的 A 日程", "personal_eligibility": "unconfirmed", "written": {"status": "unknown", "time_zh": null, "subjects_zh": []}, "oral": {"status": "held", "description_zh": "A：7月11日"}},
    {"source_route": "b_schedule", "label_zh": "学校公布的 B 日程", "personal_eligibility": "unconfirmed", "written": {"status": "held", "time_zh": "8/18 共通 10:00–11:30；专门 A 13:30–17:30 或专门 B 13:30–15:30", "subjects_zh": ["共通科目和专门科目的已审中文说明"], "selection_rule_zh": "按所有志愿导师共同指定选择", "points_zh": "专业 500", "answer_language_zh": null, "administration_language_zh": null}, "oral": {"status": "held", "description_zh": "8/25口头问答；须携带作品集"}, "english": {"submission_zh": "本系已审英语说明"}}
  ],
  "field_bindings": [{"field_path": "b.subjects", "value_zh": "已审中文值", "missing_reason_zh": null, "sources": [{"source_id": "fact:00309", "physical_pages": [60], "exact_text": "全問必答"}]}],
  "evidence": [{"fact_id": "fact:00309", "pages": [60], "official_text": "官方原文"}]
}
```

上段是字段形状示意，非可运行招生响应；省略的完整目标身份、来源身份、官方标题及 PDF 路径由实际投影给出。#278 使用 `time_zh`、`subjects_zh`、`selection_rule_zh`、`points_zh`、`description_zh` 和逐字段 `field_bindings`，**没有**旧候选的 `sessions/components`、自动日期计算、`question_offer_count` 或口述 `dates` 数组。分时段和选答条件作为已审中文字段完整写出；不把这些未使用能力强行加入本轮生产。`target_identity.application_route=null` 保持目录原值；A/B 来源路径和本人资格分离。`not_held` 仅在原文明示时使用；未载细目仍写未知。字段来源绑定保留原文、页和 Fact 身份，正文与报告只输出中文整理。

### 五个必须同时成立的状态例子

| 当前目标／条件 | v2 响应 | 第二步与报告 |
|---|---|---|
| システム制御系，目录 route=null，课程未提供 | `status=available_official_paths`、`personal_route_state=unconfirmed`、`course_state=unspecified`，`pathways` 并列官方 A 口述与 B 笔试/口述 | 可查阅两张官方日程卡；标题写“学校公布的”；报告若选考试主题，分别列 A/B 并写“本人适用路径待学校确认”，不写本人一定参加 B。 |
| 情報工学系，目录 route=`b_schedule` | 旧请求仍是 1.0 原值；显式 v2 可为 `available_official_paths`、`personal_route_state=catalog_b` | B 内容与现有审核值一致；A 作为同册背景资料可查阅，但旧页面与旧报告不新增 A。 |
| 社会・人間科学系，route=null | B `written.status=not_held`，依据 p.70 `fact:00330`；A 口述也 `not_held` | 卡片明确“学校公布的 B 日程不举行笔试，可能有书面筛选，8/18 或 19 口述”；报告不能生成空白笔试时间或“资料不足所以无笔试”。 |
| 三系之一 `course_id=地球生命コース` | `status=not_covered_course`，`pathways=[]`，携带另册提示与课程排除来源，不附通用系表肯定结论 | 页面和报告都写“地球生命课程采用另册，本项目尚未覆盖该课程考试安排”；不继承系表，英语及其他已有规则仍按原有边界处理。 |
| 建築学系，route=null，专门科目未确认 | A/B 官方日程并列；B 的共通十二题全答，专门 A 即日设计或专门 B 建筑科目六领域选一，导师指定科目尚未在 Profile 中确认 | 页面和报告列并行选择、各自时段，注明出愿时须按**所有志愿导师共同指定**选择；不代选、不推断资格，无导师数据库或必填新字段。 |

对三系课程使用同一版本化白名单：地球惑星科学系覆盖 `地球惑星科学コース`、排除 `地球生命コース`；応用化学系覆盖 `応用化学／原子核工学／人間医療科学技術／エネルギー・情報コース`、排除 `地球生命コース`；生命理工学系覆盖 `生命理工学／人間医療科学技術コース`、排除 `地球生命コース`。白名单与排除项来自 p.25/46/55 的课程栏与另册指示，[字段账本](exam02a-field-bindings.json)同时供服务校验、页面显示和报告读取。未提供课程时只说“本册所列课程的官方安排”，并显著提示地球生命另册未覆盖；明确提供非白名单未知课程时 fail closed。不得把三系整体停用。

考试年份统一用封面 2026 年 4 月刊行、2026 年 6 月出愿、p.2 连至 7/8 月选拔，再绑定各系表推定为 2026 年；两入学批次均为同册，不从 2027 年 4 月入学推算考试年。原 CS B 的跨页审核结论保留，其他系由各自系页与共同封面/流程组成独立来源绑定。

## 可信度、兼容与接入点

| 现有模块 | 审核后最小必要变化；本 PR 不实施 |
|---|---|
| `service/exam_presentation.py` 的 `load_exam_presentation` / `exam_response` | 将目前写死的 CS B scope、单一配置哈希、固定 3 组/题数/时段扩为经审核的只读记录集合；精确匹配学校、文档、学院、系、学位、批次，**不以 null route 匹配 B 本人资格**。分别载入本系官方 A/B 来源路径与个人适用状态，核实登记语料、PDF/KB 哈希、Fact 文本哈希、页、学院/系 scope、字段原文锚点和课程白名单/排除。缺件 fail closed；维持旧 1.0 CS B 行为。 |
| `service/static/unified-core.mjs` 的 `validateExamInformation` / `examReportRows` | 1.0 原响应仍按现有白名单校验；v2 校验 `status`、课程与来源路径的分离、中文时段／科目字段与逐字段来源绑定。明确 `not_held` 才可写“不举行”；未知空值不当作 0 分或无要求。报告句子写明“学校公布的”日程和本人适用未知，且按来源字段组装，不依赖证据数组第 0/1/2 项。`not_covered_course` 不输出该系笔试/口述肯定结论。 |
| `service/static/app.js` 的 `renderExamCard` / 第二步顺序 | 对 null 目录目标并列显示“学校公布的 A 日程”“学校公布的 B 日程”，不改变第一步/个人 Profile；卡片展示已审中文科目、选法和时段，口述折叠。沿用 `advanced.html` 的 `flow-step`、日期/材料/考试页内导航和现有原文按钮 `openDemoEvidence`；来源按字段 ID 查找、焦点回原触发按钮。CS 旧 1.0 B 卡保留。 |
| 报告主题和来源窗口 | 考试主题**默认不勾选**；选中才加入考试段落。生成、预览与复制使用同一已审核文本映射；独立复制必须有科目名称，不用“如上”。来源后台保留，不向正文输出 `fact_type` 等内部字段。打开原文显示对应页与条款，可返回/关闭。 |

新记录不得直接从 KB 运行时搜索决定展示；先由设计审核中文和作用域，再发布固定版本配置。配置中的 `source_identity`、每个 Fact 的 scope/页/text SHA 与 `field_bindings.exact_text` 均要与登记语料比对；封面无 Fact 时明确使用 `pdf_page` 锚点，不捏造 ID。`fact_type` 不能决定是否是考试事实：现有信息工学系 `fact:00288` 和电气电子 `fact:00230` 的类型均可能因表格抽取而不匹配。

可观察的回归验收建议：旧 CS B 两批次 1.0 精确兼容；其余 34 目标可查阅两条官方来源路径但不声称本人已选 B；数学无需外部成绩单，物理考试日提交，社会・人間无笔试，建筑需导师/科目条件；三系地球生命明确未覆盖；多时段、多选答、原文按钮和报告复制；来源 hash/页/scope/anchor 错配降级；两校切换、桌面/手机、未选考试报告不输出考试段落。以上是 #275 候选验收维度，不是本 PR 已运行的测试。

## 与已有英语规则的相交检查

| 系与来源 | 现有规则对应 | v2 考试说明的处理 |
|---|---|---|
| 数学系 p.19 `fact:00149`：不交外部成绩单、全员参加内部英语笔试 | `demo_requirements.py` 已有数学系例外分支及 `english:math`，不把外部证明缺失计成待办 | 一致：展示内部英语笔试及必要条件，定位现有英语卡，不创建第二套材料状态。 |
| 物理学系 p.21 `fact:00181`：出愿时**不交**，笔试当天携带打印的在线成绩单 | 已有一般英语材料/证明说明可能显示出愿时提交；本系特殊时点未见同等已审规则覆盖 | 标记 **潜在冲突字段 `english.submission_time`**；考试卡明确原文并提示按本系要求核对，正式材料待办仍由既有规则输出；#275 需先由设计审查规则适用性，不能静默覆盖。 |
| 土木・環境工学系 p.63 `fact:00314`：原则出愿时提交；不希望参加 A 口述时 7/29 必达、简易挂号邮寄 | 一般英语提交卡缺此条件分支 | 标记 **潜在冲突字段 `english.submission_condition`**；考试卡按原文呈现条件，个人是否符合由现有规则/学校核对，不能因本候选直接改材料待办。 |
| 其他系的考试英语配分/方式 | 现有英语考试种类、证明格式、有效期规则继续独立运行 | 考试配分不证明申请人合格；不替换 `english_preparation_result` 或五项证明字段的既有结果。 |

## 待设计独立验收的边界

上面的路线并列查阅、课程排除、2026 年跨页依据、建筑未选专门科目和英语冲突标记是本轮设计审查意见指定的候选决策；需审核来源与字段后才可作为 #275 正式合同。尚缺的地球生命另册不得下载补入，本册未载的选答数／配分保持空值。#278 已在独立依赖分支实施显式 opt-in v2；#277 与 #278 均待集中验收，不能合并或切换在线页。

## 本检查点的可复核证据与资源

- 已逐页目视核对 18 系主表：PDF 物理页 p.19、21、23、25、27、31、33、37、40、42、46、50、52、55、60、63、66、70；另看 p.1 封面、p.2 共通流程和续表 p.34、41、61，共 **23 个既有 PDF 页**。页图仅在忽略的本地缓存中渲染供检查，未复制或修改 PDF。CSV 有 **36 条精确目录目标**，其中 34 条当前 route 为空，2 条信息工学系为 `b_schedule`。
- 既有 PDF 85 页、5,088,401 字节；既有 391 Fact KB 3,361,076 字节。按上列 SHA-256 只读核对。[字段覆盖检查](exam02a-field-map-check.py)验证 **18 系、36 目标、187 字段、611 条来源锚点**的 Fact 文本 SHA、页、学院/系作用域及原文。p.40 纵向备注和三系课程栏是标明的人工 PDF 页锚点；“子串存在”本身不充当中文语义验收。
- 静态 Edge/Playwright 直接加载当前 main 的 `advanced.html`、`app.css`，没有旧 `unified.css` 侧栏。简单系：[第二步桌面](exam02a-evidence/simple-exam-desktop.png)、[第二步手机](exam02a-evidence/simple-exam-mobile.png)、[第四步桌面](exam02a-evidence/simple-readiness-desktop.png)、[第四步手机](exam02a-evidence/simple-readiness-mobile.png)；复杂系：[第二步桌面](exam02a-evidence/complex-exam-desktop.png)、[第二步手机](exam02a-evidence/complex-exam-mobile.png)、[第四步桌面](exam02a-evidence/complex-readiness-desktop.png)、[第四步手机](exam02a-evidence/complex-readiness-mobile.png)。[回放记录](exam02a-evidence/current-page-replay.json)验证原四步 DOM、完成步骤压缩、第三步修改入口、第四步材料待办、日期/材料/考试定位、口述/指南折叠、原文窗口、报告默认不勾选及两种复制文本、无横向溢出/页面错误。仅内存 GET `/app`、`/assets/app.css`；日期/材料/个人核对为清楚标记的结构占位，**不能证明真实 API 或 #275 生产体验**。
- 两例各保存了报告主题[未选时的复制文本](exam02a-evidence/simple-report-default.txt)、[选中考试后的复制文本](exam02a-evidence/simple-report-exam.txt)，以及建筑的[未选文本](exam02a-evidence/complex-report-default.txt)和[选中考试文本](exam02a-evidence/complex-report-exam.txt)。这些文本与静态样例使用同一候选状态，不冒充正式服务生成的报告。
- 本项累计资源：真实服务启动 **0**；真实产品 POST **0**；付费模型 **0**；下载 **0**；PDF 解析重跑 **0**；KB/向量构建 **0**；受保护资产写入／复制 **0**。仅只读 PDF、391 KB、保存目录响应及本地静态浏览器。没有切换在线预览。
