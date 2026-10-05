# M19 开发成果包：审核输入到五主题配置

执行 Issue：[#291](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/291)。开发基线 main `ae93db63b37732ebb5ef4fe6edcbb81ee9bf33fa`；设计 PR #292。本包等待长期设计 Agent 独立验收，生成成功不是独立语义审核，也不授权生产启用。

本包把东大 CBMS／2027 修士一般选拔 A／2027 年 4 月历史切片的**报考志愿调查表**接入原两校四步页。新配置五主题；小论文与调查表分别自报准备状态。官方需提交与个人已准备始终分开。英文成绩单、检查表和在职计划书保持既有规则。不是完整材料清单、东大全系、导师推荐或资格判断。

## A：人工输入与机械派生

| 字段 | 原维护位置 | 本包唯一人工维护源 | 机械生成去向 | 仍需人工语义审核 |
| --- | --- | --- | --- | --- |
| 日文原文、表头归属、页码、上下文 | seed，另手工抄 Fact/bindings | 设计 v3 seed E11/E12 | 原 mapper 的 Fact/Unit/lineage，policy/plan 的完整 bindings，原文窗口 | 原页与条款归属，不能由生成器推断 |
| 中文/日文名称 | 作者、plan、展示映射、控件名 | author.claims.material_name | plan 名称，目录卡片、控件、报告 | 名称及其片段引用 |
| 完整目标与来源集 | author、import、policy、plan | 外部批准锁定的 author/seed 与已审文档身份 | import 目标、policy、plan、scope、snapshot | 学校、年度、批次、路线和入学期 |
| 提交条件与阶段 | 作者规则投影、policy、plan | author.condition 及 audience/stage claims | 原 `mode=all/predicates=[]/required` 条件与出愿阶段 | 显式有限模板的含义与全部依据 |
| 中文正文 | 作者、plan 总结、展示说明 | reader.summary.text | plan.matched_explanation_zh 与 guide.purpose/卡片说明 | 中文解释和 claims 引用 |
| 准备步骤 | 作者、展示、报告 | reader.steps | 原 M18 guide.steps，页面和复制报告 | 内容、顺序和逐步骤引用 |
| 注意点与未知 | 作者、plan 注记、展示 | reader.notes/unknowns | 固定顺序组成 plan.context_note_zh；guide.warnings/报告；未知值保留 null | 未知边界和个人记录说明 |
| 文件关系 | seed、plan、关系窗口 | seed.relations | plan 和已有关系窗口 | supplements 关系，不是“专攻总覆盖共通” |
| 自报控件 | 曾需要材料专用名称/状态副本 | author.control | 原 M18 通用三态控件，page-local preparation | 产品含义：不证明上传、受理或资格 |
| hash、候选 ID、snapshot、trust | 多处手工对应 | 无需手填，均由已批准输入派生 | import/policy/plan-trust、manifest、静态目录 | 最终新 trust 与实现由设计在 PR 独立复核 |

仍保留一份已审旧四主题 policy/plan 作为语义基底；本包不批量迁移历史解释。既有三主题展示名称仍来自已验收 M18 迁移文件，旧小论文仍用原 author 文件。新增生成器不从学校 ID、topic ID 或中文材料名分支决定招生结论。另一个合成学校/材料也通过同一入口。

## B：生成合同与身份

入口 [`scripts/m19_configs.py`](../../scripts/m19_configs.py) 先校验外部设计批准、精确 author/seed/base_inputs hash、source pin、完整目标、全部上下文、claim 引用和有限模板，再调用原 `reviewed_fragment_import` 纯 mapper。policy、plan 的旧来源按 lineage 的 record/fragment/fact 重新绑定；旧四条业务规则和旧四个 plan topic 保持。不是全局字符串替换。

生成器复用 `load_plan/verify_evidence_bytes` 完整审核器；发布后再调用原磁盘 reference loader。候选不作为自签信任来源。新 `*-trust.json` 是隔离开发用精确绑定，等待独立 PR 验收。设计批准 JSON、旧 trust 与 M9 指纹没有修改。

- 唯一候选：`d54514a43da772bec2609b364b3e3497d02c9b6388c85712a502c746b5ffbaca`，124,539 bytes。共通 2、专攻案内 22、追加表 27 个 Fact/Unit，共 51。
- 新 snapshot：`4237c6f910448b2223e40b2f64ad0e9ee2de1e37bcc6c16596368d9879afa942`。
- 摘录 bundle revision 3；PDF 与来源集 s1 revision 1 不变。原 10 记录/37 片段/6 关系保持；新增 2 记录/14 片段/1 关系。
- 生成配置目录约 161 KiB，包含 import、policy、plan、精确 trust、seed、逐字段来源表、差异表、manifest 和展示模块；本地路径不进入身份。两处小型配置工作目录和重复生成逐字一致。
- [逐字段及 lineage 绑定](m19-generated/sources.json)、[精确差异范围](m19-generated/differences.json)、[输入/工具/产物 manifest](m19-generated/manifest.json)。表中的 `old_rules_unchanged_except_bindings` 与 `old_topics_unchanged` 同时有逐字段测试验证；没有泛化忽略所有差异。
- 小论文的适配记录保存原 author hash/原 seed 引用和新的派生 seed 引用，并先验证原 E09/E10 逐字不变。原作者文件未“升级”。
- 输出先完整计算和验证再写。新目录用 staging 发布；显式生成目录刷新期间标记 `incomplete.json`，check/preview-config 拒绝不完整/多余文件。check 全程只读，输出任一字段漂移均拒绝。

## C：运行入口

在本 PR 的源码工作区运行；复用原 `.venv`，不安装/下载新依赖，不复制 PDF、runtime、模型或候选。

```powershell
$env:PYTHONPATH = 'src'
$python = 'D:/J-Grad-Admission-RAG/.venv/Scripts/python.exe'
$pdfs = 'D:/J-Grad-Admission-RAG/outputs/source-documents/utokyo-gsfs/2027'
$store = 'D:/J-Grad-Admission-RAG/outputs/reviewed-source-candidates'

& $python -B -m scripts.m19_configs generate --output docs/onboarding/m19-generated --pdf-dir $pdfs --static-dir src/jgrad_admission_rag/service/static
& $python -B -m scripts.m19_configs check --output docs/onboarding/m19-generated --pdf-dir $pdfs --static-dir src/jgrad_admission_rag/service/static
# 发布入口显式调用；已有同 build 只读复用，不发布第二份。
& $python -B -m scripts.m19_configs publish --output docs/onboarding/m19-generated --pdf-dir $pdfs --candidate-store $store
& $python -B -m scripts.m19_configs preview-config --output docs/onboarding/m19-generated --pdf-dir $pdfs --candidate-store $store --preview-path D:/J-Grad-Admission-RAG/outputs/m19-audit/preview.json
```

这个 preview config 只选新 v3 一个东大目标，不把 v1/v2/v3 三个同名目标并列给用户猜。实际开发取证服务由以下显式命令启动，随机独立端口，打印地址。它复用原 391 runtime，禁止 embedding/query/generation 模型调用；共享账本先记启动和 POST，失败也计数。开发已启动 1 次；设计应使用自己的独立取证入口与预留额度，不能通过此开发入口记入设计额度。

```powershell
& $python -B -m scripts.m19_preview --config D:/J-Grad-Admission-RAG/outputs/m19-audit/preview.json --assets-root D:/J-Grad-Admission-RAG
```

不要运行已经耗尽配额的旧 M18 preview 启动器。原 M18 生成命令和 read-only check 仍可执行：`python -m scripts.m18_presentation --descriptor docs/onboarding/m18-presentation-build.json --candidate-root <原v2候选> --pdf-dir <原PDF目录> --output-dir src/jgrad_admission_rag/service/static --check`。

前端保留旧生成模块，新增模块由通用 `material-presentation-catalog.mjs` 聚合；每个 snapshot 完整目标只命中一个条目，重复身份拒绝。`reference_app.py` 仅增加两条静态 GET 路由；`service/app.py`、生产 Schema/API、规则/报告引擎和 `pyproject.toml` 均未改变。本包入口依赖源码工作区，沿用既有 M18 的打包边界。

## D：证据与验证

**真实隔离 HTTP**：开发服务 1 次、两份报告 POST 各 200；所有静态目录模块 GET 200。完整 JSON 请求/响应、GET headers/hash、报告及剪贴板内容保存在 [m19-evidence](m19-evidence/live-browser-journal.json)。服务已停止，取证端口 53550 已关闭；原用户 8000 服务仍为 PID 34116，未切页面。

- [桌面调查表指南](m19-evidence/desktop-application-questionnaire-guide.png)、[手机指南](m19-evidence/mobile-application-questionnaire-guide.png)。展开正文和四步骤均来自 reader。
- [桌面两来源关系](m19-evidence/desktop-application-questionnaire-relations.png)、[手机 E11](m19-evidence/mobile-E11-source.png)、[手机 E12](m19-evidence/mobile-E12-source.png)：两份原文全部 14 片段及关系往返、焦点归还检查通过。
- [桌面复制文本](m19-evidence/desktop-copy-available-not_yet.txt)、[手机复制文本](m19-evidence/mobile-copy-not_yet-available.txt)。两个控件交叉准备/未准备/未知，互不串值；修改会隐藏旧结果；缓存复用不增加真实 POST；换学校清空两个自报和旧报告。
- 五主题报告完整身份一致。只开放本切片实际可用的“材料与待办”类别；取消唯一类别时禁止复制空报告，不泄漏旧文本。Node 覆盖了该约束及自报不改变官方需提交结果。

**真实来源直接投影（非 HTTP）**：[九种在职组合与三次生成](m19-evidence/reproducibility.json) 验证 null 不转 false，调查表/小论文始终本范围需交，英语/检查表不新增提交义务。[候选复用证据](m19-evidence/candidate-reuse.json) 记录同身份复用前后 hash/大小/mtime 逐字不变，没有第二物理候选或新索引。

**保存响应回放（零真实 POST）**：旧 v1 三主题×三种条件×桌面/手机，[旧 v2 四主题指南及复制文本](m19-evidence/legacy-v2/v2-replay-browser-journal.json)，[ISCT 考试](m19-evidence/isct-replay-journal.json) 与 [ISCT 材料报告](m19-evidence/isct-materials-replay-journal.json)。实际基础响应复用既有保存文件；考试沿用已验收覆盖层，不冒充新 HTTP/新官方来源核验。

**隔离合成与负例**：新学校/材料标识无需生成器或前端专用分支；单处 reader 步骤修改同步桌面/手机与复制报告；一个合成名称字段同步 plan/卡片/控件/报告。测试批准明确 synthetic，限 tests 路径。真实批准/作者/seed 文件不改。无批准、hash 失配、旧基底漂移、缺表头/错引用、错误阶段、不支持模板、跨学校/年度/路线/批次/入学期、candidate/lineage/snapshot 漂移均拒绝肯定结果。

本地正常离线集最终运行 1,936 passed、317 skipped、2 deselected（模型和私有 PDF 等 opt-in 边界）；随后新增的已提交生成目录漂移测试与其余 25 项生成器测试均通过。全部 21 项 Node 测试通过。全仓 lint/format、两项 M9 冻结 gate 均通过；精确最终 head 与 GitHub CI 由唯一 PR 和 #291/#191 同一交接登记，避免文档包含自己的循环 commit hash。

[50 个原路径资产 before/after](m19-evidence/protected-after.json) 的 hash/大小/mtime 保持；15 个受保护 tracked 输入保持。另 [冻结设计输入与原 M18 静态模块](m19-evidence/frozen-inputs.json) 逐字核验通过。334/391、三个 PDF、旧候选、旧 trust、M9 未改。

## 预算、时间与未知

共享累计账本固定 `D:/J-Grad-Admission-RAG/outputs/m19-audit/budget.json`，原 owner/Issue/进程核查依据保留。PR 保存 [账本快照](m19-evidence/budget-snapshot.json)，以共享文件最新值为准，不因换聊天/目录重置。

| 资源 | 本包开发累计 | 上限/设计预留 |
| --- | --- | --- |
| 新真实候选 | 1，124,539 bytes，唯一 ID | 1 / 8 MiB；设计只读 |
| 开发服务启动 | 1，已停止 | 开发 2；设计另留 1 未使用 |
| 产品 POST | 2，均 200 | 开发 10；设计另留 4 未使用 |
| 付费、下载、完整 PDF 解析、向量构建 | 各 0 | 各 0 |
| 纯配置/候选生成耗时 | 成功调用实测约 0.03–0.13 秒，累计见账本 | 单次 60 秒，累计 600 秒 |
| 纯生成峰值 RSS | 118,558,720 bytes（约 113 MiB） | 1 GiB |
| 小型配置输出 | 164,936 bytes；外加部署用同源静态模块仍低于 1 MiB | 1 MiB |

时间不换算为效率百分比。设计预先来源整理/作者输入/人工语义审核耗时未知。开发领取记录为 2026-10-05 17:46 JST；工具等待、编码、排错和连续工作之间无法准确拆分“人工作业”，记未知而不冒充教师可比工时。机器执行和资源计数以日志/账本实测为准。初次默认沙箱 Python 依赖导入停滞、原测试静态路由列表漏模块、合成 entry ID/回放 selector 与 Windows RSS 参数类型等返工均保留记录；均在同包修复，无第二 Issue/PR、服务或候选重建。

已完成范围内无已知产品阻塞；剩余步骤为设计独立复核生成配置/trust、代码和证据。在线表单当前是否开放、完整字段、具体截止日期或时刻未知；小论文模板细目也仍未知。不追加下载验证，不扩大其他材料。来源由设计预先给出，未做盲抽取、年度迁移或同任务人工对照，不能宣称节省比例或全自动扩校。

回退：revert 本 PR 代码/新配置接入并沿用旧 opt-in 配置；保留全部旧资产和新候选供审计。开发不合并、不切用户在线页面、不开始下一材料；#291 保持 Awaiting review，最终验收后才可结项。
