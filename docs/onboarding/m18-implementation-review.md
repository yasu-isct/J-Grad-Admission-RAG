# M18 实现、来源映射与维护成本

基线 main `8aa4e812`；任务 #285；开发源码与真实运行绑定见 [implementation-binding](m18-evidence/implementation-binding.json)。完整运行命令见 [README](m18-delivery/README.md)。

## 复用与完整身份

生成器 `scripts/m18_presentation.py` 通过 `ReferenceWorkspaceConfig` 与原完整 `load_reference_config` 读取：原 v2 seed/plan/policy/trust、候选五文件、三份原PDF。`load_reference_workspace(path)`现在只把文件路径解析成同一配置后委托该函数；校验循环未改。没有发布候选、修改生产Schema/API、下载、embedding或解析流水线。

生成完整target、snapshot、revision和topic/material别名。原文匹配信息含所有37个片段的record/source/page/role/stage/heading、fragment_role、Fact ID、authoritative text hash及逐字引文；关系来自原plan。前端仅按完整身份和完整来源匹配使用指南，JSON对象键顺序不影响字段值比较，数组/片段内容仍严格校验。缺模块会显示刷新提示，不无限loading；没有学校专用降级。

| 真实主题 | 实际来源及原合同 | 生成与消费 |
| --- | --- | --- |
| application-essay／application_essay | author01作者输入；E09/E10共14片段；两份原文互补 | 作者claims派生中文/日文名；guide.what/preparation/attention → purpose/steps/warnings；唯一self_report_tri_state控件 |
| work-study-plan／work_study_plan | E06/E07/E08；两个就业条件同时真才命中，E07为独立入学手续背景 | 只搬已验收名/短用途；原plan/policy提供结论、未知和关系；不新增指南或自报 |
| english-score-sheets／english_score_sheet | E01/E02/E03；共通文件委托专攻确认、本固定范围无需成绩单 | 原跨文件关系与原说明保留；不推出免英语考查或永久优先规则 |
| checklist-submission／checklist_form | E04/E05；参照检查表与提交表不同 | 同一生成目录，原plan保持无需交表本身和部分覆盖限定 |

输入归属与逐指南字段引用见 [build描述](m18-presentation-build.json)、[迁移作者配置](m18-migrated-material-displays.json)、[生成来源映射](../../src/jgrad_admission_rag/service/static/reviewed-material-presentation.sources.json)。旧三主题字段从精确main的 `materialDisplays` v2三元组逐字搬移，不从名称推招生判断。原已审作者输入、plan/policy/trust、候选全部字节不变。

生成模块只固定export JSON数据，安全转义分隔符/HTML字符；manifest绑定真实输入和输出hash、content_id。机器本地路径只写入单独preview config，模板中历史机器路径不参与内容身份；模板标签和实际loader元数据仍hash绑定。另一工作区仅复制小型元数据，真实候选/PDF/模型/索引均不复制。

## 人工维护位置：改前与改后

以下统计是明确代码位置，不是节省比例或净工时。

| 重复维护项 | main改前位置 | 本包改后 |
| --- | --- | --- |
| 小论文完整身份 | unified-core.authorEssayIdentity | 从plan及loader snapshot派生，无手填副本 |
| 小论文中文指南 | author01作者guide＋unified-core.authorEssayGuide | 作者guide一处；模块与页面/原文说明/报告派生 |
| 14段日文原文及source/page分支 | seed＋unified-core.authorEssayFragments/authorEssaySourcesMatch | seed/loader一处；生成记录提供机械完整匹配 |
| v2主题名/短用途和小论文别名 | unified-core.materialDisplays v2 | 旧三项迁移作者配置；小论文claims；别名从plan自动派生 |
| 小论文准备控件主题分支 | app.renderSlicePreparation | 按校验目录循环，程序只认识一个已用控件类型 |
| 小论文控件标签 | app.renderSlicePreparation字面量 | 目录显示名；与卡片/报告同源 |
| 小论文个人摘要标签 | app.updateApplicantStepSummary字面量 | 当前控件数据标签 |

原前端7处内容/材料专用维护位置消除。改后保留作者guide/claims、旧三主题显示配置、字段路径→claim映射三类小型作者资料；完整loader、来源审核、plan/policy作者工作仍存在。没有把规则判断移到显示作者配置，也没有把重复维护转为另一套学校分支。

