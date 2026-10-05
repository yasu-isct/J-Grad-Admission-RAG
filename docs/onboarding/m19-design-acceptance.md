# M19：审核输入到配置贯通独立验收

#291 / [PR #293](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/293) **验收通过并合并**。实现 head `9858cf37392ccfb6d403efa0a4a3fb461a224d54`；merge `736e12d48070958e4eaa536ca42d259301a30251`；[独立验收意见](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/293#issuecomment-5995895553)。

## 老师现在能使用什么

东大新领域创成 CBMS、2027修士一般选拔A、2027年4月入学的固定历史新配置有五个材料主题。本轮新增“报考志愿调查表”：中文四步说明、两份原文的关联与全部14片段、独立准备状态和可复制报告贯通原两校四步页面。调查表与小论文互不串状态；个人填写已准备不会改写学校的提交要求，也不证明实际上传或受理。

这仍是有限历史覆盖，不是全东大、完整学生材料清单或当前开放申请窗口。实时表单开放情况、完整字段、具体截止日期/时刻及小论文模板细目仍未核验。没有自动切换用户在线服务。

## 重复配置减少在哪里

此前同一材料需在作者输入、import、policy/plan、来源绑定及前端说明中分别对应。本包以外部设计批准锁定的 author/seed 为输入，经既有 mapper 和完整来源审核器生成新的导入配置、规则/报告绑定、精确 hash/trust、展示目录及字段来源表。中文正文和步骤从同一 reader 派生，页码和原文不手抄进前端。

旧四主题仍保留一份已审语义基底，仅按 lineage 更新新候选对应的来源绑定。有限条件模板消费已审核的显式条件，不从自然语言猜逻辑、不按学校名称分支。旧三主题、四主题和东科大兼容。新开发 trust 已独立复核；生成 hash 不是语义审批，生产启用仍需显式选择配置。

新唯一候选 `d54514a43da772bec2609b364b3e3497d02c9b6388c85712a502c746b5ffbaca`，124,539 bytes；新 snapshot `4237c6f910448b2223e40b2f64ad0e9ee2de1e37bcc6c16596368d9879afa942`。生成配置164,936 bytes；原三个PDF、来源集s1 revision1不变。新51片段由旧37加14组成，不新建向量索引。完整维护位置、入口及限制见[开发交付说明](m19-delivery.md)。

## 独立核验与证据边界

精确提交隔离归档：`outputs/design-m19-review/head-9858cf3`，未切换/修改共享开发目录。原PDF/KB/索引/候选均在原路径只读。

- [三次配置重现](m19-design-evidence/reproducibility.json)，包含另一小型工作目录，与提交文件逐字一致；九种就业组合直接投影正确，唯一原路径候选全部字节一致。程序绑定与来源语义分别检查。开发保存的两次真实HTTP响应及来源目录与重新生成的投影一致。
- 独立32 Python、21 Node通过；覆盖外部批准失配、跨身份/阶段/来源篡改、漂移、合成另一学校与单处编辑传播。额外检查离线wheel内三个新旧目录模块全部存在且与提交字节一致。
- [新五主题双视口独立回放](m19-design-evidence/five-topic-replay/replay-browser-journal.json)：14新增片段、两文件关系与原文返回焦点、两个独立三态控件、指南/报告/真实剪贴板、改资料及换学校清空通过；无JS错误/横向溢出。全部网络被拦截，实际POST0。
- [旧三主题](m19-design-evidence/old-three-replay-journal.json)、[旧四主题](m19-design-evidence/legacy-v2/v2-replay-browser-journal.json)、[东科大考试](m19-design-evidence/isct-replay-journal.json)与[材料报告](m19-design-evidence/isct-materials-replay-journal.json)独立保存响应回放通过，不冒充新的HTTP。
- [保护资产](m19-design-evidence/asset-audit.json)：50个原路径文件hash/大小/mtime与开发前一致，设计验证前后再次一致；[20个受保护仓库输入](m19-design-evidence/frozen-tracked.json)与main相同，其中含15个原保护输入及5个M19设计输入。原334/391、PDF、旧候选/信任、M9不变。
- 精确head Quality CI通过，无未解决审查线程。独立审查结合源码、原来源、可复现产物和最终页面，不以开发自检或测试数量单独批准。

本包真实HTTP证据来自开发精确代码的隔离服务：桌面/手机真实静态GET和报告POST成功，两次200，见[原始记录](m19-evidence/live-browser-journal.json)。设计已将其响应与原PDF新投影逐字核对。

**设计独立服务尝试失败一次**：取证脚本在写入listener事件时重复传入`role`参数，发生在uvicorn启动和HTTP之前；实际成功服务0、产品POST0。这是设计取证脚本错误，不能归为产品失败，也不能宣称独立真实服务通过。失败按Spec计入启动1/1，未重启或重置预算；后续只完成直接投影及保存响应回放。Spec要求的真实闭环已有可核验开发证据，未要求设计必须再跑一次；结合本轮独立交叉核验，证据足以支持此范围的验收。

独立样张：[桌面调查表](m19-design-evidence/five-topic-replay/desktop-application-questionnaire-guide.png)、[手机报告](m19-design-evidence/five-topic-replay/mobile-report-available-not_yet.png)、[报告复制文本](m19-design-evidence/five-topic-replay/desktop-copy-available-not_yet.txt)。完整本地证据 `outputs/design-m19-review/evidence/`。

## 资源与结束点

[原累计账本](m19-design-evidence/resource-ledger.json)：开发候选1/1、服务1/2、POST2/10；设计启动尝试1/1、实际POST0/4。设计启动额度已用完，不能因换聊天/目录重置。付费/下载/完整解析/向量构建均0；设计未发布第二候选。在线问答未测试，用户在线页未切换。

M19要求的来源、工具、真实新材料、旧配置兼容与证据已完成；#291及M19结项，无新Ready，不自动开始下一材料或下一Milestone。M17暂停QA、M13、MinerU保持原状态。

来源事实、中文解释和条件语义仍需审核；有限模板之外的新业务不能冒充已支持。没有同任务盲测或可比人工工时，不宣称提效百分比。回滚仅回退#293代码/展示接入并显式选旧配置；保留全部PDF、KB、索引及候选供核验。
