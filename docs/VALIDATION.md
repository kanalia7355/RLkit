# 検証記録 — 2026-09-11

## v0.5 — 既存研究の取り込み

資料選択・プレビュー・コピー・確認済み回答の引継ぎ・不足質問・次計画への接続を追加。
元資料のバイト一致、取り込み時にコードを実行しないこと、未採用の状態から開始すること、
プレビュー変更・パス逸脱・除外対象・サイズ超過・重複・選択済みセッションの拒否を検査する。
コピー中断後に部分研究が一覧へ出ないこと、実際のAgent入口での取り込みも検査対象。
既存51件とインポート8件の計59件。動作実証では取り込み後の新しい計画採用から実プロセスを実行する。

```console
python tools/verify_release.py --archive dist/research-loop-kit-0.5.0-source.zip --wheel dist/research_loop_kit-0.5.0-py3-none-any.whl
```

対象はローカル資料のスナップショットと研究文脈。既存プロセス・外部ツールDBの復元は含まない。

## v0.4 — 報告会用報告書・承認付きスキル育成

Windows / Python 3.10.6で51件成功。同梱18スキルの形式検査も成功しました。
v0.3の41件に、報告書と育成の境界10件を追加しています。

- 報告会用Markdownの実測値・手順・証跡と、完了ゲートへの組込み
- 4種類のAgent用スキル配置にreferences本文を含むこと
- 設計の別承認、古いハッシュ・未承認資源・references欠落・参照リンク欠落の拒否
- 実装コードを実際にテストし、不合格版は未反映、再試行成功版のみ有効化
- 後続作業票への適用、無効化後の除外、検証後に改変された版の読込拒否
- 設計改訂後の古い実装の再試行拒否と、新しい設計の承認待ち
- 研究期限後のスキル承認、研究一時停止を維持したスキルだけの再開
- 再セッションのimproveモードで研究実験の起動を拒否

AI応答はデモ用固定応答。生成スキルの検証は実Pythonプロセスで3件の正常・欠落・非有限値ケースを実行します。
これはスキルの全場面での判断品質や認証付きAgent UIの実運用を保証するものではありません。

独立配布の検証入口:

```console
python tools/verify_release.py --archive dist/research-loop-kit-0.4.0-source.zip --wheel dist/research_loop_kit-0.4.0-py3-none-any.whl
```

lab_ex外の未インストール入口、全テスト、wheelと資源の一致、2サイクル20実行、報告書、references配布に加え、
デモ候補の承認を模擬して実装・テスト・有効化を検査します。実研究の承認を代行するものではありません。

## v0.3 — スキル適応・Markdown報告と完了ゲート

Windows / Python 3.10.6。41件のテストが成功しました（既存35件＋ガード境界6件）。
同梱16スキルはskill-creatorの形式検査に成功しました。

- 保存済み測定値の改変・実行ログ欠落で、review受理と次サイクルを拒否
- 報告本文の照合失敗で履歴を巻き戻し、修正後の同じレビュー再提出で復旧
- 完了ゲートに知見・分類・比較・履歴・改善候補・問題・報告・検査記録の本文ハッシュを保存
- 実プロセスのseed完了からprogress.jsonを生成
- 未使用設定引数とencoding省略を検出し、バイナリopenを誤検出しない
- 4種のAgent向け16スキル配置と、review作業票への適用を確認

レビュー応答はデモ用固定応答です。三観点レビューの研究上の品質、各Agent製品の実UI起動、
元lab_exの全スキルとの互換性を保証する試験ではありません。移植範囲はSKILL_MIGRATION.mdを参照。

v0.3配布検証の対象:

```console
python tools/verify_release.py --archive dist/research-loop-kit-0.3.0-source.zip --wheel dist/research_loop_kit-0.3.0-py3-none-any.whl
```

これはlab_ex外への展開、未インストール状態のAgent入口、41件のテスト、wheelとのソース・スキル一致、
wheelから2サイクル・20回の実行、新規研究初期化を検査します。

## v0.2 — Agentからの開始と再セッション

Windows / Python 3.10.6で、既存22件にセッション関連13件を追加しました。
合計35件です。未インストールのclone相当フォルダで内部入口を起動し、初回質問、研究作成、
再セッションでの選択待ち、候補を選び直した分岐から実験完了までを試験します。
2つ以上の研究から前回選んだ研究を示す場合も、自動的に選択済みにはしません。

SessionStartのJSON形式・初回表示・コンテキスト圧縮時の扱い・実働Agentの除外を試験しました。
rootのresearch-startスキルは形式検証に合格しています。
各製品の実際の対話UIで自動読み込み・発話が行われることを、この自動試験だけで保証するものではありません。

35件を含む独立配布検証:

```console
python tools/verify_release.py --archive dist/research-loop-kit-0.2.0-source.zip --wheel dist/research_loop_kit-0.2.0-py3-none-any.whl
```

同梱のclone入口をpipインストール前に実行し、起動用指示ファイルとhookの同梱も確認します。

## v0.1で実測した結果（履歴）

環境: Windows / Python 3.10.6。

| 検証 | 結果 |
|---|---|
| unittest結合・境界テスト | 22 passed / 0 failed / 0 skipped |
| 4つの共通スキルの形式検証 | 4 valid |
| wheel生成 | 成功 |
| 元リポジトリ外へZIPを展開してテスト | 22 passed / 0 failed / 0 skipped |
| 独立フォルダへwheelをインストール | 成功、ソースとの同梱コード・スキル一致 |
| インストール済みwheelから動作実証 | 2サイクル / 20 seed別実行 / 15 Agent作業 / complete |
| インストール済みwheelから新規研究フォルダ生成 | 成功 |

テストでは、実際のPythonプロセスによる計算とファイル入出力を使用しています。
active方式のAgent応答は試験用応答、custom方式は試験用の別プロセスです。
4製品の認証付きAI呼び出しを22件の試験に含めたという意味ではありません。

主に検証した境界:

- 基本回答・深掘り回答が欠ける場合の停止
- 未採用の計画、古い提案ハッシュ、未解決事項を含む計画の実行拒否
- 同じ仕事の並列取得防止と、AI同時処理数の上限
- 再起動時の状態保持、古いtoken・完了済み応答の再送拒否
- 試行履歴と失敗ログの保存、予算消費の保持
- 実行seedと測定seedの不一致、非有限値の拒否
- 未支持の測定をsupportedとするレビューの拒否
- ファイルの配置先逸脱、既存研究フォルダの上書き拒否
- タイムアウト、任意CLIとの実ファイル応答契約
- 次サイクルへの結果・知見の引き継ぎ

## 再検証

パッケージ直下で:

```console
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps --wheel-dir dist
python tools/export_project.py --output dist/source-new.zip
python tools/verify_release.py --archive dist/source-new.zip --wheel dist/research_loop_kit-0.4.0-py3-none-any.whl
```

## 未検証・今後の確認

- Codex / Claude Code / Gemini CLI / OpenCodeでの認証付き実運用
- Linux、macOS、Python 3.12の実機実行（WindowsとUbuntu向けCI定義は同梱）
- 任意の実データ、任意の専門分野における研究結論の妥当性
- 実機、人を対象とする研究、多群推測統計、外部サービスの副作用

## 親リポジトリでの作業条件

既存研究のSTATEと進捗を参照しました。作業前のgit-syncによるpullは、既存の未コミット変更により
失敗しました。既存変更の退避・上書き・全件commit/pushは行っていません。
実装と試験成果物はcreate-tools/research-loop-kitの内部、および破棄する一時検証フォルダに限定しました。
既存研究の実験・production状態を進める操作は行っていません。
