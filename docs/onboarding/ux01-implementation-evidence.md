# UX-01 开发验证：报告反馈与更换学校

对应 [#247](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/247)。本次只改两校四步页的操作反馈和返回入口；报告、规则、数据通路沿用原实现。

## 定位与复用

| 已有资源 | 实际复用位置 | 必要差异 |
| --- | --- | --- |
| `generateReferenceReport`、`renderReferenceReport`、`legacyReport`、报告选题与复制 | `service/static/app.js` 的第二、四步按钮和原报告窗 | 两处按钮旁同步显示等待、成功、失败和重试状态；早退说明原因；等待时屏蔽重复请求。 |
| `edit-target`、`activateStep`、`handleDemoTargetChange` | 原第一步选择器和第二至四步的当前目标栏 | 点击“更换学校”只打开第一步；实际更改目标时仍走原有失效与清理。 |
| 两校 `/v1/reference-targets`、基础要求、个人对照、GSFS 报告及关系窗口 | 原四步页面和原服务端接口 | 不改 Schema、报告正文、材料义务或关系响应。 |
| #239 保存的 ISCT 报告复制投影、#240 原文绑定、UI02 保存真实响应 | 浏览器回放与一次真实服务闭环 | 同一响应比对原版和当前页面，保持复制文本一致。 |

用户遇到的“报告按钮像假按钮”尚未在保存真实响应的原版页面复现：原版第二步无个人信息和第四步个人结果均可打开报告。静态核查确认，第四步按钮触发失败时，旧状态只写在第二步的 `reference-inline-status`，用户在第四步看不到就近说明；等待期间按钮虽禁用，缺少明确的等待文字。实际部署版本或当时接口故障仍未确定。本次修正这两个可确认的可见性缺口，并保留原报告生成与复制流程。

更换学校原来需要寻找第一步的“修改目标”入口。现在第二至四步顶部显示学校、专业和“更换学校”，手机布局也可见。只打开选择器不会清除输入；实际更改身份才清除旧目标的基础要求、个人对照、报告、问答和原文窗口。旧异步响应继续由原有请求 ID 和 AbortController 拦截。

## 保存响应回放，非真实服务请求

脚本：[ux01-browser-replay.py](ux01-browser-replay.py)。来源：`outputs/ui02-real/final-head-cd09bd4` 的 ISCT 基础要求、个人对照和 GSFS 报告响应，`evidui01-evidence/gsfs-evidence-real.json` 的关系响应，`report02-evidence` 的 ISCT 复制文本。原版静态文件来自 main 基线 `3cdc26e8ebbec73a81de9cf4a1c7f90932e2021f`；当前静态文件来自本分支。两版均用同一批保存响应。

记录：[replay-journal.json](ux01-evidence/replay-journal.json)。原版和当前版的 ISCT 第二、四步报告均能打开，选题后的复制与保存投影逐字相同。当前版还回放 ISCT→GSFS→ISCT：打开学校选择时原输入保留，实际切换后旧报告清空，GSFS 关系窗口和报告可打开，再切回无串校。GSFS 报告用受控延迟及 503 回放验证立即反馈、重复点击无第二个请求、失败不假成功、原输入保留且能重试。合成浏览器测试另覆盖输入变化和迟到响应失效。

代表性前后图（1440 与 390 分别为桌面、手机）：

| 步骤 | 原版 | 当前版 |
| --- | --- | --- |
| 第二步无个人信息 | [桌面](ux01-evidence/before-step-2-panel-1440.png) · [手机](ux01-evidence/before-step-2-panel-390.png) | [桌面](ux01-evidence/after-step-2-panel-1440.png) · [手机](ux01-evidence/after-step-2-panel-390.png) |
| 第四步个人结果 | [桌面](ux01-evidence/before-readiness-panel-1440.png) · [手机](ux01-evidence/before-readiness-panel-390.png) | [桌面](ux01-evidence/after-readiness-panel-1440.png) · [手机](ux01-evidence/after-readiness-panel-390.png) |

补充状态图：[手机等待](ux01-evidence/after-report-wait-390.png)、[手机失败与重试](ux01-evidence/after-report-failure-390.png)。截图是保存响应回放，不能当作真实接口故障记录。

## 真实服务闭环

使用现有 391 runtime 和 GSFS 配置，只读验证保护资产前后 SHA-256；独立临时端口由脚本持有并停止。脚本：[ux01-real-browser.py](ux01-real-browser.py)，记录：[real-journal.json](ux01-evidence/real-journal.json)，[真实手机第四步](ux01-evidence/real-isct-step4-mobile.png)。执行代码 head `dbab65e86a869900e91d98fc9e1a69d82f4111d2`：1 次服务启动并正常停止，基础要求与个人对照 POST 合计 3 次、GSFS 报告 POST 1 次、其他 POST 0 次、付费调用 0 次。31 项保护资产前后大小和 SHA-256 全部相同。较早的普通权限预检因 391 runtime 的 `.jgrad-demo-owned.json` 无读取权限而中止，未启动服务；随后仅以提升权限完成只读预检和单次闭环，未改 ACL。

真实闭环从 `/v1/reference-targets` 的两个目标进入：ISCT 第二步无个人信息报告和第四步个人结果报告均打开、聚焦，复制文本分别逐字匹配 [无个人信息](report02-evidence/isct-no-profile-after-copy.txt) 与 [已有对照](report02-evidence/isct-with-profile-after-copy.txt)，本地投影不发 POST。原个人材料状态经实际个人对照响应呈现；只打开学校选择器时输入不变，切到 GSFS 后旧报告及字段清空。GSFS 关系图能打开原文并返回，报告响应与既有保存响应一致；再切回 ISCT 无串校。真实会话未模拟服务故障，等待、失败与重试结论仅来自受控回放。

## 定向检查

`pytest tests/test_ui02_browser.py tests/test_reference_workspace_browser.py tests/test_ux05_ui.py -q`：11 passed。`node --test tests/unified_core.test.mjs`：5 passed。`node --check app.js`、`ruff check`、`ruff format --check`、`git diff --check` 均通过。精确 PR head 的 CI 在 PR 创建后核对。
