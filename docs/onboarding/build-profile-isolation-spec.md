# BUILD-01：隔离东科大构建规则，建立显式构建入口

执行：[Issue #206](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/206)。
状态：设计合并后唯一 Ready；不是整个 M15 的开发任务。
归属：[M15](https://github.com/yasu-isct/J-Grad-Admission-RAG/milestone/15)，治理 #191。
依赖：#195、#197、#177 收尾及 #202 / PR #204 均已完成。
设计：[ADR 0011](../decisions/0011-explicit-build-profiles-and-reviewed-lineage.md)。

## 背景与可见目标

当前 `build_document_kb` 无论收到哪所学校的 identity，都会调用东科大的院系和适用范围规则。
设计主 Agent 在 main `e46721a` 实测 `build_entities([])` 仍产生 25 个东科大实体。
因此，新学校不能直接复用这个默认入口。

本任务完成后：旧东科大构建结果不变；开发者使用新显式入口时，必须声明采用哪套构建规则。
尝试把东大、其他文档系列或不支持的年度送进东科大 profile，会在解析前明确失败。
本任务不会让网页出现东大，也不会生成东大知识库。

## 范围

1. 把 `builder/kb_builder.py` 中 `COLLEGE_DEPARTMENTS`、相关常量/正则、
   `build_entities`、`infer_scope`、`propagate_department_context` 及其私有辅助逻辑归入
   一个 `legacy-isct-v1` profile 模块，保留原来的顺序、判断和置信度。
2. 通用的 Fact/RetrievalUnit 组装、诊断、源文件哈希校验和序列化继续复用。
   原 helper 导入位置可用薄包装/再导出兼容；不要复制两套规则，也不要更改规则内容。
3. 增加 Python 显式入口，例如
   `build_document_kb_with_profile(pdf_path, identity, *, profile_id, ...)`。
   `profile_id` 无默认值；使用静态已知 profile，不加载任意 Python 路径或外部插件。
   名称和模块布局可由开发 Agent 决定，以下行为是强制契约。
4. 新入口先重新验证 identity 和 profile 兼容性，再做 PDF I/O、哈希校验及旧构建流程。
   `legacy-isct-v1` 只声明当前 `isct` / `isct-master-admission-guidelines` /
   `2027-april-2026-september` 组合；这些值必须与既有 reviewed identity 一致。
   不按学校显示名称猜测 profile，不改写调用方 identity，不把新 profile 失败回退成旧默认。
5. 沿用 `DocumentBuildError` 对外异常家族或其兼容子类；提供可测试、稳定且不泄露路径的
   profile 错误诊断。缺失参数可以是 Python 的明确参数错误；其他无效输入不得进入解析器。
6. 增加聚焦测试、真实数据前后对照记录，以及一段新旧入口的使用与边界说明。

## 兼容性：必须保留，也必须诚实说明

- `build_document_kb(...)` 及旧 CLI、Demo、HTTP/job 路由的参数、错误与输出行为不变。
  旧入口继续是 legacy 兼容包装，包括现有非 ISCT 的合成测试。不得偷偷改成学校推断路由。
- **旧入口仍可能接受其他学校 identity；本任务没有宣称全面禁止这一历史行为。**
  新学校 onboarding/import 必须使用显式入口；新入口不支持 GSFS 时就拒绝。
  不把新显式参数添加到现有 HTTP v1，也不在本任务收紧旧公开接口。
- 旧包装和新显式入口在受支持 ISCT 输入下，必须走同一份实现，输出逐字节一致。
- `extractor.py` / `chunker.py` 中的既有语句、表格和标题规则仍属于 legacy PDF 流程，
  本任务不移动或“通用化”它们。拆出三处 policy 并不代表全链路已成为通用解析器。
- 不为记录 profile 修改 `KnowledgeManifest`、builder/schema version 或旧 Fact metadata；
  本次 profile/code revision 只写入验收记录。现有知识库的规范序列化字节不能变化。

## 非目标

不实现 neutral/GSFS/reviewed-source profile，不创建插件注册平台，不导入 23 段原文，
不改原文 seed、pin、gold，不新建规则/模型/检索器，不修改生产 Schema、API/UI 或学校选择。
不重新运行 MinerU 或 GSFS A/B，不运行全部学校 PDF，不启用完整材料清单、资格或日期判断。
不改 `application_materials.py` 的五项规则；它的可移植性留给后续任务。

## 数据、资产与资源预算

| 项目 | 本任务允许的影响 |
| --- | --- |
| ISCT PDF | 读取现有 `outputs/real_pdf/isct_2027_4_2026_9_master.pdf`，先校验既有 fixture SHA-256 |
| ISCT 构建 | 仅为回归对照，最多一次改前、一次改后离线构建；也可一次提取固定 pages 后供两版共用，但须另证生产入口绑定正确 |
| 临时产物 | 仅保存在同一个忽略的 `outputs/build01/` 中，或在内存比较；保持稳定 `source_pdf_label` 与参数 |
| 334/391 KB/index/runtime | 只读；不覆盖、不迁移、不重嵌入、不切换 pointer，不生成另一份运行目录 |
| GSFS 资料 | 沿用 #202 固定目标/来源身份做拒绝用例；不得解析或构建 GSFS KB |
| 模型、网络与付费 | 无模型加载/embedding、下载、API 调用或云资源；GitHub 正常交付不受影响 |

两次 ISCT 构建是本任务明示的有限回归操作，不是恢复 #177 试点。每次墙钟上限 15 分钟，
单进程执行；超过即停止并报告原因，不自动重试或无限轮询。测试会隐式构建真实 PDF 时，
必须算入上述次数并复用 session fixture；不得测试完再另跑同样的全量构建。
合成单测不计入真实构建次数。正常 CI 依项目 workflow；不用主动增加全量语义/浏览器/付费测试。

## 验收条件

- [ ] 原三处 ISCT policy 只有一份权威实现，旧导入路径保持兼容；通用组装无新增学校专用分支。
- [ ] 新入口没有隐式 profile；未知 profile、不支持 institution/family/edition、无效 identity
  在源 PDF I/O/extraction/输出写入之前失败。用 spy 验证拒绝发生的位置。
- [ ] 真实 GSFS 来源 identity（可构造满足现有 schema 的固定测试输入，清楚标为 guard 夹具，
  不是正式文档 coverage 审核）和另一个虚构学校都不会进入 ISCT profile。
- [ ] 调换文件名、路径或显示名称不能让不支持的结构化 identity 通过；hash 校验仍有效。
- [ ] 改前 main 与改后相同输入、参数、source label 的 ISCT canonical KB bytes 完全一致。
  同时比较旧包装与显式入口；可以在相同固定提取结果上复用构建，不需第三次 PDF 提取。
- [ ] 391 Facts/RetrievalUnits 的 ID、顺序、正文、页码、section path、scope、实体、
  embedding_text、诊断与质量门槛均未变化；不能只比较条目数量。
- [ ] 旧 CLI、Demo 与同步/job 调用链的聚焦测试通过；旧合成测试不通过改 identity 来掩盖兼容破坏。
- [ ] EVID-01 与 MS02 定向回归通过，seed/pin 和 334/391 保护资产哈希未变。
- [ ] PR 明确列出保留的旧入口限制和 extractor/chunker 耦合，不声称已完成多校入库。

## 必须提供的证据

开发 PR 提交短表：改前 main SHA、实现 SHA、profile ID、PDF SHA、构建参数及稳定 source label、
改前/后 canonical KB digest 和结构计数；列出真实构建次数/耗时、保护资产前后 digest。
若 existing runtime 因路径 label 不同与临时 build hash 不同，要说明差异，不改 baseline。
比较对象必须是同条件改前/后结果，不能只拿自己刚产生的结果互相比较。

测试优先选择 `test_kb_builder.py`、`test_embedding_text.py`、新的 profile guards，
以及 CLI/Demo/service build/job 的直接受影响用例；保留 EVID-01、MS02 的定向回归。
真实回归使用上述受控对照，不为了“跑全套”重复解析。不要为未改的网页或向量检索增加测试。
可访问源文件但未执行真实对照时不能报“验收完成”；证据限制要明确回交设计主 Agent。

## 执行与回滚

沿用当前 M15 开发对话，不需要新开一个对话。一个 Issue、一个实现 PR，两个检查点：

1. 先记录改前真实基准，再完成 policy 拆分与 guard 合成测试，报告兼容边界。
2. 受控真实对照、受影响调用链测试与 PR 交接，停止等待独立架构验收。

预计一个专注开发日；超过两个专注开发日、需要改 Schema/公开接口或涉及已有资产写入，
回到设计拆分，不能自行扩大范围。回滚仅撤销新入口/模块和旧包装的委托变更；无数据迁移。
本 Issue 验收后才设计并放行 reviewed excerpt -> KB/Fact/lineage 的下一任务。
本 Spec 不授权后续规则、网页、多校检索或恢复 M13。
