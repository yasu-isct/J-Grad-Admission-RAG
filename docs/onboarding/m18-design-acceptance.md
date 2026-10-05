# M18：可复用资料交付包独立验收

2026-10-05，#285 / [PR #289](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/289) **验收通过并合并**。
实现 head `0aa1388c9e77b5f27d077125268c395dbcfeb196`；merge `5b3c9a43ba617b7afaa66f9615ed851eebec1ec9`。[独立验收意见](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/289#issuecomment-5990589373)。

## 实际成果

原两校四步页继续使用已有服务和规则。东大固定历史 v2 四主题共用生成展示目录：普通小论文、带就业条件的在职计划书、跨文件英语说明，以及检查表。小论文中文指南、完整身份、原文匹配及控件名称不再手抄进前端；修改同一作者指南即可派生页面、原文说明和报告。

这解决的是“已审核资料如何少重复配置地交付给使用者”。不是自动审核新 PDF、完整普通学生材料覆盖、全东大接入或规则引擎替换。条件仍由原 policy/plan 执行，身份、来源及逐字段引用继续校验；原 v1 三主题及 ISCT 路径保持兼容。

## 独立证据

审查使用精确 head 隔离归档 `outputs/design-m18-review/head-0aa1388`。没有 checkout/reset/stash 开发目录；资产按原路径只读，没有拷贝大型资产。

- 对原三 PDF、原 v2 候选和审核配置执行完整 loader 的只读 `--check`，与提交静态产物逐字一致：25,931字节，content_id `b45639b3a74c10b53dad30a187d6cc33517918005e5e4d2322eac6841afca8c5`。约0.047秒仅是这次展示校验时间，不是完整新来源接入工时。
- 独立25项Python、18项Node通过。包括完整loader合成跨学校、单处指南编辑同步、身份/来源篡改负例、缺模块恢复、只读漂移检测、离线wheel的JS与JSON静态资源闭包。
- [真实桌面/手机闭环](m18-design-evidence/live-browser-journal.json)：最终代码独立服务一次，真实报告POST两次均200。4主题、37片段、原文往返焦点、三态准备、预览及真实剪贴板复制、换学校清空通过；未拦截产品请求。测试服务已停止。
- [实际静态模块GET](m18-design-evidence/static-http.json)为200，字节与已审模块一致，CSP/no-store保留。
- [旧东大三主题](m18-design-evidence/old-three-replay-journal.json)三条件×双视口与[东科大考试报告](m18-design-evidence/isct-replay-journal.json)双视口独立回放通过。这些回放全部拦截，不冒充新的真实HTTP。
- [保护资产核验](m18-design-evidence/asset-audit.json)：50个原路径文件与开发前hash/大小/mtime一致，设计真实服务前后再次一致。15个受保护仓库输入与基线main逐字一致；不重签M9、不改变334/391、原PDF、候选和受信配置。
- 精确head Quality CI通过、无未解决审查线程。开发前后样张、九就业组合、三次可复现生成和合成单字段编辑的证据已结合源码核验，详见[开发完整成果](m18-completion-and-gaps.md)。

独立样张：[桌面材料卡](m18-design-evidence/desktop-essay-card.png)、[手机报告](m18-design-evidence/mobile-report.png)、[复制文本](m18-design-evidence/desktop-copy-not_yet.txt)。完整独立请求响应保存在本地 `outputs/design-m18-review/evidence/`，不另建知识库。

## 资源、限制与交接

[累计原账本](m18-design-evidence/resource-ledger.json)：开发服务1/1、POST3/4；设计服务1/1、POST2/2。付费、下载、完整PDF解析、新真实候选、KB及向量构建均0。设计服务已停止；用户在线服务未切换，本轮不验证在线问答。

必需成果全部完成，#285完成，M18收尾关闭。M17中暂停的QA保持原状态，不连带关闭。没有新Ready任务；后续由设计依据本试验整理新的资料接入范围，再形成下一成果包，不自动开启下一里程碑或扩大生产覆盖。

真实内容仍只限已审2027修士一般选拔A、2027年4月入学历史四主题。小论文模板字数/版式细目、精确截止时间仍未知。新来源的事实整理、中文解释、条件与例外审核仍需人工；生成和hash校验不证明语义正确。没有盲测或可比工时，不宣称节省百分比。

回滚：回退#289的生成器/静态目录/展示接入，保留全部PDF、候选、KB、索引及旧配置。[使用说明](m18-delivery/README.md)提供生成、只读校验和独立预览入口；预览预算已用完，后续不能把换聊天或换目录当作新额度。