合成换学校/主题样本实际修改文件类型：隔离源manifest/target contract/seed、import metadata、policy/plan/trust、authoring、preview标签及合成候选/PDF；后者由既有测试mapper机械生成。本M18显示描述和三主题迁移配置原样复用，源JS改动 **0**。全部标识为synthetic，未触及真实候选或信任pin。完成换目标后，第二步仅修改隔离authoring文件 `guide.preparation[0]` 一处；两个视口页面/控件名/报告同步，见 [桌面](m18-evidence/synthetic-1440-journal.json)/[手机](m18-evidence/synthetic-390-journal.json)。这不证明新来源可免审接入。

## 验证类别与测量

| 类别 | 实际测量或证据 | 边界 |
| --- | --- | --- |
| 3次静态生成 | 02:21:44.962–02:21:45.402 UTC记录窗口；单次0.032/0.047/0.078秒，总0.157秒，25,931字节 | 含完整只读来源审计；输出目录不同仍逐字一致；包括第二工作区 |
| 9就业组合直接投影 | 总0.156秒；[逐例](m18-evidence/generation-and-direct-journal.json) | 原snapshot.report直接计算，不是产品HTTP，不调用新规则引擎 |
| 前后样张计算 | 四主题显示一致，三就业条件×三自报状态共9份报告逐字一致 | 精确main旧core与新core同源计算；不是新增真实请求 |
| 真实服务 | 02:34:33.421–02:35:27.746 UTC，共54.326秒 | 包含启动、等待、实际双视口浏览器与停止；不当作纯业务计算时间 |
| 真实HTTP | 静态模块GET200，三次POST均200，全部四主题/37引用 | 真/真、否/未知、未知/未知；[保存原请求响应](m18-evidence/live-browser-journal.json)；其余组合不扩大POST |
| 保存响应回放 | 旧三主题3条件×2视口，东科大考试2视口，v2预检3场景 | 全流量拦截；实际POST0；未验证在线问答 |
| 合成修改 | 完整loader + 新学校/来源/主题；单authoring字段改变content_id、页面和复制报告 | 所有源/PDF为测试合成；不视为真实新增覆盖 |
| 定向检查 | 90项相关Python最终聚焦通过，另18项生成/漂移测试通过；18项Node通过，离线wheel闭包通过 | 重复运行不相加为唯一测试数量；全量结果和最终CI见测试记录/PR |
| 实现与人工排查 | 第一次单独记录时钟02:06:10 UTC；真实服务停止02:35:27 UTC | 这29分17秒仅是可定位工作窗口，起始阅读和前期编码早于它；纯编辑/排查/等待未拆分，不能当总工时 |

返工实际发生在：沙箱ACL读取/写入改用正常本机执行；旧测试合成fixture补全真实provenance；模块资源白名单补齐；合成manifest/contract hash链和source ID顺序重绑；JSON键序比较；复制报告句末标点断言；关系图按record ID而非节点顺序取证；临时目录清理与lint；首次全量测试发现打包修改触及 `pyproject.toml` 的M9冻结hash，随后恢复原文件并通过现有 `MANIFEST.in` 纳入生成资源，未重签清单。均在同包内部处理，没有失败的实际产品POST或额外服务启动。各项纯人工耗时、测试编写时间、早期读取起止、独立设计验收时间未完整计时，明确为未知。

没有盲测或同任务旧流程对照，不能声称节省百分比。已有审核内容复用可运行，但语义审查、新来源准备、候选/plan制作和最终设计验收仍需要人工。

## 资源与回滚

原#285开发服务1/1、POST3/4；设计服务0/1、POST0/2预留；全部禁止资源0，旧预算不重置。服务PID32852已退出；Ctrl+C的Python KeyboardInterrupt退出码1是人工停止，finally已记录stopped_utc，并非启动或产品失败。[前后保护账本](m18-evidence/protected-after.json)核对50文件和15main输入；未修改ACL、生产运行目录、334/391、source PDF、v1/v2信任或M9 pin。前后端/生成器源码真实测试后保持同字节；只调整打包文件，离线wheel重新验证生成资源齐全。

revert本PR即可回退展示接入，保留全部资产和旧配置，不删除候选或索引。独立设计验收通过前不自行合并或关闭M18；新年度/真实材料/普通学生全覆盖/QA/M13/MinerU没有放行。
