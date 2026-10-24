# 開発証拠の画像アーカイブ

2026-10-25 時点の main `d94fd4c953aee1b6bfee987eb7777246d6f19737` にある
過去の画面証拠を [GitHub Release](https://github.com/yasu-isct/J-Grad-Admission-RAG/releases/tag/development-evidence-20261025)
へ移しました。公開デモや README の作品紹介画像は引き続きリポジトリ内にあります。

## 対象と選択理由

| 対象 | ファイル数 | 元の容量 | 扱い |
| --- | ---: | ---: | --- |
| `docs/onboarding/` 内の PNG | 319 | 47,681,449 bytes | Release の個別画像と ZIP に保存 |
| `outputs/ux04/`、`outputs/ux05/` | 14（PNG 12、JSON 2） | 2,639,166 bytes | 同じ Release に保存 |
| `outputs/parser-pilot/mineru-4.0.7/` | 2 | 14,438 bytes | 文書・実行手順から参照されるため保持 |

全リポジトリの PNG は移行前 350 枚です。うち onboarding の 319 枚が対象で、
名前が `*-evidence` ではない `ui02-checkpoint1` の 10 枚も同じ過去証拠として含めました。
残る作品紹介画像 19 枚は移動しません。`.gitignore` は変更しません。

Release を選んだのは、過去証拠を通常の checkout から外しつつ、追加の Git LFS 設定なしに
文書から個別画像を表示し、必要時には一括で復元できるためです。
[GitHub の Release 仕様](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
では 1 Release 当たり 1,000 assets、各 asset は 2 GiB 未満です。このアーカイブは 335 assets です。
履歴は書き換えていません。したがって、**過去履歴を含む full clone の容量は直ちには減りません**。
移行後の checkout、ソース配布、shallow clone の対象が軽くなります。

## 確認・復元

- [一括 ZIP](https://github.com/yasu-isct/J-Grad-Admission-RAG/releases/download/development-evidence-20261025/development-evidence-20261025.zip)
  は元の相対パスを保持します。既存の作業ファイルに上書きせず、空の別ディレクトリへ展開してください。
- ZIP の SHA-256: `d189e01742ce94af9c0074d0fc54fdbaca27023ecdfc53af40a216f0dad04916`。
- [パス・個別 URL・サイズ・SHA-256 一覧](evidence-archive-manifest.json) と
  [Release 上の同じ manifest](https://github.com/yasu-isct/J-Grad-Admission-RAG/releases/download/development-evidence-20261025/manifest.json)
  で各ファイルの完全性を確認できます。
- 各画像も個別 asset として保存し、文書中の 202 か所の画像リンクを更新しました。
  JSON の実行記録に書かれた当時の保存先は書き換えず、manifest で旧パスから辿れます。
- `outputs/ux04`、`outputs/ux05` には、追跡済み Markdown/HTML/RST 文書からの参照はありませんでした。
  当時の生成スクリプトは出力先を引き続き使用でき、生成物は従来どおり Git の対象外です。
- parser pilot の `execution-lock.json` は `mineru-4.0.7-pilot-report.md` から参照されています。
  `config.yaml` は `mineru-4.0.7-pilot-audit.json` と `tests/run_parse01_pilot.py` に関係するため保持しました。

コード・文章・JSON の監査記録は削除せず、今回外に移した旧 `outputs/` の JSON も ZIP にそのまま保存しています。
公式 PDF、KB、ベクトル、モデルはこの Release に含みません。
