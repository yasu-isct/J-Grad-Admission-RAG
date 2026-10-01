# EXAM-01 #260 开发自检交接

状态：M17 Main 开发自检完成，待设计 Agent 独立验收；不代表最终事实或产品验收。
实施分支 `codex/exam01-b-schedule`，基底 main `2684cd97c1e9ebad4c0b245cc2f81fda0063497b`。精确提交和 CI 以 PR 页面的 head 为准。

## 来源、字段与兼容

运行配置为 [`reviewed_exam_presentation.json`](../../src/jgrad_admission_rag/demo_config/reviewed_exam_presentation.json)，从已合并的 [审核字段表](exam01-reviewed-field-map.json)制作。启动时校验配置摘要、注册语料身份、PDF/KB 摘要、Fact 全文摘要、页码、作用域、字段引用和原文子串；失配关闭考试分组，不更改既有资格规则。2026 考试年来自固定同册 p.1、p.2、p.52 的设计审核，p.1 保留 `pdf_page` 身份，没有虚构 Fact。

| 用户可见内容 | 已审核来源 |
| --- | --- |
| B 日程笔试日期、9:30–12:00、150 分钟、A/B/C 科目组、每组出题、日语作答、专业 900/英语 100、英语外部成绩方式、口述日期和对象 | `fact:00288`，物理 p.52；其 Fact 类型为 `english`，由精确来源绑定校验 |
| 口述对象 8 月 20 日 17 时左右起公布 | `fact:00289`，物理 p.52；保留“左右起”，不当作最终合格公告 |
| 英语成绩单须在出愿时提交的入口 | `fact:00287`，物理 p.52；前端跳转既有英语证明说明 |
| 考试年份 2026 | 固定 PDF 封面 p.1、流程 p.2、系内表 p.52 的跨页审核；不按入学年份替换 |

真实 391 校验读取了既有 PDF 和 KB，PDF SHA256 `57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735`，KB SHA256 `7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce`；前后相同。配置读取到 391 条 Fact，`fact:00287/288/289` 的全文哈希、p.52、系内作用域和短引文均通过。完整字段级偏移见审核字段表与运行配置。中文语义是人工/设计审核结果，程序校验不能代替自然语言蕴含审核。

原 `POST /v1/base-requirements` 及 `?include_examination_information=false` 不新增考试字段。只有显式 `true` 添加旁路分组；个人对照、问答和 GSFS 接口合同未改。两批次 B 日程均显示 2026 考试；非目标系返回“本项目尚未整理考试安排”。配置失效返回 `unavailable`，不显示旧值或肯定安排。A 路线未加进当前目标目录。

## 同一真实响应的页面与报告

保存的 [2027 年 4 月 CS B 基础响应](exam01-evidence/cs-april-response.json)用于以下浏览器回放。桌面与手机均复用原四步页；截图由本分支静态资源和保存响应生成，**没有启动在线产品服务**。

- 第二步：[桌面全页](exam01-evidence/exam01-step2-desktop.png)、[手机全页](exam01-evidence/exam01-step2-mobile.png)、[桌面考试卡](exam01-evidence/exam01-card-desktop.png)、[手机考试卡](exam01-evidence/exam01-card-mobile.png)。
- 报告：[桌面考试单选](exam01-evidence/exam01-report-desktop.png)、[手机考试单选](exam01-evidence/exam01-report-mobile.png)。
- 同一响应的复制样张：[原默认主题](exam01-evidence/report-default.txt) 与 [考试单选](exam01-evidence/report-exams-only.txt)。考试主题默认不勾；单选考试无材料缺项结论，不触发个人对照请求。预览与复制均来自同一 reader 投影。

浏览器回放核查了原文窗口打开/关闭及焦点返回、英语证明跳转、桌面与手机不横向溢出；回放只有一次**模拟**基础 POST，未计入真实 391 产品额度。回放脚本为 [exam01-browser-replay.py](exam01-browser-replay.py)。其他学校与目标切换仍沿用现有失效/取消机制，合成浏览器回归通过。

## 验证与预算

真实 TestClient 会话使用现有 391 runtime 完成一次启动、四次基础 POST：CS April `available`、CS September `available`、非 CS `not_covered`、旧请求无新字段，HTTP 均 200。April/September 的结构化考试安排相同，考试年均为 2026；April 去掉考试分组后与同目标旧响应完全相等。[预算与资产日志](exam01-evidence/real-journal.json)和 [一次性验证脚本](exam01-real-validation.py)可复核。未配置 provider，未进行付费调用或真实问答。

定向测试：Python 43 项（含合成两校浏览器 6 项）、Node 10 项通过；真实响应离线浏览器回放通过。`ruff check`、格式检查、语义检索与 M9 离线 gate 通过；完整仓库 CI 待 PR 精确 head 的 GitHub Actions 结果。保护资产、正在运行的 8005/8004/8003 预览未变。

M9 的绑定文件差异仅为 `service/app.py` 中考试展示配置的启动加载、基础要求查询开关与旁路分组；检索、生成、问答、资格执行函数均未修改。`implementation_sha256` 由 `189705ee88842578093fb1f181c3120bb0d5ed9faee5010b3a6f5d52cd59f222` 更新为 `f0906681edf8bf657008a882888f62915ee1866a7734a97c773ae3bc748874b2`，`implementation_paths`、suite、observations、语义基线、gold、阈值不变；M9 其余 16 项检查全部通过。此摘要更新只记录本版代码，不表示独立验收。

累计开发预算：真实产品会话 **1/1**，基础/个人 POST **4/4**，GSFS 报告 **0**，真实问答 **0**，付费 **0**，PDF/模型下载 **0**，解析重跑 **0**，KB/索引构建 **0**。后续复审使用已保存响应与定向测试，不再启动真实产品会话或追加真实 POST。

## R1 增量修复：个人对照失败不阻断考试单选

设计复审指出，填写个人情况后原报告按钮会先请求个人对照，503 时连已加载的考试单选也打不开。本次把主题选择放在请求前：填过个人情况且未完成对照时，默认日期／材料主题显示“需先核对个人情况”，不可复制；明确选择仅考试时直接用已加载基础响应预览与复制，不请求个人对照。选择日期／材料等个人主题后，用户可在同一窗口按“核对个人情况并生成所选报告”；失败会明确提示并保留主题选择，随后切回考试单选仍可复制。已有有效对照或同一窗口成功结果可复用。目标或个人输入变更仍清除旧报告。

[R1 保存响应回放脚本](exam01-r1-browser-replay.py)使用上文同一 CS April 基础响应及既有个人对照保存响应，全程拦截本地 URL，**没有启动真实服务**。桌面 1440 与手机 390 的 [失败后考试单选截图](exam01-evidence/r1-report-recovery-desktop.png)、[手机截图](exam01-evidence/r1-report-recovery-mobile.png)、[个人主题复制样张](exam01-evidence/r1-report-personal-copy.txt)及 [断言日志](exam01-evidence/r1-report-recovery.json)记录：考试单选各为 0 次模拟个人对照 POST；主动核对返回 503 后，考试复制文本与失败前逐字相同；桌面端重试 200 后，日期／材料／考试混合报告可复制，重开复用，不重复请求；切换目标清除考试安排。两个视口没有脚本错误或横向溢出。

增量验证：现有考试与四步合成浏览器测试 **7 通过**，Node reader 测试 **10 通过**，新增保存响应回放两个视口通过；JS 语法、Ruff 检查与格式、`git diff --check` 通过。真实预算维持上述累计数，新增付费、下载、解析或构建均为 0。最终以本次 PR 精确 head 的 CI 与设计 Agent 增量复审为准。
