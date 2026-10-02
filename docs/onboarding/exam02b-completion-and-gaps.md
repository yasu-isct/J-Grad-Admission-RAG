# EXAM-02B：18 系考试信息完成与缺口（待集中设计验收）

## 用户能看到的内容

原两校四步页 `/app/advanced` 的第二步，在东科大现有 18 系、2026 年 9 月与 2027 年 4 月共 36 个目标展示同册官方 A/B 日程。考试卡先给出 2026 年考试时间、科目、选答方式与配分；口述、英语、语言和课程条件按需展开。日期、材料、考试三个定位按钮沿用第二步；官方原文进入原依据窗口。可选报告新增同源的“考试安排”主题，默认未勾选；仅选择考试时可独立生成、复制。原个人对照、材料准备及旧信息工学系 B 日程 1.0 请求保留。

统一来源是 [#274 字段绑定](exam02a-field-bindings.json)的逐字打包版本 `src/jgrad_admission_rag/demo_config/exam02b_source_bindings.json`，SHA-256 `c724d2e228a128fff1cc863aca68e72cd10ee02bbe4c4ce67c835f7e2d632ef3`。启动时先核对固定 PDF、登记语料、391 Fact、页码、作用域、Fact 文本 SHA 与字段原文锚点；失配降级，不从 KB 搜索临时拼出招生结论。新 API 只在 `include_examination_information=true&exam_presentation_version=2` 时启用；旧请求格式和 CS 1.0 结果不变。官方 A/B 资料可并列查阅，不据此判断本人路线或资格。

## 验证与可复核样张

| 检查 | 证据 |
|---|---|
| 36 个目标真实 HTTP | [逐项状态](exam02b-evidence/real-http-journal.json)：18 系 × 2 批次均 HTTP 200、v2 可用；[#274 字段账本](exam02a-source-ledger.md)逐项对应。 |
| 36 个只读真实源投影 | [投影记录](exam02b-evidence/projection-summary.json)、[18 系中文卡片文字](exam02b-evidence/teacher-card-samples.txt)。每系两批次通过前端来源校验；地球生命课程单独 fail closed。 |
| 报告与复制 | [18 系真实响应生成的考试单选复制文本](exam02b-evidence/exam-only-report-copy-samples.txt)。浏览器与同一保存响应生成的文本逐字一致；默认未勾选时无考试段落。 |
| 桌面与手机 | [7 类保存真实响应回放记录](exam02b-evidence/browser-replay-journal.json)：简单、数学、材料双组、建筑导师选科、融合双题、社会人文无笔试、旧 CS。示例：[建筑第二步桌面](exam02b-evidence/architecture-step2-desktop.png)、[手机](exam02b-evidence/architecture-step2-mobile.png)、[仅考试报告桌面](exam02b-evidence/architecture-report-desktop.png)、[手机](exam02b-evidence/architecture-report-mobile.png)；[无笔试报告](exam02b-evidence/social-human-report-desktop.png)。回放的产品 POST 全由保存响应拦截，实际新 POST 0。 |
| 旧接口与负例 | [4 次真实 HTTP](exam02b-evidence/api-compat-journal.json)：旧 CS 1.0 考试字段及要求与历史响应精确一致；无参数旧请求无考试字段；另册课程不继承系表；错校目标不产生肯定结论。 |
| 受影响回归 | 41 项 Python 通过、16 项现有条件跳过；13 项 Node 通过；7 类四步页桌面/手机无页面错误或横向溢出。PDF、391 KB、payload、vector 的 [SHA 与登记清单一致](exam02b-evidence/protected-asset-hashes.json)。 |

## 未完成、限制与验收顺序

1. **来源仍待设计独立批准。** #277 R1–R3 已按原审查修正并自检，#275 从其精确 head `eb969b1b74929f4976b9e622a0e84f020109d2fc` 建立依赖分支。设计先核对 #277 的 2026 年跨页推定、原文/范围/语言、A/B 路径和课程排除，再审本 PR 的目标匹配、页面与报告。未验收前不合并、不切换在线网页。
2. **真实来源缺口隔离。** 地球生命课程另册不在本次 PDF，显式选择即返回 `not_covered_course` 且无考试路径；本册未载的选答数、配分保持未载。建筑专门科目依全部志愿导师共同指定，页面不代选。机械/应用化学另见网页的细节未下载补充。官方 A/B 日程不证明个人参加资格。
3. **英语规则交界。** 数学不要求外部成绩单，物理在考试日携带，土木有条件性提前邮寄；考试卡转述本系原文，现有个人英语准备规则仍独立核对。若未来要改变材料规则，应另行审核，不由考试卡暗改。
4. **M9 CI 指纹待批准。** `service/app.py` 仅新增显式 v2 查询参数、调用和初始化，未改自然问答/M9 规则。冻结报告、阈值与全部其他 gate 检查通过；本版 `implementation_sha256=e96cb087a5291dec157f6f2a6b8a2212a46c62ed813fe3e95ef19ef49975d213` 对旧值 `f0906681edf8bf657008a882888f62915ee1866a7734a97c773ae3bc748874b2` 不匹配。自动审批拒绝本轮未获精确授权的政策指纹更新，因此 PR 保留该 CI 单项失败，等设计/用户明确批准后才能改签；历史数据和验收阈值不动。

**资源账本。** 本项 1 次独立服务启动并停止；基础/个人产品 POST **44/60**（36 个目标基础、4 个英语个人对照、4 个兼容/负例），GSFS 报告 POST 0，付费 0，下载 0，PDF 解析重跑 0，KB/向量构建 0，受保护资产写入/复制 0。浏览器回放另有 7 次被本地路由拦截的模拟 POST，不计产品服务请求；设计预留的 12 次未动。

**复现入口。** 从本 PR 工作区设置 `PYTHONPATH=src`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，使用既有 `jgrad-demo`/`python -m jgrad_admission_rag.demo_cli`，参数为 `--pdf D:/J-Grad-Admission-RAG/outputs/real_pdf/isct_2027_4_2026_9_master.pdf --workspace D:/J-Grad-Admission-RAG/outputs/m10-09-deepseek-live --embedding-provider bge-m3 --embedding-cache D:/J-Grad-Admission-RAG/outputs/model-cache --reference-workspace-config D:/J-Grad-Admission-RAG/outputs/display-01/real-config.json --port <空闲端口>`；不加 build/rebuild 选项，确认日志为 `reused-read-only`、`391`、`online=false`。四步页路径是 `/app/advanced`，当前在线服务不由本 PR 切换。
