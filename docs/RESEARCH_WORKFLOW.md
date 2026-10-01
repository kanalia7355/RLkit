# 研究の再開・分岐・検証契約

## データを引き継ぐ分岐

branch / revise / reselectは、新しい設定の`data_files`に登録されたデータを
元の研究から同じ相対パスへコピーする。バイナリとimports/配下の登録資料も対象。
元ファイルへの参照ではないため、分岐後に原本を変更してもコピーは変わらない。
コピー元とコピー先のサイズ・SHA256を照合し、`prior_research.data_manifest`に残す。

srcとデータの継承はstagingで完了させ、その後に研究一覧へ公開する。
欠損、リンク、パス逸脱、初期化ファイルとの衝突、100MiB超、コピー中の変更で失敗した場合はstagingを削除し、
入口の選択を確定しない。必要ならsettingsでdata_filesを変更して選び直す。
未登録のインポート資料全体は自動コピーしない。原研究の履歴・資料の所在は分岐記録に残る。

## 完了済み研究を確認する入口

新規セッションのメニューで「探索結果を固定条件・未使用seedで確認する」を選ぶ。
`diagnostics.confirmation_candidates`に、サイクル、実験ID、結果ハッシュを提示する。
完了・停止していない研究で、実行前検証済みの探索結果が閾値に到達し、
確認用の実行回数・任意の有限時間・Agent予算が残っている場合に選択できる。
候補表示は予備判定であり、confirm時に証跡・実行環境・未使用seedを再検査する。

Agentは未使用seedを会話で確定し、内部入口からconfirmを呼ぶ。
予算はリセットしない。コード・入力・比較条件は元の実行版で固定する。
確認モードのnextはレビューだけを取得し、runは実験だけを実行する。
実装や方針の変更には新しい入口から分岐を選ぶ。

## 状態診断

status / doctor / 再開メニューは同じdiagnosticsを提示する。
残りAgent・実行前レビュー・スキル・seed実行回数、時間の終了時刻、
pending/running/failed作業、取得を妨げる理由、次の内部操作をまとめる。
ジョブ取得の診断は実際の`_claim_blocker`を共有する。
実行中のプロセスは勝手に回収しない。recoverは停止確認とtokenが必要。
表示は状態確認時点の案内であり、操作時の予算・token検査は省略しない。

## 構造化停止条件

新しく生成されるplan作業票は、各実験にstop_policyを要求する。
旧版から引き継いだ作業票や完了済み証跡は読める。stop_policyのない旧実験は
報告で「終了条件の自動検証なし」と表示する。

| kind | 必須項目 | 判定 |
|---|---|---|
| fixed_iterations | max_iterations | 指定回数で終了 |
| convergence | max_iterations, min_iterations, patience, tolerance | 隣接観測差がtolerance以内の状態がpatience回連続 |
| no_improvement | 上記とdirection | 最良値からtoleranceを超える改善がpatience回ない |

max_iterationsは1..100000、min_iterations/patienceは1..max_iterationsの整数。
toleranceは有限の非負数。適応停止も最大回数で必ず終了する。
観測の単位、両条件への適用、固定する対照の計算予算はmethodへ記す。

新しい計画はcomparison_policyも必須。実装は同梱の`rlk_stop.py`のComparisonRecorder.from_environment()で両条件の方針を読み、baseline/treatmentの別conditionブロックで計測する。
旧いcomparison_policyのない実験だけはStopController.from_environment()を使う。
実際の更新・走査ごとにstep(value)を呼び、Trueなら終了する。
ランタイムがこのモジュールを実装へ加え、コードハッシュの対象として保存する。
停止時はtermination.jsonへ方針・回数・理由・観測列が自動保存される。

実行前レビューは通常のunittestに加え、評価seed以外の検証seedで実装を実行する。
停止記録がない・方針と違う・観測列から終了理由を再現できない場合、本実験を開始しない。
本実験の各seedと報告の完了検査でも観測列を再計算する。
観測値の実装との接続はレビューと動作テストで確認する。
任意のPythonコードの隠れた計算や、虚偽の観測値を強制的に監視する仕組みではない。

## 出典と主張の対応

plan.referencesにid/source/claim/relevance/statusを保存し、
各実験のreference_idsで対応付ける。重複ID、未知の参照ID、不正なstatusは受理しない。
statusはunread/read/content_checked。readでは読んだ箇所locatorと要約・限界noteが必要。
資料一覧は方針ハッシュと事前登録へ固定し、報告書に表示する。
readはAgentの読み取り申告であり、出典の実在や主張の外部検証を意味しない。
未読、読了申告、資料未登録のいずれも、報告では外部未検証と明記する。

本文固定・引用一致、確認事前登録、両条件の計測契約は[EVIDENCE.md](EVIDENCE.md)を正本とする。
研究全体は既定で無期限。有限の稼働時間と旧版期限の扱いは[PROJECT_POLICY.md](PROJECT_POLICY.md#無期限の中断・再開)を参照する。
