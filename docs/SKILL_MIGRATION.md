# lab_exスキルの移植対応 — v0.4

v0.4ではresearch-report（報告会用Markdown）とauto-skill-pipeline（設計承認後の実装・検証・反映）を追加し、計18スキルです。
両スキルのreferences本文も配布・研究初期化・作業票読込へ接続しています。詳細はSKILL_EVOLUTION.md。
以下のv0.3の12スキル一覧はその適応範囲を引き続き示します。

v0.2までは概念を参考にした新規4スキルだけであり、既存スキル群を組み込んだ状態ではありませんでした。
v0.3では下記12スキルの観点を分野非依存に書き直し、同梱・作業票・実行経路へ接続しています。
元のスクリプトをそのままコピーした完全移植ではありません。未実装をPASSとして扱いません。

参照元はlab_exの `.claude/skills/<スキル名>/SKILL.md` です。
独立配布物はそのフォルダやlab_exのコードを必要としません。
適応版は `src/research_loop_kit/assets/skills/` にあり、研究初期化時に4種類のAgent用skillsへ配置します。
既存研究のローカルコピーは自動上書きしませんが、作業票は現在の同梱版を読み込みます。

## 追加した12スキルと実際の接続

| 元スキル / 適応版名 | 適用段階・実装 | 限界 |
|---|---|---|
| encoding-guard | implement作業票、inspect_codeでencoding省略を注意、実行ログUTF-8 | 既存入力データの文字コードを一律変換しない |
| dead-impl-detector | implement作業票、未使用設定引数・同一ファイル内参照なしをAST検出、事前登録へ保存 | 静的な注意喚起。動的配線保証・lab_ex特有のメソッド検査なし |
| run-sentinel | 実行seedごとのprogress.json、経過時間・残りseed・ETA、開始手順から参照 | 世代別収束監視なし。ETAは推定、常駐監視なし |
| run-resume-helper | 開始手順から参照、tokenと試行による復旧・retry、途中成果物保持 | 部分seedを統合して再開する機能なし。新試行は全seedを再実行 |
| report-quality-guard | review作業票、verify_evidenceで数値再読込・集計再計算・ログ存在・登録コード照合 | 自然言語解釈はAgentレビュー。全主張の自動意味検証なし |
| cycle-completeness-guard | review受理時の必須ゲート、Markdown本文一致・ハッシュ記録、失敗時DB巻戻し | MarkdownとDBは単一原子操作ではない。確定はDBイベントで判断 |
| experiment-knowledge-base | ideas作業票、KNOWLEDGE.mdとhistoryを次候補へ渡す | 信頼度の自動推定なし |
| experiment-cluster-map | ideas作業票、CLUSTERS.mdを採用方針の完全一致で分類 | 意味的クラスタリングなし。元の固定GA分類は使わない |
| skill-candidate-detector | review作業票、反復知見・単発知見・ジョブエラーを記録し、毎サイクル最大1件を設計へ接続 | 設計承認後だけ実装・反映。元の全キーワード検出は未移植 |
| experiment-review-panel | review作業票で数値・機序・対照/統計の三観点を適用 | 同一Agentのレビュー。独立3AgentやR4による合議は未実装 |
| seed-power-advisor | plan/review作業票で実験単位・対応関係・必要差と標本数を確認 | 助言のみ。検出力計算・検定未実装。非対応検定の式を流用しない |
| multi-exp-comparator | review作業票、COMPARISON.mdに指標・方向・改善幅・件数を出力 | 異なる研究条件を自動順位付けしない |

もとの4スキル（research-onboarding / research-propose / research-experiment / research-analysis）は継続します。
v0.3の16スキルに前述2つを追加した合計18スキルです。cloneルートには別途research-startがあります。
スキル文の存在だけで実行保証とせず、上表の実装またはAgentの適用範囲を基準にしてください。

## 既存ランタイムで対応している観点

| lab_exの機構 | 汎用版の対応 |
|---|---|
| experiment-cycle / experiment-team / next-experiment-proposer | Engineの段階遷移、設定件数の候補ジョブと並列上限、採用後の実験 |
| state-guard / research-policy-guard / structure-guard | 状態・token・採用ハッシュ・未解決事項・出力パスの制限。元の全規則との互換ではない |
| run-generation / failure-recovery / run-lifecycle-recovery | job/attempt/token、重複取得防止、停止確認後recover、失敗試行保持 |
| entrypoint-resolver / entrypoint-autogen | experiment.pyとseed/output引数を固定。既存実験の入口自動探索はしない |
| log-reality-guard / metrics sanity | 実プロセスからseed/有限数値を取得、コード・事前登録・保存数値・集計照合 |
| session-log-guard / KB freshness / phase_gate | DB履歴からMarkdown生成と本文照合、完了ゲート成功後のみ次段階 |
| integrated-review | 全実験の単一reviewジョブ、失敗・閾値未達のsupported拒否。独立複数レビュー統合ではない |

## 未移植・任意拡張として残すもの

| スキル・機構 | 理由・現在の扱い |
|---|---|
| wiring-smoke-guard | 動的な設定変更効果の試験契約が必要。ASTの注意喚起で代用済みとはしない |
| benchmark-registry / repro-checker | 公式ベンチ登録、過去configの再実行、bootstrap CIは未実装 |
| load-controlled-bench / 環境fingerprint / dataset manifest | Python/OS/コード/seedの登録のみ。負荷制御、依存パッケージ・データ版固定は未実装 |
| cost-label-guard / figure-toolkit / figure-provenance / presentation numbers | 図・発表資料生成と数値照合は未実装。現在は数値とMarkdown |
| helper-adoption-guard | lab_exの共有ライブラリに依存。汎用版に同じimportを強制しない |
| edge-fps-validator / ga-trajectory-golden-test | エッジ画像処理・GA専用。分野拡張で追加する対象 |
| llm-ablation-runner / intervention-cost-accountant / intervention-override-guard | LLM介入を研究対象とする専用比較・コスト測定。汎用標準から除外 |
| regime-registry / meta-fitness-optimizer / prediction-debugger | 元研究固有の状態・評価・予測契約を持つため未移植 |
| ab-test-runner / contract-test-guard / system-doctor | 元のA/B評価・総合診断の全経路は未移植。スキル育成は汎用契約で別実装 |
| weekly系 | 要求対象外のため同梱しない。報告会用research-reportは同梱する |
| poster系 / 論文・スライド出力 | 個別成果物の拡張。現版の既定成果物はMarkdown |
| git-sync / GitHub Issue / Discord連携 | 親プロジェクトの運用を持ち込まない。自動同期・投稿機能なし |

全lab_exスキルの同梱・同等動作を必要とする用途には未対応です。
分野固有の拡張では、対応スキルだけでなく実行契約・失敗テスト・成果物検証も追加してください。

## Markdown報告の契約

研究ごとのreportsにPROPOSAL.md、cycle-NNN.md、cycle-NNN-CHECKS.md、KNOWLEDGE.md、
SESSION_LOG.md、CLUSTERS.md、COMPARISON.md、SKILL_CANDIDATES.md、ISSUES.mdを出力します。
v0.4ではMEETING_REPORT-NNN.md、SKILL_EVOLUTION.md、候補別のskill-sN-DESIGN.mdも出力します。
JSONは機械用の併存形式です。ユーザー向けの既定をGitHub Issueに切り替える設定はありません。
研究上の失敗も本ツールの運用エラーも、外部へ自動投稿しません。

既存のv0.2状態は読み込めます。完了済みの過去サイクルに新しいゲートを通ったと遡及記録しません。
次に受理するreviewからゲートが適用されます。
