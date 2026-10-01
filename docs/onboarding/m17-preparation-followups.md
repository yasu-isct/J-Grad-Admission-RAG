# M17 演示补充：准备提醒、工具整理与考试信息

当前状态（2026-10-01）：#258、#259已经独立验收合并。#260正式来源、字段和API合同已完成；
本设计PR #264合并并更新#191为Ready后，只有#260可进入开发。M17 Main沿用原对话，一份实现PR交设计验收。

| 任务 | 用户效果 | 状态 |
|---|---|---|
| [#258 PREP-02](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/258) | 毕业日期、网上手续、寄出与实际送达提醒 | Accepted/merged，PR #262 |
| [#259 TOOLS-01](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/259) | 移除旧高级工具，保留报告、问答与原文窗口 | Accepted/merged，PR #263；问答计数回归已复核 |
| [#260 EXAM-01](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/260) | 第二步展示信息工学系B日程笔试，报告可选考试主题 | 设计PR合并后唯一Ready；尚无生产实现 |

[前两项独立验收与来源审核](prep02-tools01-design-review.md)。
[EXAM-01正式规格](exam01-written-exam-spec.md)与[逐字段来源](exam01-reviewed-field-map.json)是开发依据，
旧A/B并列候选已收窄为当前目录已有的B日程；2026考试年按固定册p.1、p.2、p.52跨页审核。

继续复用原两校四步页、现有KB/目标选择、原文窗口和共享报告。只添加小型审核展示配置和可选响应，
不重建向量库、不用问答临时生成考试事实，也不制作独立考试页面。

每项累计预算见各自Spec，不因换对话重置。EXAM-01开发/设计各最多1次真实产品会话、4次基础/个人POST；
付费、真实问答、下载、解析重跑及KB/索引构建均0。直接读取已有KB与保存响应回放优先。
用户8005固定cd4064及其他预览保持，不自动升级或停止。334/391、PDF、模型缓存、reference_only与回滚点不变。
完成后准备私塾演示；QA #233/#236、东大普通学生扩覆盖、M13/MinerU保持暂停，不自动改为Claude/PDF架构。
