# UI-02：旧四步流程与双校报告独立验收

2026-09-29。Issue #229 / PR #231，精确 head `cd09bd43abbc276c2f5fb1bc2fdae40aa82eb166`，merge `40cd25d84c15d4ccaace610d5158875632dd428c`。
[唯一独立审查记录](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/231#issuecomment-5882540237)保留检查点1及已解决指摘；[Spec](v1-flow-restoration-spec.md)、[ADR0016](../decisions/0016-restore-v1-flow-with-multi-school-capabilities.md)。

## 复用与产品结果

实际沿用旧 `advanced.html/app.js/app.css/overview.js` 的四步结构、日期时间线、材料卡片、全部个人字段、行动摘要与会话准备勾选，接入已验收 `unified-core.mjs` 的两校目录和报告映射。没有新写第三套主流程。第二步日期／材料默认展开、主栏个人入口显著；对照后焦点进入第四步，先看需补充／待确认／已记录。报告为第二／四步次级可选动作，无个人信息也能导出。

GSFS 仍限历史固定三主题，无日期或完整准备统计时明确不覆盖，问答不可用。正式入口与旧路径沿用原接口；没有规则、Schema、gate、trust pins、KB或索引变更。助手仍 reference_only，M13暂停，#177关闭。

检查点1对比了旧／新桌面日期材料、个人情况、行动摘要、390px页面及局部材料截图。发现物理页／印刷页适配遗漏，并要求合成夹具不再用不匹配输入的固定响应冒充实际映射证明；最终 head 均修复。历史浏览器hash常量只说明旧证据身份，不能代替当前行为验证。

## 独立验证

- **29 个定向测试通过，3 个 Node 测试通过**；3 条 Edge 合成流程覆盖输入与逐项结果、过期响应、切校、重试、问答边界、复制及手机多来源按钮。最终head [Quality CI SUCCESS](https://github.com/yasu-isct/J-Grad-Admission-RAG/actions/runs/36520361489)，无未解决审查线程。
- 独立工作区断言代码head，导入正式CLI使用的factory，临时端口49925。复用并审阅开发者六场景脚本，独立输出、端口、角色与head，追加逐项状态／下一步／限制和手机检查；保留旧成果而非重复构建验收基础设施。
- ISCT 2027无个人信息、有已有／尚未取得／未知信息、2026另一批次各一报告；GSFS unknown/unknown、yes/yes、no/unknown各一报告。GSFS canonical report及Markdown与保留基线逐字节一致；ISCT每项状态及下一步与真实响应一致，个人报告各项标题／下一步／限制同时存在于预览和复制。
- 源原文、物理页28／印刷页26、引用、报告预览与复制、桌面1440和手机390、旧入口200及redirect307均验证。资料浏览不自动POST报告，打开已生成GSFS报告预览不重复POST。
- 25个受保护文件的SHA-256、大小、mtime完全不变；独立服务启动0.469秒，总服务5.110秒，最高采样RSS167288832字节，结束可用内存17207283712字节，自有服务已停止。

代表性截图来自此次独立真实运行，而非合成页面：

- [东科大日期与材料](../assets/ui02/isct-step2-desktop.png)
- [东科大个人准备对照](../assets/ui02/isct-step4-desktop.png)
- [东大手机材料列表](../assets/ui02/gsfs-step2-mobile.png)
- [东大原文物理页与印刷页](../assets/ui02/gsfs-source-desktop.png)

本地原始证据 `outputs/review231-final-real/`：journal、before/after、真实响应、预览／复制和全部截图；开发最终证据 `outputs/ui02-real/final-head-cd09bd4/` 单独保存，不混称独立证据。

## 累计资源与限制

| 资源 | 开发累计 | 独立设计 | 总计 |
| --- | --- | --- | --- |
| 真实服务启动 | 5 | 1 | 6 |
| 显式报告尝试 | 23 | 6 | 29 |
| 基础／个人对照／旧详细POST | 14 | 3 | 17 |
| 真实搜索、在线模型、下载、解析、构建、迁移 | 0 | 0 | 0 |

#229 开发交接记录说明用户追加了开发侧额度；这些累计数保留所有失败尝试，包括一次选择器错误导致点击前终止，不能把开发多次尝试隐藏成最后一次成功。设计未使用开发补充额度，严格使用原预留启动1/1、报告6/6、POST3/10。启动／报告预留耗尽，剩余POST数不授权新启动。UI-01/M15旧台账保持关闭。

真实验收使用只读 embedding identity provider，不加载模型、不做搜索或在线问答；问答显示由合成测试验证，不能声称本轮重新认证检索／模型质量。391原有排序诊断仍披露。用户8000/PID24728及8001/PID30320服务与其源目录未更改，合并不会自动替换其旧页面。新预览需显式切换到已合并源码。

M16在UI-02修正后完成。无下一实施任务Ready，无高亮、新学校覆盖、付费或公网部署授权。
