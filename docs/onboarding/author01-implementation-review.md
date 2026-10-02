# AUTHOR-01 开发实现与验证交接

Issue [#281](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/281)；最新设计 main `6336d5090ef82f1ece35938844599012238af58c`。
工作区 `D:/J-Grad-Admission-RAG/outputs/author01-worktree`，branch `codex/author01-essay-onboarding`。
M17 Main 开发自检，独立设计验收待进行；单个非Draft PR，不合并、不切换既有在线服务。

## 来源、身份与真实候选

沿用设计提供的 [revision2 seed](author01-essay-evidence-seed-v2.json) 与 [来源审核](author01-source-review.json)。开发只读核对原PDF hash；14新增片段的人工转录与适用范围已有设计审核。PDF/source-set `s1` 不变，seed revision=2；派生build、plan、snapshot均为新的身份。

| 项目 | 精确SHA-256／身份 |
| --- | --- |
| seed／新设计pin | `96b5944a18e24cb2f65020dd3e7affb909522322ab8172ca5d9b375c56aea5ab` |
| import config | `66ded26e0d840857bba1310cb5d4e895c0584c402fd66b995dc29e6a19c6f271` |
| candidate build | `7ea490375de4c28859ca38dd76bb3952aa8b3d601aa3ccc9eeb5f4ee93cad752` |
| policy | `ac136e5cfb4db7e805f8584184168de1da9e287994f55bbc0698571d41856f5e` |
| plan | `f49717f2cb30ada799f51056d9c78808f25e152b69a3843ac4cadd2b836ff576` |
| 实际reference snapshot | `a729b19705be68c9a4e79bc71d6dbaaed12710989aeac79b90cf34347bf89164` |

新候选在共享资产根的全新build目录内，五个文件共94,232字节（最多8MiB），不是向量库副本。第一次现有 `publish_candidate` 返回 generated，第二次同输入返回 reused，五文件hash及mtime完全一致；单次0.031／0.032秒，峰值工作集91,537,408／91,713,536字节，均低于60秒／1GiB。每个新旧片段逐字、页码、Fact／Unit、PDF／KB／文本hash在[映射](author01-field-source-map.json)中；旧8记录／23片段／5关系逐结构保留。

## 实际复用和必要差异

[详细表](author01-field-source-map.md)列出已有资源→复用位置→必要差异。生产导入器、`material_conditions.py`、`material_slice_report.py`、`reference_workspace.py`均保持原代码：新增配置使用既有全员all＋空predicates；旧主题业务字段保持，仅对新KB重新绑定hash。

前端改动限原四步页：动态主题数，精确机构／项目／年度／路线／批次／snapshot及14原文片段约束的中文指南，通用“补充说明”关系标签，已有材料指南／原文返回／简洁报告投影。准备状态使用既有unknown／available／not_yet语义，只是本页自报；POST合同不加必填项，自报不改服务器submission_required。条件改变继续清旧结果；仅准备自报修改复用已验证的同目标、同在职条件结果。

## 真实HTTP与保存响应回放分别记账

- [真实服务账本](author01-evidence/service-journal.json)：自有offline loopback服务1次；真实POST2次，全部200。使用原391 runtime、原PDF路径和唯一新候选；embedding provider仅暴露原索引身份并拒绝调用，未运行检索／模型，不证明问答恢复。
- [真实catalog](author01-evidence/live-catalog.json)、[真实evidence](author01-evidence/live-evidence.json)：新配置实际GET为4主题／10记录／37片段；snapshot与上表一致。来源浏览和填写本身无POST。
- [桌面请求](author01-evidence/live-desktop-request.json)→[真实报告](author01-evidence/live-desktop-report.json)：在职条件均未知，小论文matched／submission_required；[手机请求](author01-evidence/live-mobile-request.json)→[真实报告](author01-evidence/live-mobile-report.json)：目前不在职，小论文仍需提交，在职计划书本规则不适用。
- [首轮partial记录](author01-evidence/live-browser-first-attempt.json)：真实桌面闭环成功后，测试脚本要求复制文案必须含“已提交”字面值而停止。实际有学校受理边界，收窄断言；后续桌面使用保存响应，未重复POST。另修验证脚本CSP等待字符串，均不改产品规则。
- [完成真实／混合执行记录](author01-evidence/live-browser-journal.json)与最终[四主题保存响应回放](author01-evidence/saved-four-browser-journal.json)分开：后者报告POST全部拦截。正常修改入口→自报三态→明确核对→报告，以及重载清空均用真实保存响应验证。
- [旧配置回放](author01-evidence/old-three-replay-journal.json)：已有实际三主题evidence及 `outputs/display-01/real-run-2/real-report-{1,2,3}.json`，三种在职情况×桌面／手机；仍3主题，无小论文控件，无新增实际POST。
- [东科大回放](author01-evidence/isct-replay-journal.json)：已有信息工学系v2真实基础要求＋已验收review overlay，桌面／手机仅考试报告可复制，两份复制hash一致，无新增实际POST。此回放证明展示兼容，不替代此前真实来源与后台验收。

代表性截图及文本：

| 页面 | 桌面 | 手机 |
| --- | --- | --- |
| 小论文中文卡 | [卡片](author01-evidence/desktop-essay-card.png) | [卡片](author01-evidence/mobile-essay-card.png)、[下半部分](author01-evidence/mobile-essay-card-bottom.png) |
| 关系／全部原文 | [关系](author01-evidence/desktop-essay-relations.png)、[E09](author01-evidence/desktop-E09-source.png)、[E10](author01-evidence/desktop-E10-source.png) | [关系](author01-evidence/mobile-essay-relations.png)、[E09](author01-evidence/mobile-E09-source.png)、[E10](author01-evidence/mobile-E10-source.png) |
| 核对／报告 | [核对](author01-evidence/desktop-essay-readiness.png)、[报告内容](author01-evidence/desktop-essay-report-content.png) | [核对](author01-evidence/mobile-essay-readiness.png)、[报告内容](author01-evidence/mobile-essay-report-content.png) |
| 复制文本 | [未知](author01-evidence/desktop-copy-unknown.txt)、[已准备](author01-evidence/desktop-copy-available.txt)、[尚未准备](author01-evidence/desktop-copy-not_yet.txt) | [尚未准备](author01-evidence/mobile-copy-not_yet.txt) |

## 定向检查与CI

`test_author01.py`29项覆盖纯37片段映射、旧对象不变、新pins与pure mapper一致、真实配置生成函数→现有条件evaluate→公开assemble／renderer；6种错target在证据读取前拒绝肯定结论、缺表头／全员／两段正文、PDF／KB／lineage／plan／seed hash失配，以及同时删除plan与policy绑定并重pin仍拒绝。所有负例使用合成PDF／内存数据，不篡改原件。

已执行相称的现有导入／报告／reference API定向套件：86 passed／4 skipped（Windows symlink）；四步合成浏览器4 passed；新正常修改／核对／复制保存响应浏览器2 passed（桌面／手机，4.15秒）；Node身份／指南／报告16 passed。冻结semantic retrieval及grounded RAG两个gate均通过，未改M9文件、policy指纹、阈值或历史结果。Ruff检查／格式、patch空白通过；最终精确head的正常Quality CI在PR／Issue交接中列出，不将本地自检写成设计验收。

## 绝对成本与限制

时间统一UTC（JST＋9）。多人并行整理／测试时间不能相加当作单人净工时；未记录的时刻明确未知。

| 阶段 | 实际记录 | 运行／等待限制 |
| --- | --- | --- |
| 已有来源准备／复用读取 | 设计在10月2日看原页，10月3日冻结14片段；开发读Spec／旧模块及核对3PDF hash | 本次开发开始／结束精确时刻未单独捕获；没有从PDF零起点盲抽取 |
| authoring整理／映射 | 配置作者记录窗口15:47:29–15:49:42；补齐37片段映射至15:51:45 | 包含编辑、工具等待；纯手填／等待未拆分，不能估算节省百分比 |
| 导入发布／复用 | 15:47:35.607–15:47:35.641；15:47:47.343–15:47:47.377 | 两次运行共0.063秒；无第二build |
| 配置finalize | 同候选只读两次，命令wall0.959／1.045秒 | 第二次合并lint，未拆纯读取秒数；RSS未单独记录，不以导入RSS代替其测量 |
| 页面适配 | 复用原卡片／指南／窗口／报告，最终检查点见保存响应账本 | 精确页面开工时刻未单独记录；计时缺口如实保留 |
| 验证／负例编写 | 合成测试编写15:44:55–15:53:38；29项最终运行1秒（命令wall2.20秒） | 首次普通sandbox临时目录失败并终止，提升权限后合成运行；不修改ACL |
| 真实服务／回放 | 服务15:54:26启动；真实HTTP与各次回放起止见独立账本 | 第一次harness断言、CSP等待及正常编辑入口检查返工均用保存响应；失败记录保留，不重置预算 |
| 返工 | 去除全员指南旁的泛化适用条件警告；准备状态从正常修改入口复用同条件结果；脚本断言／等待修正 | 返工包含页面及harness；纯运行与人工排查未完整拆分 |

结论：沿用既有模块，小幅调整配置生成和身份约束展示。现有集合可扩展；成本主要在来源上下文、全部hash重绑、中文重复表达和真实浏览器状态核对。本文不声称节省百分比，也不批准将流程推广为自动事实审核。

## 资源、保护与独立启动

AUTHOR-01开发累计：新build1/1，生成＋同身份复用2次（0.063秒）；配置finalize同身份只读2次；真实服务1/2，产品POST2/16。设计预留仍为1次服务／8POST；旧IMPORT-01、EXAM-02账本冻结不重置。付费API／下载／PDF全解析／向量构建／迁移均0。

31文件保护账本覆盖原391 runtime、旧东大候选、三PDF、东科大PDF、旧v1配置和冻结基线；[before](author01-evidence/protected-before.json)／[after](author01-evidence/protected-after.json)的hash／大小／mtime全部一致。自有服务[峰值观察](author01-evidence/service-memory-observation.json)为160,419,840字节（Python launcher另计5,111,808字节），低于1GiB。未动现有在线网页或其源目录；自有预览已停止，未使用第二次开发启动或设计预留。

从此隔离工作区启动（开发预算最多还剩1次；设计使用独立预留，启动前须核对账本）：

```powershell
$env:PYTHONPATH = 'src'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
& D:/J-Grad-Admission-RAG/.venv/Scripts/python.exe docs/onboarding/author01-serve-preview.py
```

入口由控制台输出独立loopback端口，模式是offline，新preview只引用本次全新配置、唯一candidate和原PDF路径；未传新配置的旧服务继续3主题。换审查工作区时仅生成新的本地preview路径配置，不更改hash绑定内容、不重复build、不切换原8000。全部生产Schema与reference_only边界保持。
