# PREP-01 #254 第一段：实现与验证交接

## 范围与复用

开发分支 `codex/prep01-preparation-guidance` 基于 main `2b61c28c45ce18cabefd1d2c2f3c268f5aa34faf`。复用现有两校四步页、`DemoApplicantComparisonRequest`、`ApplicantProfile.language_test_results`、391 审核规则的 `build_applicant_report`、原文抽屉和可选报告。未修改领域 Profile、已审核规则、KB、索引或 M9 权威边界。

先实现英语和第①②项样板，再补齐第③④⑤项。五项仍使用原有 `materials[{code,preparation}]` 三态输入；中文文字只在已核对的学校、资料、Fact 和页码绑定成立时出现。当前只支持东科大 `isct_2027_4_2026_9_master`；东大仍走原展示。

## 来源与字段对应

| 页面内容 | 已审核来源 | 实际使用位置 |
| --- | --- | --- |
| 邮寄地址标签、入学申请表、志愿理由书、学士课程成绩证明、毕业或预计毕业证明 | 同一 PDF p.10，`fact:00104`；各自表格行 ①～⑤。④⑤的 OCR 名称被拆行，按行号与拆行片段核对 | `materialGuide` 为第二步、第四步、原文抽屉、报告和复制提供目的、准备方法、注意与条件说明；正式适用性和准备三态仍取服务响应 |
| 接受／不接受的考试类型、TOEIC 数字证明和二维码 | p.11 `fact:00110` | 第二步英语概要、旧规则 `approved-kind`／`unapproved-kind`、`toeic-digital-certificate`／`toeic-qr` 的执行结果 |
| TOEFL Test Taker Score Report 与 G179 | p.11 `fact:00111` | 第二步说明和已有 TOEFL 证明规则 |
| 本版本考试日期下限 | p.11 `fact:00114` | 第二步及已有 `test-date` 谓词；未在展示层另算日期 |
| 在线 PDF 与纸质成绩单说明 | p.11 `fact:00115` | 第二步及已有 `online-pdf` 谓词 |
| 数学系英语笔试例外 | p.12 `fact:00123` | 现有 `math-written-exam` 规则成立时，不把外部证明列为待办 |
| 信息工学系出愿时提交、截止后不可补交／替换 | p.52 `fact:00287` | 仅审核目标为信息工学系且对应规则及 Fact 成立时显示 |

| 新请求字段 `english_preparation.*` | 页面选择 | `ApplicantProfile.language_test_results[0].*` | 已有规则后缀，均加 `isct-master-english-` 和入学期 `-apr/-sep` |
| --- | --- | --- | --- |
| `downloaded_online_pdf` | 在线下载的官方 PDF | 同名字段 | `online-pdf` |
| `toeic_verification_qr_present` | TOEIC 真伪验证二维码 | 同名字段 | `toeic-qr` |
| `toeic_digital_official_score_certificate` | TOEIC 数字官方证明或同等形式 | 同名字段 | `toeic-digital-certificate` |
| `toefl_test_taker_score_report_pdf` | TOEFL 指定成绩 PDF | 同名字段 | `toefl-report-toefl_ibt`／`toefl-report-toefl_ibt_home_edition` |
| `toefl_di_code_g179_set` | 本次成绩设置 G179 | 同名字段 | `toefl-g179-toefl_ibt`／`toefl-g179-toefl_ibt_home_edition` |

旧请求不带 `english_preparation` 时，响应不含 `english_preparation_result` 键。新页面显式发送这一分组；服务端构造旧 Profile，并由已有报告引擎生成 `source_decisions`、`resolution_steps`、`predicate_outcomes` 与证据，然后投影为核对卡。`true`、`false`、`null` 分别产生按填写已具备、明确待处理、尚待确认；触发不接受考试的规则不会被误写成合格。考试切换清理旧成绩、日期和专属证明；学校切换清理全部个人输入与旧报告。

## 同一真实响应前后样张

真实目标：东科大信息工学系，2027 年 4 月入学，B 日程。自报 TOEIC L&R、2024-06-11、在线 PDF 已取得、QR 未确认、数字官方证明已取得；邮寄标签已准备、入学申请表未准备，其余材料未填写。

