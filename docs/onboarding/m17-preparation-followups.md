# M17 后续三项：准备提醒、入口清理、笔试信息

当前状态（2026-10-01）：#258已验收合并；#259仅修问答计数回归；#260资料已审但生产仍Blocked，最终字段合同未放行。[独立审查](prep02-tools01-design-review.md)。下表为原设计顺序，不是新的Ready许可。

2026-09-30 用户授权继续设计这三项；尚未选择更换为Claude/PDF方案，也没有授权东大扩覆盖。
审计基线 `cd406405fcce1380e9bcb7f346b494e299dd9a3e`，PREP-01 #254已完成。本次仅设计文档与Issue，不修改生产代码或运行预览。

| 顺序 | Issue与用户效果 | 放行条件 |
|---|---|---|
| 1 | [#258 PREP-02](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/258)：毕业日期、网上手续、寄出/实际到达转为清晰提醒 | 本设计合并后唯一Ready |
| 2 | [#259 TOOLS-01](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/259)：移除高级工具面板，保留主流程与共享功能 | 第一项验收合并，设计明确放行 |
| 3 | [#260 EXAM-01](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/260)：信息工学系A/B考试安排与笔试科目卡 | 前两项合并，设计补齐原页/年份/字段审核后放行 |

顺序原因：先将实用字段接到主流程，再撤下旧入口；最后增加独立考试信息。
同一M17 Main对话可串行实施，每项独立PR和交接，不同时开展，不要求为每个检查点开新对话。

复用：已有ApplicantProfile日期/提交字段、审核规则和predicate_outcomes、PREP-01可选投影、
四步页/报告/原文窗口。高级工具需要清理app.js旧DOM依赖，不能只删HTML。
考试p.52已有Fact和表格，但结构化展示配置尚未审核完成，不能把样板当成已完成招生事实验收。
主页面 /app 实际返回advanced.html；/app/advanced旧入口需保持访问兼容。

具体规格：
- [PREP-02字段、中文样板、验收](prep02-graduation-submission-spec.md)
- [TOOLS-01依赖清理表](tools01-advanced-cleanup-spec.md)
- [EXAM-01范围与放行前审核](exam01-written-exam-spec.md)

共同边界：334/391、PDF、模型缓存、reference_only与回滚版本保持；付费/下载/构库0。
QA #233/#236继续暂停，东大普通学生扩覆盖、M13、MinerU不启动。
用户在线预览8005固定cd4064，目录outputs/design-prep正在使用；8004/8003及其他预览也不自动切换/停止。
各任务独立有界预算见Spec；上一任务累计台账不重置。每项只做与风险相关的验证，优先复用真实保存响应。
实现完成后准备演示，不自动进入普通学生扩覆盖或改变系统架构。
