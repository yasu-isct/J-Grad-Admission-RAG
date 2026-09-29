# UI-02 检查点 1：旧四步页面复用与合成呈现

本记录供 #229 的设计 Agent 先核对产品呈现。截图都由同一组合成响应在 2026-09-29 的本地 Edge 中生成；它们不是最终真实招生响应或检查点 2 的验收证据。旧版取自设计合并提交 `c4e6d0691c65187a3fec9b4e8af9f4dec804ad00` 的 `advanced.html/app.js/app.css/overview.js`，新版取自本 PR 的四步页面。没有启动真实服务、读取 391 runtime、调用模型或生成真实报告。

## 实际复用映射

| 旧组件 | 复用点 | 本轮必要变更 |
| --- | --- | --- |
| `advanced.html` | 页头、四步导航、选择表单、主栏个人情况、行动摘要、证据弹层、高级工具 | `/app` 直接服务这份 HTML；第二步和第四步加同一参考报告动作；第三步按能力显示原全部东科大字段或东大在职条件。`/app/advanced` 仍直达同页。 |
| `app.js` 的 `renderRequirements`、`renderKeyDates`、`renderRequirementCard` | 保留申请概览、必着时间线、材料卡片、主栏 CTA 与原文入口 | 东科大继续使用原响应；材料区展示所有已审核材料及官方适用性。东大已验收证据映射为旧卡片输入，日期明确“当前资料尚未覆盖日期”。 |
| `app.js` 的 `renderComparison`、`renderPriorityActions`、`applyReadinessFilter` | 东科大原行动摘要、数量、分组、筛选与会话内勾选 | 东大只在同一第四步呈现三主题条件结果，隐藏完整准备统计与筛选，不称材料备齐。 |
| `app.css` 与 `overview.js` | 页面宽度、色彩、响应式布局、概览指标和个人情况入口 | 仅补报告弹层、次级动作、东大两项条件的样式；原日期和材料权重保持。 |
| UI-01 `unified-core.mjs` | 能力目录、双身份范围、证据绑定、基础／个人展示导出及 GSFS byte-bound 报告验证 | 原学校选择控件只建立页面选项投影；东大请求仍使用切片 target 和 profile target，不向旧 API 发送虚构文档 ID。 |

## 同一合成场景的旧／新截图

旧／新均选“第一所学校、修士课程、2027 年 4 月、学院、专业、A 日程”，用同一合成必着日期、材料和三项准备对照。第二所学校为合成的历史固定材料切片，仅用于检查布局和能力边界。截图中的学校名、日期和材料都不是招生事实。

| 视图 | 旧 v1 | UI-02 当前实现 |
| --- | --- | --- |
| 日期／材料，桌面 1440 | [旧截图](ui02-checkpoint1/old-dates-materials-1440.png) | [新截图](ui02-checkpoint1/new-dates-materials-1440.png) |
| 日期／材料，手机 390 | [旧截图](ui02-checkpoint1/old-dates-materials-390.png) | [新截图](ui02-checkpoint1/new-dates-materials-390.png) |
| 个人情况，桌面 | [旧截图](ui02-checkpoint1/old-personal-1440.png) | [新截图](ui02-checkpoint1/new-personal-1440.png) |
| 行动摘要，桌面 | [旧截图](ui02-checkpoint1/old-action-summary-1440.png) | [新截图](ui02-checkpoint1/new-action-summary-1440.png) |
| 东大材料／条件，桌面 | 不在旧 v1 范围 | [三主题材料](ui02-checkpoint1/new-slice-materials-1440.png)、[局部条件结果](ui02-checkpoint1/new-slice-conditions-1440.png) |

## 合成检查与待完成工作

- 本轮合成 Edge 流程验证：两校在原学校下拉框；东科大日期与材料默认显示，主栏入口进入第三步；个人对照后焦点进入第四步，已准备／尚未取得／未知的响应状态和三类计数可见；两步共用报告预览和复制；东大无日期、三主题、无完整准备统计、问答不可用；浏览与选择不发报告 POST；手机无横向溢出。
- 当前定向 Python/浏览器检查 26 项通过。旧高级工具、正式入口、离线 wheel 依赖闭包通过合成检查；旧 v1 脚本仍作为页面脚本，而非另写一套主页面。
- 请设计 Agent 先核对布局、日期／材料与个人入口的主次、东大无日期和局部准备说明。检查点 2 才做完整竞态、失败、问答边界、精确 head 真实浏览器和保护资产前后身份核对。UI-02 额度累计仍为启动 0/2、报告 0/12、基础／对照／详细 POST 0/20、真实检索 0。
