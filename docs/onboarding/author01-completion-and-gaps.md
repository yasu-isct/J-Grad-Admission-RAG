# AUTHOR-01 完成与缺口（供集中设计验收）

任务：[#281](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/281)。
角色：M17 Main；状态：**complete（开发自检），Awaiting review（独立验收待进行）**。
分支：`codex/author01-essay-onboarding`；基底：main `6336d5090ef82f1ece35938844599012238af58c`。
精确提交与 CI 以同一 PR／Issue 原交接记录为准；本文不声称设计验收通过。

## 用户能看到的变化

独立 opt-in 预览保留原两校四步页，在东大固定历史目标中加入**申请小论文**：中文准备步骤、语言／指定格式／两部分写作内容／出愿期间上传 PDF；原文窗口保留两份来源全部14片段及补充关系。可填写未填写／已准备／尚未准备，核对及可复制简洁报告保持官方提交要求与个人自报分开。

新配置显示4个材料主题；原三主题配置保持3个。东科大考试、材料及既有报告组件继续工作。后台引擎、API必填项、M9跟踪文件及指纹未改。

## 完整成果包

- [字段来源与复用表](author01-field-source-map.md)、[authoring输入](author01-essay-authoring-input.json)、[37片段精确映射](author01-field-source-map.json)。
- 全新 import／policy／plan／trust／preview 配置：`author01-*-v2.json`；[重放生成器](../../scripts/author01_generate_configs.py)。
- 唯一新候选：`D:/J-Grad-Admission-RAG/outputs/reviewed-source-candidates/7ea490375de4c28859ca38dd76bb3952aa8b3d601aa3ccc9eeb5f4ee93cad752`，94,232字节，37 Fact／Unit，三文档2／17／18；[生成及同身份复用账本](author01-evidence/candidate-operations.json)。
- [完整验证、成本和启动说明](author01-implementation-review.md)；[真实HTTP／回放及截图](author01-evidence/)。

## 验证与边界

真实 offline 服务1次、真实报告POST2次；桌面／手机完成材料卡、14片段原文、返回焦点、报告和复制。保存响应回放另列，不冒充新增真实HTTP。旧三主题三种在职情况、东科大含考试报告完成桌面／手机回放；三态自报和正常修改路径只复用已校验结论。

定向Python／Node、现有CI及资产保护结果见验证记录。错误目标、缺片段／表头、文件hash失配拒绝肯定提交结论；未知不等于不符合，规则触发不等于申请资格或学校受理。

## 明确保留的缺口

本轮只覆盖东大複雑理工修士一般选拔A、2027年4月历史切片的一项新材料。指定模板未持有，字数、版式细目、具体截止日期／时刻为未知；不接入问卷或完整普通学生清单。来源由设计预先审核提供，不是盲抽取试验，无同任务旧流程计时，不能给节省百分比。

建议：**沿用现有模块，小幅调整整理输入与展示映射**。成本证据中的未计时阶段／等待／返工如实保留；不据本轮自行推广、合并或切换在线页面。下一责任方：设计 Agent，集中核对新信任绑定、目标／事实边界、原文与复制、兼容性及精确head的CI。
