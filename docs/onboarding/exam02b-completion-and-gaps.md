# EXAM-02B：18 系考试信息完成与缺口（待集中设计验收）

## 用户能看到的内容

原两校四步页 `/app/advanced` 的第二步，在东科大现有 18 系、2026 年 9 月与 2027 年 4 月共 36 个目标展示同册官方 A/B 日程。考试卡先给出 2026 年考试时间、科目、选答方式与配分；三系本册课程范围及另册排除默认可见；口述、英语和语言按需展开。日期、材料、考试三个定位按钮沿用第二步；官方原文进入原依据窗口。可选报告新增同源的“考试安排”主题，默认未勾选；仅选择考试时可独立生成、复制。原个人对照、材料准备及旧信息工学系 B 日程 1.0 请求保留。

统一来源是 [#274 字段绑定](exam02a-field-bindings.json)的逐字打包版本 `src/jgrad_admission_rag/demo_config/exam02b_source_bindings.json`，SHA-256 `906ceaa57ac615f1d2acb1da1265f93c690e8574b31fc8a2303e2b12605acfad`。启动时先核对固定 PDF、登记语料、391 Fact、页码、作用域、Fact 文本 SHA 与字段原文锚点；失配降级，不从 KB 搜索临时拼出招生结论。新 API 只在 `include_examination_information=true&exam_presentation_version=2` 时启用；旧请求格式和 CS 1.0 结果不变。官方 A/B 资料可并列查阅，不据此判断本人路线或资格。

## 验证与可复核样张

| 检查 | 证据 |
|---|---|
| 36 个目标真实 HTTP（前版存档） | [逐项状态](exam02b-evidence/real-http-journal.json)：旧来源版18 系 × 2 批次均 HTTP 200、v2 可用；本轮新来源内容用下列只读直接投影及保存基础响应回放验证，没有新增产品 POST。 |
| 36 个只读真实源投影 | [投影记录](exam02b-evidence/projection-summary.json)、[18 系中文卡片文字](exam02b-evidence/teacher-card-samples.txt)。每系两批次通过前端来源校验；地球生命课程单独 fail closed。 |
| 报告与复制 | [前版18系真实响应复制文本](exam02b-evidence/exam-only-report-copy-samples.txt)保留作历史对照；[本版10系保存基础响应＋只读考试投影的复制文本](exam02b-evidence/review-exam-only-report-copy-samples.txt)与七类浏览器回放逐字一致。默认未勾选时无考试段落。 |
| 桌面与手机 | [7 类保存基础响应＋本版直接投影回放记录](exam02b-evidence/browser-replay-journal.json)：简单、数学、材料双组、建筑导师选科、融合双题、社会人文无笔试、旧 CS。示例：[建筑第二步桌面](exam02b-evidence/architecture-step2-desktop.png)、[手机](exam02b-evidence/architecture-step2-mobile.png)、[仅考试报告桌面](exam02b-evidence/architecture-report-desktop.png)、[手机](exam02b-evidence/architecture-report-mobile.png)；[无笔试报告](exam02b-evidence/social-human-report-desktop.png)。回放中所有 GET/POST 均由本地浏览器拦截，实际新服务／POST 0；[四类考试卡两视口增量回放](exam02b-evidence/review-card-replay.json)核对三系默认课程提示，以及地球惑星笔试四组原文与系统控制多 Fact 口述，[地球惑星手机原文](exam02b-evidence/review-earth-390-source.png)、[应用化学手机课程提示](exam02b-evidence/review-applied-chemistry-390-card.png)。 |
| 旧接口与负例 | [4 次真实 HTTP](exam02b-evidence/api-compat-journal.json)：旧 CS 1.0 考试字段及要求与历史响应精确一致；无参数旧请求无考试字段；另册课程不继承系表；错校目标不产生肯定结论。 |
| 受影响回归 | 前版41 项 Python 通过、16 项现有条件跳过；本轮新旧考试定向 Python 6 项、Node 13 项，36目标只读投影与7类完整四步页＋4类考试卡双视口回放通过。M9 policy 写入被自动审批拦截，不能称当前 CI 绿。PDF、391 KB、payload、vector 的 [SHA 与登记清单一致](exam02b-evidence/protected-asset-hashes.json)。 |

## 未完成、限制与验收顺序

1. **来源仍待设计独立批准。** #277 R1–R3 已按原审查修正并自检，#275 先从原 head `eb969b1b74929f4976b9e622a0e84f020109d2fc` 建立，并已重放到来源返修 head `d6b3f99b40024324447223f8dc4bd595216e9bbb` 的依赖分支。设计先核对 #277 的 2026 年跨页推定、原文/范围/语言、A/B 路径和课程排除，再审本 PR 的目标匹配、页面与报告。未验收前不合并、不切换在线网页。
2. **真实来源缺口隔离。** 地球生命课程另册不在本次 PDF，显式选择即返回 `not_covered_course` 且无考试路径；本册未载的选答数、配分保持未载。建筑专门科目依全部志愿导师共同指定，页面不代选。机械/应用化学另见网页的细节未下载补充。官方 A/B 日程不证明个人参加资格。
3. **英语规则交界。** 数学不要求外部成绩单，物理在考试日携带，土木有条件性提前邮寄；考试卡转述本系原文，现有个人英语准备规则仍独立核对。若未来要改变材料规则，应另行审核，不由考试卡暗改。
4. **M9 policy 单字段写入受自动审批阻挡。** 已比对审查 head 的四个跟踪文件均未改变，重算 `implementation_sha256=e96cb087a5291dec157f6f2a6b8a2212a46c62ed813fe3e95ef19ef49975d213` 与设计原 PR 审查授权值完全相同。自动审批仍拒绝持久修改 `config/grounded_rag_release_gate_v1.json`，理由是该授权仅来自工具读取的审查内容，而非用户在当前可信对话中的明确批准，并明确禁止绕过。policy 未改；精确 CI 1850 项通过、314 项跳过、2 项失败，两项唯一失败码均为 `implementation_sha256`，其他 gate 检查通过。需用户直接批准这一次精确单字段更新后才可完成 CI。历史数据、路径与阈值均不动。

**资源账本。** 本项 1 次独立服务启动并停止；基础/个人产品 POST **44/60**（36 个目标基础、4 个英语个人对照、4 个兼容/负例），GSFS 报告 POST 0，付费 0，下载 0，PDF 解析重跑 0，KB/向量构建 0，受保护资产写入/复制 0。浏览器回放另有 7 次被本地路由拦截的模拟 POST，不计产品服务请求；设计预留的 12 次未动。

**复现入口。** 从本 PR 工作区设置 `PYTHONPATH=src`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，使用既有 `jgrad-demo`/`python -m jgrad_admission_rag.demo_cli`，参数为 `--pdf D:/J-Grad-Admission-RAG/outputs/real_pdf/isct_2027_4_2026_9_master.pdf --workspace D:/J-Grad-Admission-RAG/outputs/m10-09-deepseek-live --embedding-provider bge-m3 --embedding-cache D:/J-Grad-Admission-RAG/outputs/model-cache --reference-workspace-config D:/J-Grad-Admission-RAG/outputs/display-01/real-config.json --port <空闲端口>`；不加 build/rebuild 选项，确认日志为 `reused-read-only`、`391`、`online=false`。四步页路径是 `/app/advanced`，当前在线服务不由本 PR 切换。
