# UX-02 实施与验收证据（#250）

## 复用与必要差异

| 已有资源 | 复用位置 | 本次必要差异 |
| --- | --- | --- |
| main 的两校四步页 `advanced.html`、`app.js`、`app.css` | 目标、基础要求、个人对照、报告、问答和关系窗口均沿用 | 统一字级；缩短内部文案；材料卡显示中文名、日文正式名、用途和不同状态；问答正文安全分段。 |
| `unified-core.mjs` 的目标映射、`legacyReport`、`sliceReport`、`readerReport` | 页面材料卡、个人对照、报告预览和复制 | 以学校身份与原 material code 为键加入 8 项展示解释；未知 code 保留原名并标“说明待核实”。服务端规则、报告选择与证据校验不变。 |
| 已审核 ISCT `fact:00104` 与 GSFS E01–E08 | [材料解释与文案复用表](ux02-material-copy-map.md) | 仅用来核对材料名称和通用用途；适用、提交和准备状态仍取现有响应。 |
| UX-01 保存的真实基础/个人/GSFS 报告响应和 E01–E08 绑定 | [重放脚本](ux02-browser-replay.py) | 同一 JSON 输入分别注入基线 `b0943cc651f5d0b92bfa0226f7583b810e90a29a` 和本版静态页面；浏览器只发路由拦截请求。 |
| QA-01 脱敏历史在线回答 case 03 turn 1 | 问答视觉重放 | 只验证段落、混合语言、默认来源隐藏；这不是当前 main 的在线质量验收，也未复用暂停的 QA Draft 代码。 |

## 保存响应、资产和预算

[重放日志](ux02-evidence/journal.json)记录 4 份保存响应的规范化 SHA-256、基线提交、前后各一次基础/个人/关系/报告/问答的浏览器路由计数。同一保存响应在前后页面未改写。真实服务启动 **0/1**，真实基础/个人 POST **0/4**，GSFS 报告 POST **0/1**，付费调用 **0**。这些计数是浏览器路由拦截，不是实时 HTTP。

[只读资产核对](ux02-evidence/asset-preflight.json)以 UX-01 回滚清单 `outputs/backups/demo-before-usability-20260930/manifest.json` 为准，31/31 项大小与 SHA-256 一致、0 项不符；脚本为 [ux02-asset-preflight.py](ux02-asset-preflight.py)。334/391 和 8003 未写入。

## 前后截图（保存响应重放）

每格是 **基线 → 本版**；1440 为桌面，390 为手机。报告材料截图在原窗口中滚动到清单。ISCT 第三步自报地址标签已准备、申请表尚未准备，其余未填写；第四步仍区分官方适用性与个人准备情况。GSFS 仅显示 3 个历史材料主题和缺日期范围提示。

| 视图 | 桌面 1440 | 手机 390 |
| --- | --- | --- |
| 选目标 | [前](ux02-evidence/before-step1-1440.png) → [后](ux02-evidence/after-step1-1440.png) | [前](ux02-evidence/before-step1-390.png) → [后](ux02-evidence/after-step1-390.png) |
| 基础要求 | [前](ux02-evidence/before-step2-1440.png) → [后](ux02-evidence/after-step2-1440.png) | [前](ux02-evidence/before-step2-390.png) → [后](ux02-evidence/after-step2-390.png) |
| 个人情况 | [前](ux02-evidence/before-step3-1440.png) → [后](ux02-evidence/after-step3-1440.png) | [前](ux02-evidence/before-step3-390.png) → [后](ux02-evidence/after-step3-390.png) |
| 个人对照 | [前](ux02-evidence/before-step4-1440.png) → [后](ux02-evidence/after-step4-1440.png) | [前](ux02-evidence/before-step4-390.png) → [后](ux02-evidence/after-step4-390.png) |
| 报告窗口 | [前](ux02-evidence/before-report-1440.png) → [后](ux02-evidence/after-report-1440.png) | [前](ux02-evidence/before-report-390.png) → [后](ux02-evidence/after-report-390.png) |
| 报告材料清单 | [前](ux02-evidence/before-report-materials-1440.png) → [后](ux02-evidence/after-report-materials-1440.png) | [前](ux02-evidence/before-report-materials-390.png) → [后](ux02-evidence/after-report-materials-390.png) |
| 历史在线回答布局 | [前](ux02-evidence/before-answer-1440.png) → [后](ux02-evidence/after-answer-1440.png) | [前](ux02-evidence/before-answer-390.png) → [后](ux02-evidence/after-answer-390.png) |
| GSFS 基础材料 | [前](ux02-evidence/before-gsfs-step2-1440.png) → [后](ux02-evidence/after-gsfs-step2-1440.png) | [前](ux02-evidence/before-gsfs-step2-390.png) → [后](ux02-evidence/after-gsfs-step2-390.png) |
| GSFS 报告窗口 | [前](ux02-evidence/before-gsfs-report-1440.png) → [后](ux02-evidence/after-gsfs-report-1440.png) | [前](ux02-evidence/before-gsfs-report-390.png) → [后](ux02-evidence/after-gsfs-report-390.png) |
| GSFS 报告材料 | [前](ux02-evidence/before-gsfs-report-materials-1440.png) → [后](ux02-evidence/after-gsfs-report-materials-1440.png) | [前](ux02-evidence/before-gsfs-report-materials-390.png) → [后](ux02-evidence/after-gsfs-report-materials-390.png) |

