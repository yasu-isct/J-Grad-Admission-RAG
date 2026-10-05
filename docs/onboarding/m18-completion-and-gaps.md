# M18 完成与缺口

任务 [#285](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/285)；责任方新 M18 Main；结论 **complete（开发成果包）／Awaiting review（独立设计验收）**。未声明 M18 已获验收或关闭。

branch `codex/m18-reviewed-delivery`；base `8aa4e812f4e8c5e1483161e6c5074d224d67feb3`。真实测试实现 head `501d0dcb7d6fdba9e4566ec97d697ecf17e40db0`；随后补证据/文档并将打包声明移到现有 `MANIFEST.in`，恢复冻结范围内原 `pyproject.toml`。真实运行的前后端及生成器字节不变，[逐文件绑定](m18-evidence/implementation-binding.json)明确列出此打包调整；最终 head 与 Quality CI URL 写在原 Issue 同一交接及非 Draft PR。[最终本地检查](m18-evidence/test-results.json)记录全量结果。

## 完整可运行成果

[统一 README](m18-delivery/README.md)提供生成、只读 `--check`、本地配置与独立 offline 预览入口。复用原完整 loader，从受审核 authoring/seed/plan/policy/trust 和已有候选派生展示目录、manifest、字段引用映射；同一目录在四步页覆盖 v2 全部四主题。小论文指南/身份/原文/控件名从 JS 手抄副本迁出，材料卡、原文说明和报告共用生成数据。原 v1 三主题、东科大材料/18系考试继续原兼容路径。

| 必需成果 | 结论与证据 |
| --- | --- |
| 普通／条件／跨文件／第四主题同一路径 | [四主题前后对照](m18-evidence/before-after-journal.json)：显示名、指南正文和9种报告投影逐字一致；来源提示机械展开完整标题/页码 |
| 身份和完整原文守卫 | 全部37片段、来源ID/标题/URL/页码/role/stage/heading、Fact及原文hash、关系；错学校/年份/路线/批次/snapshot、缺片段、重复topic、hash与产物漂移均有负例 |
| 真实服务和实际模块 GET | [静态GET](m18-evidence/static-http.json) HTTP200，22,017字节，同源CSP/no-store；[浏览器闭环](m18-evidence/live-browser-journal.json)3次实际POST均200，响应与同源直接投影一致 |
| 桌面／手机真实交互 | 四主题、全部37片段原文往返和焦点返回；unknown/available/not_yet、正常修改后重新核对、报告预览与真实clipboard复制、换学校清空；无横向溢出或JS错误 |
| 条件语义 | 实际HTTP真/真、否/未知、未知/未知；[9就业组合直接报告投影](m18-evidence/generation-and-direct-journal.json)补齐其余情况，小论文始终需交，英语/检查表始终无需交，未知不当作否 |
| 旧功能 | [旧三主题3条件×2视口](m18-evidence/old-three-replay-journal.json)、[东科大考试双视口](m18-evidence/isct-replay-journal.json)：全部保存响应回放，0实际POST；原AUTHOR-01修改/核对失败回放也通过 |
| 合成复用 | [桌面](m18-evidence/synthetic-1440-journal.json)/[手机](m18-evidence/synthetic-390-journal.json)：合成不同学校/主题/来源/显示名通过完整loader与同一前端；仅改一处author guide，页面/控件摘要/复制报告同步，无新专用JS分支 |
| 可复现／打包 | 3次生成含另一工作区逐字一致，25,931字节、0.032–0.078秒；`--check`文件mtime不变且检测篡改；离线wheel内静态依赖闭包齐全 |
| 保护资产 | [50原路径文件前后](m18-evidence/protected-after.json)hash/大小/mtime一致，15受保护仓库输入与main一致；334/391、原PDF、旧候选与v2候选94,232字节保持 |

## 样张

改前：[AUTHOR-01桌面卡片](author01-evidence/desktop-essay-card.png)、[手机卡片](author01-evidence/mobile-essay-card.png)。改后：[桌面卡片](m18-evidence/desktop-essay-card.png)、[手机卡片](m18-evidence/mobile-essay-card.png)、[手机下半卡片](m18-evidence/mobile-essay-card-bottom.png)、[桌面报告](m18-evidence/desktop-report.png)、[手机报告](m18-evidence/mobile-report.png)。

同源前后复制文本：[真/真改前](m18-evidence/before-yes-yes-copy.txt)/[改后](m18-evidence/after-yes-yes-copy.txt)，[否/未知改前](m18-evidence/before-no-unknown-copy.txt)/[改后](m18-evidence/after-no-unknown-copy.txt)，[未知/未知改前](m18-evidence/before-unknown-unknown-copy.txt)/[改后](m18-evidence/after-unknown-unknown-copy.txt)。实际clipboard：[桌面未知](m18-evidence/desktop-copy-unknown.txt)、[已准备](m18-evidence/desktop-copy-available.txt)、[待准备](m18-evidence/desktop-copy-not_yet.txt)、[手机待准备](m18-evidence/mobile-copy-not_yet.txt)。

## 累计预算与缺口

[原#285累计账本副本](m18-evidence/resource-ledger.json)：开发服务 **1/1**、实际产品POST **3/4**；设计 **0/1、0/2**预留未借用。自有PID32852于2026-10-05 11:35:27 JST退出，独立端口56333；原在线页/工作区未切换。付费/下载/全PDF解析/新真实候选/KB/向量均0。合成PDF/KB只在测试临时目录，非新真实资产；旧任务预算未重置。

无未完成的开发必需项。仍保留小论文字数、模板版式细目和精确截止时刻未知；仅固定历史四主题，不是完整材料清单、完整普通学生覆盖、全东大或新年度。生成不证明中文翻译正确或授予新可信状态。来源已提前审核，没有盲测或同任务旧流程计时，[实际维护成本](m18-implementation-review.md)不宣称节省比例。独立设计验收仍待完成。

回滚：revert本PR的生成器/静态目录/展示接入即可，不删除任何PDF/候选/索引；不启用新的本地preview配置则原服务行为保持。下一责任方长期设计 Agent 集中验收；本开发不合并PR、不关闭M18、不切换在线页或启动下一里程碑。
