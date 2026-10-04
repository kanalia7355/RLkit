# 同梱スキルと適用範囲

RLkitは27個の共通スキルを同梱します。cloneルートのresearch-startは別の起動用スキルです。
研究初期化時には同梱本文とreferencesを4種類のAgent用フォルダへ配置します。
既存研究のローカルコピーは上書きせず、作業票は現在の同梱版を読み込みます。

## 追加した汎用Agent手順

| スキル | 作業票の段階 | できることと境界 |
|---|---|---|
| wiring-smoke-guard | implement / implementation_review | 入口の到達と設定変更の作用を確認するテストを設計。生成したunittestを既存ランタイムが実行 |
| benchmark-registry | plan / review | 既存の履歴・実測から同条件の比較基準を整理。専用の追記台帳CLIはない |
| repro-checker | plan / implementation_review / review | 固定条件での回帰テストと再実験計画を整理。過去実験の一括自動再実行はない |
| load-controlled-bench | plan / review | 計測区間・環境・同時負荷の条件を計画と実測で照合。OS負荷を自動制御しない |
| cost-label-guard | plan / review | 指標の単位・分母・比較基準を照合。図ラベルを一括走査する専用lintはない |
| figure-toolkit | review / 手動の図作成依頼 | 実測に基づく図の仕様・来歴・目視検証を整理。作業票中の自動画像生成はない |
| ab-test-runner | plan / implement / review | baseline/treatmentを現行のseed対応比較で扱う。独立群検定や多群実行は追加しない |
| contract-test-guard | implement / implementation_review | 実出力を受信側へ渡す境界テストを設計。元研究の通信ブリッジや外部送信は持ち込まない |
| system-doctor | review / 手動診断 | 計画・コード・成果物の不整合を診断。DB変更・自動修復・全環境診断は行わない |

これらは再利用可能なAgent手順として適応したものです。
元研究のスクリプトを丸ごと移植したものでも、新しい自動検査CLIでもありません。
作業票は既存の出力JSONを使い、実行前レビューのtestsだけを既存ランタイムが実行します。
図・台帳などの独立成果物を作るには、通常の作業票とは別にその作成依頼が必要です。

## 既存の共通スキル

研究の入口: research-onboarding、research-propose、research-experiment、research-analysis。
報告とスキル育成: research-report、auto-skill-pipeline。
実行・検証・知識管理: encoding-guard、dead-impl-detector、run-sentinel、run-resume-helper、
report-quality-guard、cycle-completeness-guard、experiment-knowledge-base、experiment-cluster-map、
skill-candidate-detector、experiment-review-panel、seed-power-advisor、multi-exp-comparator。

既存ランタイムの固定入力、実行環境、対照比較、レビュー受理、成果物照合の詳細は
[EVIDENCE.md](EVIDENCE.md)と[RESEARCH_QUALITY.md](RESEARCH_QUALITY.md)を参照してください。

## 対象外

エッジ画像処理・GA・LLM介入などの研究分野専用スキルは同梱しません。
元研究の実験結果、非公開データ、専用評価器、通信・外部投稿の仕組みも配布しません。
図生成、環境の自動再構築、専用ベンチマーク台帳、独立群・多群実験は実装済みとして扱いません。
今後の製品拡張は[ROADMAP.md](ROADMAP.md)に、現行の動作検証は[VALIDATION.md](VALIDATION.md)に記載します。


## 初回起動時の配置

同梱スキルは `agent.py` の起動時（SessionStart hookを含む）にプロジェクト直下へ自動配置されます。既存の研究フォルダも、RLkit経由で開く際に不足するスキルが追加されます。利用者がスキル配置用のコマンドを実行する必要はありません。

配置先は `.claude/skills/`、`.agents/skills/`、`.gemini/skills/`、`.opencode/skills/` です。既存のスキルディレクトリは上書きせず、同名スキルの更新は自動では行いません。CLIが起動中にスキル一覧を更新しない場合は、配置後にセッションを再起動してください。起動hookやAgent入口が実行されない環境では、フォルダを開くだけでは配置処理は走りません。
