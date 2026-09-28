# IMPORT-01：将审核摘录接入现有 KB / Fact 与证据链

执行：[Issue #209](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/209)。
状态：已在 PR #211 独立验收并合并，#209 完成；真实调用额度4/4已用完，不可重置。
归属：M15；依赖 #202 / PR #204、#206 / PR #208 已验收。
基线：main `cca4efa7f65a19e1c12b7b601048137d9ac6b350`。
依据：[ADR 0011](../decisions/0011-explicit-build-profiles-and-reviewed-lineage.md)。

## 背景、用户目标与范围

目前只能核对三类材料的审核摘录。本任务把八条审核记录的 23 个原文片段分别转入
三份现有 DocumentKnowledgeBase，保留文件、页码、审核来源和必须一起阅读的上下文。
开发者可以用本地命令检查候选记录；申请者网页不变，不生成材料适用结论。

实现一个显式 `reviewed-source-v1` 入口（profile version / mapper version 均为 `1`），
输入为 EVID-01 审核包。复用其严格加载、review pin、来源审核，以及现有
DocumentIdentity 1.0、KB 0.6、ScopedFact、RetrievalUnit、embedding-text v1 和 canonical serializer。
新增候选导入配置、lineage/candidate 严格模型及本地生成/校验/复用命令；不修改生产 Schema。
不能经过旧 PDF builder 兼容入口，不能增加学校名称分支或第二套 Fact/KB 引擎。

非目标：新 PDF/模型、解析实验、整本重建、任何索引、corpus 注册、规则/多源报告、API/UI、
完整资格或材料判断、reference_only 边界变更、M13。不把整个 M15 打包到本 Issue。

## 审核输入与身份

显式提供已有文件路径，不扫描目录/联网。每次真实调用重新验证 EVID-01 的 exact-byte pin、
source manifest、target contract、完整 target、source-set ID/revision、三份 PDF 的 hash/页数。
种子及 pin 不变；seed SHA-256 为
`a5b2bc4e294c52b14c94946886e43928b46fc7f3ff7724ee08a3aa1067aa0b85`。
[身份配置](reviewed-fragment-import-v1.json) 的 exact-byte digest 也必须在导入信任配置中固定；
调用者自报的 digest 不是授权。其他学校未来通过审核配置扩展，不改算法。
本次配置 SHA-256：`49782ecb7bdb0c6e9fcbff230c7150587dc80ab769a2f86286f50eb2aaedb7b1`。

用现有 DocumentIdentity 校验配置，并与来源/契约逐字段核对：document_id=source_id，
family/edition 来自 MS-01，URL/hash 来自 acquisition manifest。未知发布日期/修订日期保持 null，
不能冒用 HTTP Last-Modified。固定试点 target 不等于整份 PDF 的覆盖范围：

| source_id | 整份文档学位 | 覆盖入学时间（含条件分支） | 身份依据，均为物理页 |
| --- | --- | --- | --- |
| gsfs-master-2027 | master | 2026-10、2027-04、2027-10 | 共通 p1 标题、p2 入学時期 |
| complex-guide-2027-revised | master、doctoral | 2026-10、2027-04、2027-10 | 案内 p1 封面、p28/29/30 入学時期 |
| complex-master-a-additional | master | 2026-10、2027-04 | 附表 p1 的修士 A 标题，结合案内 p28 的该日程入学時期 |

这些日期不是对个人的入学许可。附表日期来自同一 source-set 的案内，非附表直接列明。
设计 Agent 在 2026-09-28 复查保留页面图像，未新增解析。混合手册还包含核融合项目；
本轮 target 仍仅 2027 修士普通一般选拔 / A / 2027-04，不启用其他内容。

## 确定性 Fact 映射

每个 fragment 恰好一个 Fact/Unit，禁止拼接、改写、去重或丢弃表头。
输出按 source_id、record_id、fragment_id 字典序排列；lineage 另保留种子片段原序用于阅读。

- Fact ID：`fact:reviewed:<source_id>:<record_id>:r<record_revision>:<fragment_id>`。
  ID 必须唯一，不按循环位置生成；内容变更需要提高审核 revision。
- Unit ID 复用 `fact_to_retrieval_unit`；`fact_type=reviewed_source_fragment`。
- `text` 逐字符等于片段，不二次归一化；`scope_type=unknown`、`scope_targets=[]`、
  `parent_college=null`、`confidence=0.5`（兼容中性占位，不是适用性评分）。
- `source_pages=[physical_page]`；`title="reviewed fragment <fragment_id>"` 为技术标签；
  `section_path=[]`，因为审核输入没有完整官方章节树；`evidence=[]`。
- metadata 仅包含 capture_method、record_id、record_revision、fragment_id、fragment_role、
  source_id、review_record_id、title_kind=technical_label。不复制中文审核说明或虚构 parser/bbox/offset。
- 调现有 `build_embedding_text` 和无解析的 Fact-to-Unit 投影；不加载模型或生成向量。
- 每份 KB `entities=[]`；manifest source_pdf 为 `<source_pdf_sha256>.pdf`，
  builder_version=`reviewed-source-v1.1`，schema_version=`0.6`；不写绝对路径/时间戳。

预期共通 2、案内 12、附表 9 Facts，共 23；同词不同位置保留不同 Fact。
外部引用必须为 `(document_id, kb_sha256, fact_id)`，不能只拿裸 Fact ID 跨文档查找。

## 真实诊断与生产门禁

input/emitted count 为本文件片段数，dropped/merged 为零；上限 6000 字符，超限拒绝而非裁剪。
max/short(<100)/unknown/pages 等指标由实际 Facts 计算。严格拒绝空白片段；经上下文验证的
非空表头有信息价值，不调用旧 PDF heading-only 丢弃规则。本轮 empty/noninformative 为零。
missing_section_path_fact_ids 与 unknown_scope_fact_ids 均包括本文件全部 Fact。
阈值 max_missing_section_paths=0、max_unknown_scope_facts=0，其他沿用默认；复用现有
quality-gate evaluator，每份 KB 均为 **passed=false**，列出这两项真实违规。
结构/lineage 验证通过可以发布隔离候选，不能把它写成生产质量通过。

不调用 PDF reference resolver，其 manifest/diagnostics link/claim/raw occurrence 计数为零；
candidate 明示 pdf_reference_resolution=not_run。这表示未运行，不能声称原文没有引用。
五个已审核关系全部留在 lineage，不伪装成 resolver 的结果。

## Lineage 1.0 契约

新模型拒绝未知字段、重复 JSON key/ID、非有限数和 bool 冒充整数；hash 为完整小写 SHA-256。
canonical JSON 为 UTF-8、ensure_ascii=false、sort_keys=true、separators=(',', ':')、末尾 LF。
KB 使用现有 canonical serializer。lineage.json 必需字段如下：

| 字段 | 内容 |
| --- | --- |
| schema_version / artifact_role / production_enabled | 1.0 / reviewed-fragment-lineage / false |
| build_id | 下节输入描述符 digest |
| bundle | bundle_id、revision、exact-byte sha256 |
| source_manifest_sha256 / target_contract_sha256 / import_config_sha256 | 原始输入字节 digest |
| target / source_set | 完整原样 target、source-set ID/revision |
| documents | 按 document_id 排序；source_id、完整 identity、kb_sha256、fact_count |
| records | 按 record_id 排序；record_id/revision/topic_id/source_id/source_pdf_sha256/physical_page/printed_page_label/manual_anchor/capture_method/review_record_id |
| records[].fragments | 种子原序；fragment_id/role/qualified_fact（document_id、kb_sha256、fact_id） |
| records[].required_fragment_ids | 原样 required_fragment_ids，必须全部存在 |
| relations | 按 (from,kind,to) 排序；原始 from/kind/to；另存 from_facts/to_facts，为端点 record 的完整 required qualified_fact 集，按 required 原序 |

不复制 fragment.text/review_note_zh；原文从绑定 KB 读取，审核说明回到固定 seed。
一一核对全部 records、roles、pages、fragments、required context 和关系端点；拒绝缺失/多余
mapping、错误文档/hash、跨 topic 错链或残缺表格。kind 仅保留审核语义，不推导规则适用性。
提供上下文读取函数：给 record_id 或 qualified Fact，读取 required fragments 及关系相连
端点的完整上下文；正反两个方向遍历，visited 防环，不能缺文件时降级为不完整结果。
操作者按 topic 检查，但不生成新的“应交/免交”判断。

## 构建身份与不可变候选发布

输入描述符固定包含：profile_id/profile_version/mapper_version、bundle_id/revision/sha256、
source_manifest_sha256、target_contract_sha256、import_config_sha256、完整 target/source_set、
按 source_id 排序的三项完整 DocumentIdentity（与 source_id 一一对应），以及
kb_schema_version=0.6、document_identity_schema_version=1.0、embedding_text_version=1、
lineage_schema_version=1.0、candidate_schema_version=1.0。版本均为字符串。
build_id=SHA-256(描述符 canonical JSON)，不含路径/时间/运行次数/milestone/Git SHA。
代码语义变化必须提高 mapper version，不能相同输入身份生成不同字节。

唯一布局为候选根（推荐 `outputs/reviewed-source-candidates`）下：
`<build_id>/documents/<document_id>/document_kb.json` 三份，另加 lineage.json、candidate.json。
同一身份复用原根，不能按 milestone 私自复制。candidate.json 必需字段：
schema_version=1.0、artifact_role=reviewed-kb-candidate、production_enabled=false、
coverage=reviewed_fragments_only、pdf_reference_resolution=not_run、build_id、input_descriptor、
documents（document_id/relative_path/kb_sha256）、lineage_sha256。documents 按 document_id 排序。
只接受固定相对文件名，拒绝 traversal、绝对路径、候选树内 symlink/junction 和清单外文件。
candidate 不自引用 hash；独立报告记录五文件 hash。

先在 sibling 临时目录完成五文件生成和重新加载验证，再原子发布。若目标已存在，校验
可信输入、实际文件 hash、mapping 和重算 canonical 字节；完全一致原路径复用，mtime 不变。
缺失/损坏则失败，不覆盖修复。并发最多一个发布成功，另一个验证一致后复用；不能合并半成品。
命令均需显式 profile/输入，不启动服务/registry。失败不留下可认作完成的 final candidate，
可保留失败临时目录审计，但不自动清理其他产物。

## 兼容性、资产与资源预算

334 冻结、391 产品及 corpus 指针只读；采用 [BUILD-01 正确资产绑定](build01-implementation-review.md#independent-design-review-correct-asset-bindings)。
旧 `outputs/semantic_baseline/isct-master` 是 298，不是 334。不得复制大资产到 worktree。
seed/pin、旧 builder、生产配置/路由不变。解析/embedding/网络/付费预算均为零，
仅允许 EVID-01 的 PDF hash/页数检查；禁止重跑 MinerU 或真实 ISCT build。

开发与独立审核共享最多四次真实候选调用（生成/复用/验证每次计一次，每次最多三份 PDF），
累计真实墙钟十分钟，单次六十秒；开发先生成一次、复用一次，保留两次给设计审核。
纯内存及小合成 fixture 单测不占真实额度。记录命令/head/起止/输入输出 hash/状态/累计余额，
换会话不重置。单次进程 RSS 1 GiB，候选五文件合计 8 MiB；禁止并行真实实验、无限等待。
超限/失败先诊断并回交设计，不改名连续重跑，不默默扩大预算。

## 验收与证据

1. 三份 canonical KB、23 个 Fact/Unit，分配 2/12/9；逐字符核对全部原文，五关系完整闭合。
2. 两次真实调用生成再复用，五文件 byte-identical、mtime 不变，无第二套同身份候选。
3. 正反测试包括错误 profile/类型/pin/PDF hash/缺文件/target/set/revision，缺 header/cell/端点，
   重复/伪造 ID、错 doc/hash/page/role、残缺/损坏候选、traversal、重复/并发发布。
   输入变化改变 build identity；未审核配置仍不能发布。
4. 混合学位不缩窄，scope 不提升，quality gate 如实失败；合成另一机构 fixture 证明无学校分支。
5. 证明未调用 legacy build/extract、网络、模型、registry/report；无索引生成，旧 ISCT 回归通过。
6. 提交小型文本审查报告：pin、完整文档身份、五文件实际路径/hash、23 行映射核对、
   真实预算账本、生产限制和 head；PDF/生成 KB/模型等不提交。
7. focused importer、EVID-01、build-profile、KB serialization、embedding-text tests 及现有 CI。
   不要求无关全量实验；独立验收必须检查真实产物，不能按测试数量批准。

## 交接与回滚

沿用 M15 Main。两个检查点：严格契约/纯映射/负例测试，然后两次有额度真实调用和一个非 Draft PR。
交接写 branch/head、验证、真实预算已用/剩余、路径、未完事项及下一责任方设计；
状态 Ready -> In progress -> Awaiting review -> Changes requested 或 Accepted/merged。
输入不可验证/预算不足时暂停相关动作，在原 Issue/PR 更新同一交接记录。
回滚仅撤回新增 importer/模型/测试/操作文档；候选未进生产 registry，无运行资产迁移。
错误候选保留并标明不可用，不删除覆盖。下一步仍需单独设计 scoped material conditions
及多源报告绑定，本 Issue 不授权其开发。