ISCT 报告复制文本：[前](ux02-evidence/before-report-copy.txt) → [后](ux02-evidence/after-report-copy.txt)。GSFS 报告复制文本：[前](ux02-evidence/before-gsfs-report-copy.txt) → [后](ux02-evidence/after-gsfs-report-copy.txt)。重放断言五项 ISCT、三项 GSFS 的易懂名同时出现在本版预览与复制中；日期单选没有材料准备结论、完整的报告主题选择和复制一致性由现有浏览器测试覆盖。

## 验证

- `node --test tests/unified_core.test.mjs`：6/6 通过，覆盖 8 项学校限定映射、未知回退、准备/待准备/未填、GSFS 条件与不适用。
- `python -m pytest -q --tb=line -p no:cacheprovider --basetemp=<隔离目录>`：**1829 通过、303 跳过**。其中浏览器合成测试覆盖离线、503 失败、无安全结果、未覆盖分项和恶意 HTML；无脚本执行。
- `ux02-browser-replay.py`：前后两校截图与复制文本完成，页面 JS 无错误、390px 无水平溢出；换校清除旧问答，关系窗口打开/返回/关闭可用。历史在线回答只用于布局。
- `ruff check --no-cache`、`ruff format --check --no-cache`、`node --check`、`git diff --check`：随本 PR 的最终检查记录；打包测试在隔离临时目录通过。

线上问答质量属于暂停的 QA #233/#236，本 Issue 不作恢复声明；本次仅调整当前 main 页面展示。等待设计 Agent 独立验收后再决定合并。

## PR #252 第一轮审查后的增量修正

- 材料解释表按已验证 scope 的资料身份声明：ISCT 同时匹配 `school_id` 与 `document_id`；GSFS 同时匹配机构、研究科、专攻和 `snapshot_id`。页面材料卡、第三步表单、第四步个人对照与报告投影传递同一个 scope。纯函数反例覆盖同 kind/同 code 但异校、异文档、异快照、未知身份和未知 code；合成浏览器检查异校表单及卡片回退，报告投影单元测试检查同 code 复制回退，浏览器再核对未知材料的预览与复制一致。
- 保存真实响应的[第四步手机截图](ux02-evidence/after-step4-390.png)与[桌面截图](ux02-evidence/after-step4-1440.png)已刷新：原始响应中的人工审核 checklist 句不再直接作为正文输出；部分覆盖含义仍可见。未配置 `online_model` 且后台 label 含供应商品牌的[合成手机截图](ux02-evidence/review-unconfigured-synthetic-390.png)显示“在线问答暂不可用”，正文不含品牌。浏览器测试继续区分成功、离线、失败。
- 增量检查：直接相关的 Python 浏览器/UI 测试 **16 通过**，Node 投影 **6 通过**；Ruff 全仓格式/静态检查、JS 语法及 Git 空白检查通过。这是原 PR 的增量验证；保存响应与受保护资产未修改，无真实服务、模型或付费调用。原 40 张前后视图由同一重放脚本刷新，另增 1 张明确标为合成的未配置状态截图。
