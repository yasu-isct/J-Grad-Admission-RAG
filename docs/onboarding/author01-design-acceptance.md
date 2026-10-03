# AUTHOR-01 小论文接入：设计独立验收

2026-10-03，#281 / [PR #283](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/283) **验收通过并合并**。
实现 head `e7cf52c81a7ca24ba99f08135f9c7a2d2d49c120`；merge `af4ca5fcb89349003822bc6e92f57d974e833a20`。[原 PR 独立验收](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/283#issuecomment-5964253899)。

## 用户可见成果

原两校四步页的东大固定历史目标可通过独立配置显示四个主题，新增申请小论文：中文准备步骤、两份原文及补充关系、个人三态准备记录、可复制报告。原三主题配置仍为三主题，用户当前在线服务没有切换。

目标仍为东京大学／新领域创成／複雑理工／2027修士一般选拔A／2027年4月。小论文要求指定格式、日语或英语、研究主题与动机及具体自身优势两部分、出愿期间上传PDF。未持有指定模板，字数/版式细目和精确截止时间保留未知；不是完整普通学生材料清单。

## 独立核验

精确提交使用 `outputs/design-author01-review/head-e7cf52c` 隔离归档；没有修改开发checkout或用户服务目录。唯一调整是设计本地preview配置将五个元数据路径指向该归档；真实PDF、候选、391 runtime仍读取原路径。服务账本的config字段由复用启动脚本记录原参数，实际加载的设计配置见本地 `design-evidence/local-preview.json`，不改配置内容hash。

- 已审v2 seed/pin、旧8记录/23片段/5关系、全部37片段映射、新policy/plan/trust复核通过。纯mapper结果与实际候选五文件逐字一致，未调用publish或创建第二build。新候选 `7ea490375de4c28859ca38dd76bb3952aa8b3d601aa3ccc9eeb5f4ee93cad752`，94,232字节；新snapshot `a729b19705be68c9a4e79bc71d6dbaaed12710989aeac79b90cf34347bf89164`。PDF/source-set仍为s1。
- [真实浏览器账本](author01-design-evidence/live-browser-journal.json)：精确代码、真实候选、原391 runtime的一次offline服务，桌面/手机各一次真实报告POST，均200。四主题/全部14新增片段、来源返回焦点、报告和复制通过；修改个人自报三态后复用同目标同就业条件结果，无额外POST。没有拦截这两次真实POST。
- [服务账本](author01-design-evidence/service-journal.json)：自有服务已停止。禁止embedding/model调用的provider只保留原391身份；这证明材料闭环，不证明在线问答。
- 29项Python配置/负例、2项保存响应浏览器、16项Node通过。初次Python因系统temp ACL报错，改用设计专属临时目录后29项全过，未改ACL。精确head Quality CI通过，无未解决线程。
- [旧三主题回放](author01-design-evidence/old-three-replay-journal.json)覆盖三种在职条件×桌面/手机；[东科大考试报告回放](author01-design-evidence/isct-replay-journal.json)覆盖两视口。这些回放全部拦截，不冒充新真实HTTP。
- [31资产只读检查及新候选hash](author01-design-evidence/independent-asset-audit.json)通过，服务后再次核对一致。334/391、旧GSFS、旧配置及M9指纹未改。

代表性独立截图：[桌面中文卡](author01-design-evidence/desktop-essay-card.png)、[手机报告](author01-design-evidence/mobile-essay-report-content.png)。[复制样张](author01-design-evidence/desktop-copy-not_yet.txt)。本地完整原始响应/截图保存在 `outputs/design-author01-review/design-evidence/`；开发精确head证据已随实现提交，未复制大型资产。

## 架构结论：沿用模块，继续减少重复映射

这次真实接入证明“Agent整理已审事实和条件，再交既有程序执行”可用；导入器、条件判断、报告组装和reference服务都不需要新引擎。新增内容是约92KiB的小候选，不是新向量库。

但当前还不是纯数据驱动的接入：作者输入中的中文指南在前端仍有副本，前端含精确目标/snapshot/14片段的静态匹配，以及小论文专用准备控件。它们在此次最小试验范围内、有严格身份校验，不阻塞本包；后续规模化前应优先把重复映射收敛为受校验的展示配置，并保留同一四步页及服务。

来源由设计预先审核，不是盲抽取；没有相同任务旧流程对照，部分阶段和等待时间未捕获，无法给出节省百分比。[开发成本与复用表](author01-implementation-review.md)保留这些限制。建议下一次先验证一项资料能否复用同一整理输入贯通展示，不能以新增专用分支数量当扩展成果。

## 资源与交接

开发累计：新build1/1，真实服务1/2，产品POST2/16。设计累计：服务1/1，产品POST2/8；只读候选校验，不新增build。付费、下载、完整PDF解析流水线、向量构建均0。旧IMPORT/EXAM预算不重置。

#281完成，M17保持开放，本包无新Ready任务。唯一下一步由设计整理这次试验的重复映射与下一小包范围；尚不放行生产实施，不自动扩大到完整普通学生清单、不切换现有在线页。QA、M13及MinerU继续原暂停状态。

回滚：不启用新preview配置时原服务不变；需要回退代码可单独revert #283，保留新候选供审计，不删除或覆盖旧资产。
