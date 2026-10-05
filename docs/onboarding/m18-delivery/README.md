# M18 可复用资料接入与展示交付包

> 2026-10-05 独立设计验收更新：#289 已验收合并，M18成果完成。见[最终验收及设计证据](../m18-design-acceptance.md)。下方 Awaiting review 和设计预留未用等文字是开发交付时记录；当前设计累计服务1/1、POST2/2，不能重复运行真实预览命令。

唯一执行任务 [#285](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/285)。
在原两校四步页中复用已审核东大 v2 四主题：小论文、带就业条件的在职计划书、跨文件英语说明、检查表。真实目标固定为複雑理工／2027 修士／一般普通选拔 A／2027 年 4 月历史切片。

这里交付的是“已审资料 → 展示与报告”的可重现路径。生成不会审核翻译、授予新官方可信状态、创建 pin、发布候选或触发 KB/向量构建。小论文模板细目和精确截止时刻仍未知。其他主题没有新增准备自报。

## 文件与输入归属

| 信息 | 唯一维护来源 | 消费者 |
| --- | --- | --- |
| 小论文中文名、指南、逐字段 claims | 原只读 `author01-essay-authoring-input.json` | 生成目录 → 材料卡、原文说明、报告复制 |
| v2 旧三主题名、日文名、短用途 | `m18-migrated-material-displays.json` | 从 main `8aa4e812` 一次搬移的原文案；没有补写指南 |
| 指南字段 → claim 引用 | `m18-presentation-build.json` 的 `guide_bindings` | 完整片段引用检查；自报提示单独标为产品说明 |
| 学校/年度/批次/路线/快照/来源/Fact | 原 v2 seed、plan、policy、trust、候选与 PDF | 原完整 loader 派生，运行时再次逐目标、逐来源、逐片段核验 |
| 条件结果、例外、跨文件关系 | 原 policy/plan | 原服务器计算，展示目录不作招生判断 |
| 个人准备状态 | 本页三态自报 | 通用控件、摘要、预览及复制，不改变官方结论 |
| 本机路径 | 生成的本地 preview config | 仅启动配置，不进入资料或展示内容身份 |

生成物位于 `src/jgrad_admission_rag/service/static/reviewed-material-presentation.mjs`、同名 `.manifest.json`、`.sources.json`。只包含 JSON 安全序列化数据与固定 export；不要手改。页面加载失败会提示刷新，错误身份/缺上下文拒绝显示错误指南。

## 三个操作入口

以下命令在专属 worktree 执行，使用现有环境，不安装或下载依赖。开发机原资产保持 `D:\J-Grad-Admission-RAG`；设计可在自己的 checkout 执行相同命令，PDF、候选、模型和索引仍用原路径。

```powershell
cd D:\J-Grad-Admission-RAG\outputs\m18-worktree
$env:PYTHONPATH = "$PWD\src"
$m18Python = 'D:\J-Grad-Admission-RAG\.venv\Scripts\python.exe'
$m18Candidate = 'D:\J-Grad-Admission-RAG\outputs\reviewed-source-candidates\7ea490375de4c28859ca38dd76bb3952aa8b3d601aa3ccc9eeb5f4ee93cad752'
$m18Pdfs = 'D:\J-Grad-Admission-RAG\outputs\source-documents\utokyo-gsfs\2027'
```

**生成**：只写明确指定的新展示输出。先读完整受信 loader；不存在、不匹配或漂移的候选不能生成。

```powershell
& $m18Python -m scripts.m18_presentation `
  --descriptor docs/onboarding/m18-presentation-build.json `
  --candidate-root $m18Candidate --pdf-dir $m18Pdfs `
  --output-dir outputs/m18-generated
```

三个生成文件复制到固定 static 位置属于受审核代码交付；本包已提交。后续输入变化会使 manifest/check 失败，需要重生成和语义审核，不会自动改变源、plan 或信任 pin。

**只读校验**：核对当前输入 hash、全部来源/原文绑定及已交付文件。该路径不创建临时配置、不写资产或输出文件，不调用 publish。

```powershell
& $m18Python -m scripts.m18_presentation `
  --descriptor docs/onboarding/m18-presentation-build.json `
  --candidate-root $m18Candidate --pdf-dir $m18Pdfs `
  --output-dir src/jgrad_admission_rag/service/static --check
```

**独立预览**：先生成只含本地路径的 opt-in 配置，尚不启动服务。

```powershell
& $m18Python -m scripts.m18_presentation `
  --descriptor docs/onboarding/m18-presentation-build.json `
  --candidate-root $m18Candidate --pdf-dir $m18Pdfs `
  --preview-config outputs/m18-preview.json
```

已有资产必须具备读取权限；遇到 ACL 错误应取得正常本机读取权限，不能换目录隐式重建。预算沿用 #285，同一共享账本为 `D:\J-Grad-Admission-RAG\outputs\m18-audit\budget.json`；脚本不会从缺账本推定零，也不自动创建/重置它。

```powershell
# 每次实际启动前先查看原 Issue 与账本。开发额度用尽后不能再次运行。
& $m18Python -m scripts.m18_preview `
  --config outputs/m18-preview.json --assets-root D:\J-Grad-Admission-RAG
# 独立设计 Agent 才可在自己的 worktree 使用 --role design：服务1/POST2预留。
```

启动器打印随机空闲 loopback 端口和 `/app/advanced` URL，不改已有在线页。使用原 391 runtime，provider 禁止 embedding/model 调用；所有 POST（失败也算）在执行前记账。停止时对该终端 Ctrl+C，只停止自己的 PID。不要复制或重建大型资产。预算用尽后，用保存响应回放进行修复核验。

## 验证与成果入口

- [完成、证据与缺口](../m18-completion-and-gaps.md)；[维护成本和来源映射](../m18-implementation-review.md)。
- [生成与九组合直接投影账本](../m18-evidence/generation-and-direct-journal.json)、[前后逐字对照](../m18-evidence/before-after-journal.json)。
- [真实浏览器账本](../m18-evidence/live-browser-journal.json)、[真实静态 GET](../m18-evidence/static-http.json)、[累计服务账本](../m18-evidence/resource-ledger.json)。
- [旧三主题回放](../m18-evidence/old-three-replay-journal.json)、[东科大考试回放](../m18-evidence/isct-replay-journal.json)。回放、直接投影、合成和实时 HTTP 分开标注。

```powershell
# 纯生成/直接投影与保存回放；不启动服务、不发实际产品 POST
& $m18Python -m scripts.m18_evidence --prepare
& $m18Python -m scripts.m18_evidence --replay --replay-v2
node scripts/m18_compare_replay.mjs
# 实际服务已经由独立预算启动后，下面这一命令会发3次实际POST；不能重复运行
& $m18Python -m scripts.m18_evidence --live-url http://127.0.0.1:PORT
```

合成新学校/主题/显示名和单处指南编辑验证位于 `tests/test_m18_presentation.py` 与 `tests/test_m18_browser.py`，所有浏览器流量拦截，所有源和 PDF 为隔离合成数据；不冒充新增真实学校覆盖。前端使用原 `app.js`/`unified-core.mjs`，无需新增学校或主题专用分支。无私有资产的 CI 用保存审核响应验证展示漂移，完整 loader 的构建测试使用隔离合成 PDF；不替代真实验收。

## 回滚与剩余边界

回退本 PR 的生成器、目录和展示接入即可恢复原展示；原 v1/v2 配置及服务始终保留，不删除任何候选、PDF、KB 或索引。没有重签 M9、改变 reference_only、API 必填字段或生产 Schema。新真实材料、全校覆盖、年度更新、问答、M13 和 MinerU 均不在本包内。独立设计验收和 M18 关闭仍由设计负责。
