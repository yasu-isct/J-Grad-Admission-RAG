# TOOLS-01 #259 实施与验证记录

状态：开发自检中；依赖 PREP-02 PR #262 的精确 head `5dc887846268fbceac8b21db328e381c40d26ab9`，该 PR 尚待设计独立验收。本任务使用独立分支 `codex/tools01-advanced-cleanup`，PR base 指向 PREP-02 分支。

## 旧控件依赖清单

| 旧控件或能力 | 原用途 | 处置 | 原函数与 API 依赖 |
|---|---|---|---|
| `#advanced-tools` 折叠框及文案 | 用户页面进入旧工具 | 移除 DOM、专用样式与学校切换时的显隐代码 | `updateProfileCapability` 中仅服务该 DOM 的语句 |
| `#document-select`、`#evidence-form`、检索结果和 tab | 单文件关键词/向量调试与元数据展示 | 移除 DOM、绑定、初始化及旧检索渲染 | `loadCatalog` → `GET /v1/reviewed-documents`；`submitSearch` → `POST /v1/corpus/query`；保留后端端点 |
| `#report-form`、大量低频字段、旧报告 tab | 底层 ApplicantProfile 输入与详细规则报告 | 移除 DOM、绑定、旧请求构造和旧报告渲染 | `submitReport` → `POST /v1/query-intents/parse`、`POST /v1/applicant-reports`；后台合同和规则保留，低频字段未迁入主页面 |
| `#target-form`、四步目标目录 | 两校、资料身份和入学目标 | 保留 | `loadDemoCatalog` → `GET /v1/reference-targets`，不是旧 `/v1/reviewed-documents` 目录 |
| `#applicant-form`、英语与 PREP-02 字段 | 个人准备对照 | 保留 | `POST /v1/applicant-comparison`，既有 Profile/审核规则 |
| `#grounded-answer-form`、报告、两类依据窗口 | 问答、可选报告、原文和关系图 | 保留 | generation status、问答、基础/个人结果、GSFS slice 报告与证据端点 |

## 页面前后与功能回放

- [回放脚本](tools01-browser-replay.py)与[网络/控制台账本](tools01-evidence/journal.json)在 Edge 以 1440px/390px 重放 8 个前后场景，真实产品服务启动和 POST 均为 0。旧版读取 #258 精确 head 的静态文件；新版读取本分支静态文件。东科大用 #258 保存的真实目标目录、基础要求与个人对照响应；东大用既有合成切片夹具，不能当作新的真实东大响应。
- 同一视口的入口对照：[旧桌面](tools01-evidence/before-isct-1440.png) / [新桌面](tools01-evidence/after-isct-1440-tail.png)，[旧手机](tools01-evidence/before-isct-390.png) / [新手机](tools01-evidence/after-isct-390-tail.png)。新页面保留四步与问答，在末尾不再出现“高级工具”入口。GSFS 对照也见 evidence 目录的 before/after 图。
- 东科大[第二步](tools01-evidence/after-isct-1440-step2.png)、[第四步](tools01-evidence/after-isct-390-step4.png)、[报告](tools01-evidence/after-isct-390-report.png)和[复制文本](tools01-evidence/after-isct-390-copy.txt)来自相同保存响应。英语、毕业、寄出未到、五项材料保持；“寄出不等于按时送达”仍在提醒中。
- 东大[第二步](tools01-evidence/after-gsfs-1440-step2.png)、[第四步](tools01-evidence/after-gsfs-390-step4.png)、[报告](tools01-evidence/after-gsfs-390-report.png)和[复制文本](tools01-evidence/after-gsfs-390-copy.txt)是合成响应回放。关系卡→原文→返回和报告复制成功。两校桌面/手机报告复制哈希分别一致：ISCT `e22bbf5be9c0010664a943fe5f3b15af32103ef72dee585698c5de79587d2a1c`，GSFS `d8700abf2173664050e85d2d215ffe8228406671745752420be64bcfd037754c`。
- 账本记录每次模拟请求；新版没有 `GET /v1/reviewed-documents`，继续调用 `GET /v1/reference-targets`。浏览器控制台错误为 0，390px 无水平溢出。旧后台端点与服务器路由未改；`/app`、`/app/advanced` 页面一致，`/app/reference` 继续重定向。

## 定向验证与资源

- Python UI/浏览器/API 定向 46 项通过；入口路由 4 项通过；Node 共用投影 9 项通过。浏览器定向包括两校四步、报告重试/复制、学校切换、原文/关系窗口、问答假响应的提交/显示/错误与上下文隔离。JS syntax 与 `git diff --check` 通过。精确 head 的 GitHub Quality CI 待提交 PR 后补记。
- 对照 #258 已登记 SHA-256 的 12 项受保护资产，本轮只读重算均一致。没有修改后端 API、审核规则、PDF、391 索引或模型资产。
- #259 开发累计：真实产品会话 0/1，基础/个人 POST 0/2，GSFS 报告 POST 0/1，付费/真实问答/下载/解析/构建均 0；设计额度未动。模拟浏览器 POST 计入回放日志，不计真实预算。
- 限制：浏览器中的 ISCT 响应来自 #258 保存的真实 HTTP 结果，GSFS 为合成夹具；本轮没有重新验证实际运行服务、在线模型回答质量或学校新版本事实。#258 仍待设计验收；本 PR 必须保持 Draft 与依赖 base。
