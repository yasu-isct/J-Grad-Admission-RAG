# ローカルデモの実行

[READMEへ戻る](../../README.md) · [技術解説](engineering-ja.md)

この公開リポジトリは、留学塾の教務支援システムの技術・代表機能を示すデモです。塾内向けのデータ、認証、業務運用設定は公開デモと分けて扱います。後続の業務版は非公開で継続開発する方針です。

## 1. PDFなしでコードを確認する

Python 3.12は現在のCI検証環境です。PowerShellで実行します。

```powershell
git clone https://github.com/yasu-isct/J-Grad-Admission-RAG.git
cd J-Grad-Admission-RAG
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,service]"
python -m pytest tests/test_m19_configs.py -q
```

このテストは小さな合成資料で、入力承認、設定生成、改変検出、別学校への適用、旧設定互換を確認します。実PDF・モデル・有料APIは不要です。Python依存の初回取得は別途ネットワークを使います。

## 2. 指定版PDFで東京科学大学デモを用意する

任意のPDFを渡して自動対応するデモではありません。対象は既定の「2027年4月／2026年9月入学・修士課程学生募集要項」です。対応する公式PDFを手元に持っている場合のみ進めます。

- [学校の募集要項案内](https://admissions.isct.ac.jp/ja/013/graduate/guideline)で版を確認してください。現在掲載されている最新ファイルが同一とは限りません。
- 固定PDFのSHA-256：`57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735`。
- PDFやモデルのバイナリはリポジトリに同梱せず、自動ダウンロードもしません。
- 以下のパスは例です。手元の絶対パスに置き換えます。

初回構築だけを明示的に許可する例：

```powershell
$guideline = 'D:\your-data\isct_2027_4_2026_9_master.pdf'
$demoWorkspace = 'D:\your-data\jgrad-demo'
Get-FileHash -LiteralPath $guideline -Algorithm SHA256

jgrad-demo --pdf $guideline --workspace $demoWorkspace --allow-runtime-build
```

起動完了後に `http://127.0.0.1:8000/app` を開きます。終了は `Ctrl+C`。ポートが使用中なら `--port 8010` などを明示します。

**この標準の初回構築は `deterministic-fake` 埋め込みを使うオフライン動作確認です。意味検索やオンラインAI回答の品質を示すものではありません。** 誤解を避けるため、デモの起動ログのproviderとsemantic表示を確認してください。

次回からは同じ資産を再利用します：

```powershell
jgrad-demo --pdf $guideline --workspace $demoWorkspace
```

通常起動は再利用のみです。存在しない・読めない・互換性がない資産はエラーにし、別の場所へ勝手に再構築しません。自動的に `--rebuild` を付けて回避しないでください。既存の334回帰基準と391製品索引は別の役割を持ちます。

## 3. BGE-M3を使う場合

既に対応モデルキャッシュを用意していることが前提です。新しいモデルの取得手順とは分けています。

```powershell
python -m pip install -e ".[service,embedding]"
jgrad-demo --help
```

BGE-M3の既存workspaceを再利用する例：

```powershell
$semanticWorkspace = 'D:\your-data\jgrad-bge-runtime'
$modelCache = 'D:\your-data\reviewed-model-cache'

jgrad-demo --pdf $guideline --workspace $semanticWorkspace `
  --embedding-provider bge-m3 --embedding-cache $modelCache
```

モデルは `BAAI/bge-m3`、revision `5617a9f61b028005a4858fdac845db406aefb181`、1,024次元に固定。cache-onlyで読み込みます。初めて意味索引を作る場合は、既存資産と分けた明示的なworkspaceで初回構築を行います。既存の固定索引を上書きしないでください。

## 4. 東京大学の限定5テーマ

M19は既存3テーマ・4テーマ設定を残し、新しい5テーマ設定を明示的に選びます。必要なのは、指定した3つの公式PDF、レビュー済み候補、生成設定、reference workspace設定です。通常の東京科学大学デモ起動だけで有効になるわけではありません。

[固定入力と操作入口](../onboarding/m19-delivery.md)、[設定生成の設計](../onboarding/m19-authoring-to-config-spec.md)、[受入済みの範囲](../onboarding/m19-design-acceptance.md)を参照してください。既存の試験用サービス起動器は累積予算付きであり、汎用ランチャーではありません。過去の検証コマンドを新しい実行枠として繰り返さないでください。

`jgrad-demo --help` には既存reference workspaceを指定する `--reference-workspace-config` オプションがあります。完全に検証済みの設定ファイルを明示して使用します。パスの探索や「最新ファイル」の自動選択はしません。

## 5. 任意のオンライン参考回答

構造化表示・書類照合・レポートは、生成APIなしでも利用できます。オンライン参考回答は対応するproviderを明示し、サーバー側のAPIキーを設定した場合だけ有効にします。有料APIの利用料が発生し、標準CIでは実行しません。

設定と責任範囲は [Adaptive local QA](../adaptive-local-qa-v1.md)、[DeepSeek adapter](../deepseek-responses-provider-v1.md)、[参考回答の仕様](../natural-language-productization-v1.md)を参照してください。キーをGitやスクリーンショットに含めないでください。

## よくある確認点

| 症状 | 確認すること |
| --- | --- |
| PDFのhashが一致しない | 学校・年度・改訂版が固定対象と同じか |
| runtimeがない | 初回構築が必要か、既存workspaceの指定を間違えていないか |
| Access denied | 指定した既存資産を読めるか。再構築で回避しない |
| 意味検索にならない | provider、モデルrevision、semantic表示、使用中の索引 |
| 東京大学が表示されない | 検証済みreference workspaceを明示したか |
| 画面とREADMEのスクリーンショットが違う | 起動したコード版・設定版と、画像に付いた検証記録 |

サービスは `127.0.0.1` に限定した公開デモ用構成です。インターネット公開用の認証・運用構成は含みません。業務版への組込みは別の運用設計として扱います。


