# 演示可用性调整前回滚点

2026-09-30 用户要求保存当前网页版本，再制定开发方针。

- 远端固定标签：[demo-before-usability-20260930](https://github.com/yasu-isct/J-Grad-Admission-RAG/tree/demo-before-usability-20260930)
- 代码提交：`29a91ac9280349300c0d1890f48cf9e4244cd68c`。包含 #243、#245；不包含暂停的 QA Draft #236。
- 当前预览：`http://127.0.0.1:8003/app`，工作区 `D:\J-Grad-Admission-RAG\outputs\design-report02`。
- 在线问答：`deepseek-responses` / `deepseek-flash`，重试 0；环境变量提供密钥，不在快照/仓库保存密钥。
- 本地快照：`D:\J-Grad-Admission-RAG\outputs\backups\demo-before-usability-20260930`。
  `manifest.json` 保存 31 个现有资产文件的绝对路径、大小和 SHA-256，以及关键依赖版本；
  `start-original-preview.ps1` 保存当前启动参数，`README.md` 说明恢复步骤。
- 资产：391 runtime 位于 `outputs/m10-09-deepseek-live/runtime-v1`，模型缓存 `outputs/model-cache`，
  双校配置 `outputs/display-01/real-config.json`，官方 PDF `outputs/real_pdf/isct_2027_4_2026_9_master.pdf`。
  334 冻结索引仍为 `outputs/m9-01/index-bge-m3-5617a9f6`，不得替换 391。

## 恢复方式

1. 优先直接使用保留的 8003 预览作为对照。不得在该服务运行时 checkout/reset/stash 它的工作区。
2. 需要重建代码工作区时，在空闲独立工作区检出固定标签，核验 `HEAD` 等于上述提交。
   可用的工作区管理工具优先；工具不可用时才用 `git worktree add --detach <空闲路径> demo-before-usability-20260930`。
3. 使用本地 manifest 核对原资产身份；缺失或不匹配时停止恢复，不复制新索引、不改权限、不重新构建。
4. 复用已安装依赖，将保存脚本中的工作目录与 `PYTHONPATH` 指向回滚工作区，选择空闲端口。
   仅在明确确认归属后停止自己的旧预览；不动 8000/8001/8002/8029 等其他服务。
5. 运行已保存命令；禁止 `--allow-runtime-build` / `--rebuild`。在线密钥通过环境继承。
   启动及只读状态检查不调用模型，用户提交问题才触发在线调用。

这是代码、配置与资产身份回滚点，不是完整环境镜像。未复制 PDF、模型或索引，未保存用户输入、
对话缓存或密钥；不承诺第三方在线模型回答逐字重现。本次保存没有新增付费调用。
