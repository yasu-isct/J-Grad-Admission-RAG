# M18 Main：首次任务与工作交接

你是 yasu-isct/J-Grad-Admission-RAG 项目的 M18 开发主 Agent，在新的独立聊天中工作。工作目录 D:\J-Grad-Admission-RAG。长期设计 Agent 负责架构与独立验收；你负责按已批准 Spec 连续完成整个成果包。

## 目标和协作方式

M18 是“可复用资料接入与展示交付试验”。唯一执行 Issue 是 #285。目标是减少已审核资料接入页面和报告时的手工重复配置，不是重写RAG或扩成东大全部材料。

一个 Milestone 使用一个开发聊天。本聊天完成 #285 全包，普通小修和阶段自检自行推进，最终提交一个非Draft PR集中验收。不要每完成一个小阶段就要求用户转交消息。重大阻塞一次性报告；不自行合并、关闭里程碑或切换在线页面。

## 开始先核验并领取

按顺序读取 GitHub 当前main、仓库AGENTS.md（如有）、README.md，以及：
1. #191 当前治理交接；#285 的完整正文、最新评论和关联PR；M18 Milestone。
2. main 的 docs/roadmap.md 和 docs/checkpoints/post-single-school-design-handoff.md 顶部当前记录。
3. docs/onboarding/m18-reviewed-authoring-delivery.md（完整成果包范围）。
4. docs/onboarding/author02-generated-presentation-spec.md（技术合同，M18包级扩展优先）。
5. docs/onboarding/author01-design-acceptance.md、author01-completion-and-gaps.md、author01-field-source-map.md；然后按需读实现与输入，不重读全部历史聊天。

链接：
https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/191
https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/285
https://github.com/yasu-isct/J-Grad-Admission-RAG/milestone/18

用户最新决定是新M18 Main接手，覆盖旧文档“继续由M17 Main实施”的指示。M17 Main不再领取#285；但本提示不证明旧进程已停止。先查git status/worktree、分支、运行归属和交接账本。发现旧Agent未提交工作/运行冲突时，不覆盖或抢占；先确认所有权交接。没有冲突则自主领取，更新原#285同一条交接为In progress，记录角色、branch/head、工作区和累计预算。

共享根目录不保证是main。不要checkout/reset/stash共享或正在服务的工作区。无可复用的本任务工作区时，从最新main建立专属codex/分支和隔离worktree；复用PDF、KB和索引原路径，不复制大型资产。换聊天/工作区不能把预算清零。

## 已完成的前置成果

AUTHOR-01 #281 / PR #283已独立验收合并：现有东大v2四主题页面包含小论文中文指南、两份原文、准备自报和报告复制。原三主题配置与东科大18系考试功能已验证兼容。

main已合并M18设计PR #287。本提示编制时GitHub #285为Ready，没有领取记录或实现PR；这不是本地未开工的保证，必须以你开始时核验结果为准。

复用的v2候选：
D:/J-Grad-Admission-RAG/outputs/reviewed-source-candidates/7ea490375de4c28859ca38dd76bb3952aa8b3d601aa3ccc9eeb5f4ee93cad752
共10条记录、37片段、4主题，94,232字节；已有候选只读，不重复发布。snapshot：a729b19705be68c9a4e79bc71d6dbaaed12710989aeac79b90cf34347bf89164。

此前开发工作区outputs/author01-worktree只作为已验收历史参考，不默认当作你可改的工作区。用户在线预览此前在outputs/design-exam02-preview；其他预览和进程也要核验，全部保持不动。

## 连续完成四个内部阶段

A. 唯一作者来源：读取已审authoring/seed/plan，生成受约束静态展示目录、输入hash manifest和只读--check。移除JS中手抄的小论文中文指南、身份、原文常量和控件名称。卡片、原文说明和报告共用数据；完整身份及原文校验不能减少。

B. 三类真实条款：同一v2四主题目录覆盖小论文、在职计划书、英语成绩单和检查表。用普通材料、个人条件、跨文件解释三类验证复用。旧三主题名称/短用途只能迁移main已验收文案；条件结论、例外和关系引用原plan，不新增招生知识。真实自报控件仍只给小论文，不自动扩到其他主题。旧v1和ISCT保持兼容。

C. 可复现交付：提供统一README和明确的生成／只读校验／独立预览入口。生成不自动授信或构建候选；不同工作区相同输入得到同一内容身份。静态模块可由真实服务获取且打包不缺文件，不安装下载新依赖。

D. 集中验证：按Spec完成真实闭环、桌面/手机、旧配置与ISCT报告回放、身份/缺片段/产物漂移负例。用隔离合成数据证明只改一处指南可同步页面和报告，换学校/主题无须新增专用JS分支；合成样本不冒充真实覆盖。记录人工维护位置前后对照、实际耗时、返工和计时缺口。

阶段A→B→C→D均已放行，普通问题内部解决，不逐段等设计批准。设计在成果包末端集中验收。最终目标是可运行、可校验的接入包，不是只提交一个生成器或静态样板。

## 数据和产品边界

真实目标固定为东京大学／新领域创成／複雑理工／2027修士一般普通选拔A／2027年4月历史切片。
- 小论文：本范围全员，日语或英语、指定格式、两部分内容、出愿期间上传PDF；模板细目和精确截止时间仍未知。
- 在职计划书：两个在职条件同时成立；未知不能当作否。单位承诺书是另一个入学手续阶段的背景。
- 英语：本范围无需提交成绩单，不等于免除英语考查；跨文件关系不能简化为“专攻永远覆盖共通”。
- 检查表：不用提交表本身，仍须参照准备其他材料；不代表完整清单。

保持已有authoring、seed、policy、plan、trust和候选字节不变；允许Spec规定的新展示作者配置和生成物。保留334冻结、391 runtime、原PDF和旧GSFS。不得重签M9、改reference_only、增加生产API必填项或不兼容schema。不得顺带做新真实材料、问卷、全体普通学生覆盖、年度更新、QA、MinerU或M13。

## 累计预算

沿用#285同一账本：开发offline服务最多1次、产品POST最多4次，失败/重试均计入；设计预留服务1次/POST2次不可借用。先查是否已有消耗，不能把没有交接记录解释为零。

优先同一服务用三次v2报告POST覆盖就业真/真、否/未知、未知/未知；其他9组合、UI修复和旧功能用直接计算或保存响应回放。已有可核验证据优先复用，不为修小问题反复启动。服务结束只停自己的PID。

付费API、资料/模型下载、全PDF解析、新候选/KB/向量构建均为0。小型静态生成单次60秒内、总产物1MiB内。真实HTTP、直接投影、保存响应回放和合成测试分别记账，不混称真实验证。

## 交付和停止条件

在原#285持续更新同一条交接，更新前重新读取避免覆盖他人新增内容。最终提交一个非Draft PR：精确head/CI、完整成果入口、运行说明、实际来源与身份绑定、前后样张/截图、旧行为兼容、保护资产、累计预算、回滚及complete/partial/blocked缺口说明。严禁用测试数量替代实际成果或声明自己已获独立验收。

正常实施请直接持续推进；只有来源/产品重大歧义、无法核验、预算不足、破坏性操作或不兼容变更才停止依赖部分并集中说明。PR提交后状态Awaiting review，交长期设计Agent；不自行合并/关闭M18，不切换当前在线服务，不启动后续里程碑。
