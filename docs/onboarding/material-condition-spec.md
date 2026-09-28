# MAT-01：复用现有判断逻辑，补齐材料条件与申请人补充信息

执行：[Issue #213](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/213)。
状态：#213 已在 PR #215 独立验收并合并；当前没有下一项 Ready 实现，交接记录于 #191。
M15；依赖 #209 / PR #211 已验收，基线 main `595e6998ed8dcba0f565d732ba09180e605078cd`。
[ADR 0012](../decisions/0012-material-conditions-and-report-boundaries.md) 是本任务边界。

## 背景和用户可见目标

官方原文要求“在职，并希望保持在职身份入学”的人提交学业与职务両立计划书。
现有申请人 Schema 没有这两个条件，现有材料模块又固定为东科大五项。
本任务提供可重复运行的本地条件预览：两项都是是，则条件满足；任一明确为否，则条件不满足；
否则提示信息不足。空白不能当作否，条件不满足不能直接解释成免交。
同一计算核心服务东科大旧规则和新材料条件。网页、正式报告、生产资格判断本轮不变。

## 范围与非目标

包含：小型共享谓词核心、附加请求/预览 Schema、严格 policy/pin 加载、纯内存评估函数和
`python -m` 本地预览命令、定向兼容性/负例/九宫格验证和简短操作文档。
可以修改 `reasoning/applicability.py` 中两个私有函数的委托；保留旧接口/模型/枚举/行为。
不修改 ApplicantProfile 1.0、五项 ApplicationMaterialsPolicy、旧 report/evidence/decision 格式。
不扩展旧白名单来偷偷接受新 profile 字段，不把任意 dict 冒充旧 ApplicantProfile。

非目标：官方材料结论、多源报告执行、候选 KB scope/section 晋级、PDF/KB读写、解析、索引、
corpus、API/UI、自然语言助手、新下载或付费。不得调用已耗尽额度的 IMPORT-01 命令。
不做通用 DSL、动态字段访问器、学校插件体系或按学校名选择规则的 if 分支。

## 共享逻辑契约

当前 `_predicate_status` 负责九种已校验比较；`_combine_predicates` 负责 ALL/ANY 三态组合。
把这两部分算法放到一个无 I/O 的公共核心，使旧入口和新入口都调用它，不复制一套。
核心可使用 bool / None 表示比较结果，再由旧包装转换为原 ApplicabilityStatus；
原字段取值/类型检查/日期归一化/作用域/证据绑定仍留在旧包装，枚举和旧导入路径保持。
核心拒绝未知运算符。旧有空集合 ALL=true / ANY=false 等边缘行为必须保留。
不得根据文本、模型输出或学校名称生成 predicate。

新政策的可执行字段仅两项：
`employment.currently_employed_in_organization` 和 `employment.retain_employment_at_enrollment`。
允许 equals/not_equals，expected_value 必须 strict bool；禁止 null 预期值、其他路径/操作符、
重复 predicate 或同一 ALL 内互相矛盾的条件。无条件条目为 ALL + 空 predicates，条件为 true。
其中“单位”指企业、官公庁、团体等；不能把职业名称、留学生身份或当前未填写工作单位推成布尔值。

## 新请求：MaterialConditionRequest 1.0

独立 Schema，extra=forbid；不改变既有 ApplicantProfile canonical bytes：

| 字段 | 类型/语义 |
| --- | --- |
| schema_version | 字符串 1.0 |
| target | 完整 EVID-01 Target：学校、研究科、项目、学位、年度、路线、日程、入学时间及 target_id |
| applicant_profile | 原 ApplicantProfile 1.0，按既有 loader/model 重新验证 |
| employment | null 或包含下面两个键的严格对象；对象内键可省略为 null |
| employment.currently_employed_in_organization | true/false/null |
| employment.retain_employment_at_enrollment | true/false/null |

字符串 true/false、0/1、其他键均不接受。就业值是申请人自报事实，不声称由学校核实。
null 对象等同两字段 null；与 false 不同。统一规范化后才能计算 request digest。
完整 target 必须显式提供；缺字段为 invalid_request/needs_selection，不猜最近年份或院系。
保留字段缺失和目标不支持的区别；未知问题不自动启动问答模型。

## 目标与旧 profile 冲突检查

先按政策完整 target 全字段匹配；不匹配返回 status=not_covered，entries=[]，不评估条件。
target 完整匹配后检查旧 profile 中已填写的重叠字段：学位、入学年/月、研究科、项目、路线。
master 与 master 对应；其他学位按 MS-01 显式映射，不能字符串相似匹配。
旧 profile 的空字段不补造申请人事实；显式 target 为本次选择权威。
已填写的研究科/项目/路线必须属于 policy 内对应字段的精确 alias 集（含 canonical ID）；
不做翻译、模糊匹配、大小写推断或自由文本分词。日期/学位冲突或 alias 不匹配返回
status=target_mismatch、entries=[] 和 sorted conflict_fields。另一机构同名不得通过 target gate。
这只是新 envelope 的行为，旧 ISCT profile/服务处理不变。

## 已审核政策数据及信任

[政策](material-condition-policy-v1.json) 记录三个 topic、完整 target、input/policy revision、
alias 集、共享逻辑版本、条件、未来 effect/stage 与 evidence prerequisites。
exact-byte SHA-256 在配套 trust 文件固定，生产命令只从显式 operator 信任路径加载；
不能根据本次输入自动生成 pin。测试用其他机构显式合成信任数据，不改算法或正式 pin。
source/Fact 绑定来自已接受的 IMPORT-01 记录，只作未来证据审查前提，不当成本轮已经完成运行时验证。

[信任文件](material-condition-trust-v1.json) 固定 policy_id/revision/sha256，政策 SHA-256 为
`3a43af563ebb66840fa804a186779553b451b7474033fbc824f34398ebcf0bb8`。
实现须以该 JSON 的字段形状定义严格模型：schema_version/artifact_role/production_enabled/
authority/review_status/policy_id/revision/condition_logic_version/target/profile_target_aliases/
evidence_prerequisites/rules 均必需；不能将政策大段内容存成不校验的任意 dict。
version=1.0、condition_logic_version=1、production_enabled=false、authority=condition_only、
review_status=design_reviewed_not_activated 为固定值。规则 stage 本轮仅 application，
proposed_effect_when_matched 仅 required/not_required，均不进入 preview。
evidence_prerequisites.runtime_evidence_verified 必须是严格 false；各 document identity 和
required_binding 复用现有 DocumentIdentity/OfficialEvidenceBinding 做结构校验；文档、hash、
record/Fact引用互相一致且无重复，不要求或允许本轮读取 KB 来冒充运行时审核。
policy 条目数量可变，不硬编码三个主题；本版本正式数据恰好三个。alias 集不允许空值/重复项。

| topic / material | 条件 | 未来已审核语义（本轮不输出为招生结论） | 必需审核记录 |
| --- | --- | --- | --- |
| english-score-sheets / english_score_sheet | exact target 下无附加个人条件 | score-sheet submission not_required；不表示英语考试免除 | E01,E02,E03 |
| checklist-submission / checklist_form | exact target 下无附加个人条件 | checklist 本表 not_required；不是清单内所有材料都免交，仍需参照核对 | E04,E05 |
| work-study-plan / work_study_plan | 两就业字段 equals true，ALL | application 阶段需要计划书；线上 PDF 上传，必须带 E08 表头/对象上下文 | E06,E07,E08 |

E07 只保留为“入学手续阶段另有单位同意书”的关联 context；不得把它并成出愿时必交项。
其引向共通要项11.(8)的全文尚未进本切片，正式单位同意书规则不在本政策执行范围。
政策中每项 condition_rule_id 唯一，topic/material 唯一；显示顺序由 policy 显式给出。
后续正式规则需要重新审核完整 evidence 和 scope；本轮不能通过 effect 字段直接发出建议。

## 预览结果：MaterialConditionPreview 1.0

严格输出包含 schema_version=1.0、artifact_role=material-condition-preview、production_enabled=false、
authority=condition_only、policy_id/revision/sha256、request_sha256、target、status、conflict_fields、entries。
status 为 evaluated / not_covered / target_mismatch；语法/pin错误直接失败，不返回半份 preview。
entries 顺序与 policy 相同，每项仅 condition_rule_id、topic_id、material_code、condition_status、
predicate_outcomes、missing_fields。禁止 action/required/not_required 结论、官方引用或 LLM总结。
condition_status 为 matched / not_matched / needs_information；predicate_outcomes 保留
field_path/operator/status，不复制个人信息或伪造“官方已确认”。missing_fields 是未知参与字段的有序集合。
false+unknown 时总体 not_matched，但仍可列出未知字段，不强制用户为已排除条件补信息。
结果 loader 重新从绑定 policy/request 计算并验证，不能只接收自报的 matched 或任意 request hash。
canonical JSON 沿用 UTF-8、sorted keys、紧凑分隔、末尾 LF；禁重复键/非有限数/额外字段。

| 目前在职 | 保持在职入学 | 工作计划条件 |
| --- | --- | --- |
| true | true | matched |
| true | false | not_matched |
| false | true | not_matched |
| false | false | not_matched |
| true | null | needs_information |
| null | true | needs_information |
| false | null | not_matched |
| null | false | not_matched |
| null | null | needs_information |

false/true 不自动修正成 true/true；它只不满足“当前在职”条件。没有政策依据不得补出矛盾诊断。
英语/清单条目在 exact target 下均 matched，与就业字段无关；matched 绝不等于 required。

## 验收、真实依据与资源

1. 同一底层比较/组合实现服务旧 applicability 和新条件工具；证明旧函数返回/序列化不变。
   覆盖原九操作符、ALL/ANY/unknown/空集合和日期/集合边界，现有 applicability/rule resolution/
   interaction/application materials/report/profile 测试通过。不得仅测自己重写的同一逻辑。
2. 九组就业组合、null对象/省略键、unconditional条目、target各维错配、profile冲突/空字段、
   重复/矛盾规则、改pin、0/1字符串bool、伪造结果均有负例。输入顺序不能改变 canonical输出。
3. 使用版控的真实 GSFS政策及seed/身份绑定生成三份操作预览：就业 true/true、false/null、null/null。
   这些是合成申请人，不是真实用户；逐条验证preview无官方action/引用，缺失信息不会误判。
   再用一个不同学校的合成 policy/target 验证通用算法和跨学校隔离。
4. 报告完整命令/head/policy/request/output hashes、共享逻辑改动范围、旧序列化对照、覆盖矩阵、
   测试与限制。小型申请人fixture/preview可提交；不包含用户真实资料。
5. 正常 CI/冻结门禁通过。不得为新命令修改 pyproject（使用 python -m）；不刷新任何冻结指纹/
   gold/policy来掩盖失败。若事实证明必须影响冻结契约，回到设计，不自行扩大范围。

这是零 PDF/KB/索引/模型读取、零解析/构建/网络/付费任务。只读取版控小型 JSON及合成输入。
IMPORT-01 4/4额度不恢复，也不授权重跑其验证函数。预览最多三次实证命令（每命令可批量固定
三场景），开发最多两次、设计留一次；同一最终字节输入复用已有输出，不按milestone复制。
每次60秒、累计3分钟、单份JSON256KiB；由命令或外部runner执行超时控制，记录累计次数。
纯函数/合成单测不占实证命令次数。无新模型、内存密集任务或驻留服务。

上述资产禁令针对真实来源、既有候选及运行资产；旧兼容性测试所需的小型合成 fixture
可以在测试临时目录读写，不得借此加载真实 PDF/KB/index 或运行其构建。不要默认跑带真实资产
fixture 的全量套件来补充本次证据。

[固定合成场景](material-condition-examples-v1.json) 已通过现有 ApplicantProfile 1.0 校验，
不是用户真实资料。命令可重复传入 --request，每个值是一份 Request JSON 文件，
一次读取完并验证全部输入后再输出 JSONL（每行一个 canonical preview），任一失败不输出部分结果。
这使一次实证命令可覆盖三场景，无需额外队列或批处理框架；不得将示例里的 expected 值作为计算输入。

## 交接、失败与回滚

沿用 M15 Main，一个 Issue / PR。先共享核心与旧行为对照，再新契约/九宫格/三场景预览；
超过两个专注开发日或触及旧Schema不兼容、证据门禁放宽、候选资产写入即回交设计拆分。
PR给出 branch/head、已完验证、额度、产物、未完事项和下一责任方；不要自行开启报告/UI。
失败在原 Issue/PR 更新交接；保留原始错误，不改未知为false、不靠学校字符串特判修测试。
回滚撤回新模块/契约及旧函数委托，不涉及任何数据迁移。下一步是正式scope/evidence与
多源报告设计；本任务验收不授权将 condition preview 展示为招生建议。