保留了同一真实服务返回的[目标目录](prep01-evidence/reference-targets.json)、[基础要求](prep01-evidence/isct-base.json)、[个人对照](prep01-evidence/isct-comparison.json)。[旧版复制样张](prep01-evidence/before-materials-copy.txt)和[新版复制样张](prep01-evidence/after-materials-copy.txt)分别用 main 原有与本分支展示适配器投影这三份完全相同的响应；[哈希与字符数](prep01-evidence/copy-comparison.json)记录输入及结果。新版文本与[浏览器实际复制](prep01-evidence/desktop-materials-copy.txt)逐字一致；桌面和手机复制内容一致。

旧版只有五项材料简短名称、状态和通用提醒；新版包括五项具体准备方法、条件提示、当前目标英语要求与五项核对结果。报告正文不带 Fact、规则 ID 或检索内部字段。只勾“关键时间”时不输出材料准备结论。

| 视图 | 桌面 | 手机 |
| --- | --- | --- |
| 第二步英语与材料 | [整页](prep01-evidence/desktop-step2.png)／[英语视口](prep01-evidence/desktop-step2-focus.png) | [整页](prep01-evidence/mobile-step2.png)／[英语视口](prep01-evidence/mobile-step2-focus.png) |
| 第四步准备结果 | [整页](prep01-evidence/desktop-step4.png)／[英语视口](prep01-evidence/desktop-step4-focus.png) | [整页](prep01-evidence/mobile-step4.png)／[英语视口](prep01-evidence/mobile-step4-focus.png) |
| 仅材料与待办报告 | [截图](prep01-evidence/desktop-report-materials.png) | [截图](prep01-evidence/mobile-report-materials.png) |
| 仅关键时间报告 | [截图](prep01-evidence/desktop-report-dates.png) | [截图](prep01-evidence/mobile-report-dates.png) |

真实产品服务会话只启动一次、基础／个人对照 POST 共两次，得到上面三份响应；初次桌面截图来自该会话。之后发现 p.10 OCR 对第④⑤项的拆行，修复展示绑定。最终桌面／手机截图、复制内容和考试／学校切换检查均由保存的真实响应在静态重放页完成；重放未启动产品服务、未向产品 API 发送 POST。真实规则集成测试单独只读既有 391 审核资产，执行请求→旧 Profile→旧规则→详细结果。完整计数和 12 项资产前后哈希见[运行记录](prep01-evidence/journal.json)，资产一致。

## 验证与边界

- `tests/test_prep01_english.py`：真实审核数据驱动的 TOEIC／TOEFL／Home Edition 类型、五证明字段、三态、日期边界、数学例外、旧请求兼容。`tests/unified_core.test.mjs`：来源身份、五项 OCR 行绑定、报告展示。
- 保存响应的浏览器重放：1440px 与 390px、第二步／第四步／原文抽屉／报告选题／复制、TOEIC→TOEFL 清理、东科大→东大切换清理。
- `service/app.py` 只在既有请求错误处理器中为 `english_proof_kind_mismatch` 返回 422 的字段提示；其他验证错误及 M9 生成／检索处理保持原样。为使 M9 完整性检查绑定这版实际代码，只将 `config/grounded_rag_release_gate_v1.json` 的 `implementation_sha256` 从 `f2e73660…` 改为门禁函数重算的 `189705ee…`；路径、阈值、评测输入／结果哈希均未改。完整门禁重算通过，供设计审查此最小差异。
- 本地定向 Python **64 passed**，Node **8 passed**；`ruff check`、`ruff format --check`、`compileall`、`git diff --check`、语义检索门禁、M9 门禁均通过。全仓离线测试一次运行得到 **1846 passed、301 skipped**，唯一失败是 Windows 工作区 `build/lib` 的写入权限；同一 wheel 用例在隔离临时目录单独重跑 **1 passed**。PR 的 Linux CI 将提供最终完整套件结果。
- 本任务不验证用户上传文件、二维码真伪、ETS 账户或学校实际受理。已准备仅表示用户自报；未知条件不会写成不符合或豁免。
- 累计预算：真实产品服务 **1/1** 次、基础及个人对照 POST **2/6** 次、GSFS 报告 POST **0**；付费调用、下载、解析重跑、构建均 **0**。本轮不再启动真实服务。
