# 研究結果の検証段階

RLkitは実行記録の整合性を検査し、Agentの研究上の判断を記録します。
正常に完了しただけで、仮説の正しさ・統計的有意差・一般化を保証するものではありません。

## 1. 計画と実装を実行前に照合する

新しい実装は `implement → implementation_review → execute → review` の順に進みます。
`next`で実行前レビューも取得します。指標、対照、介入、データ分割、seedの5点に、
コードの位置や確認した動作を根拠として記載します。データ分割だけは理由付きの
`not_applicable`を認めます。不一致のある実装を`approved`にはできません。

承認するレビューには `tests` 辞書で `test_*.py` のunittestを提出します。
ランタイムは固定コードとテストを別フォルダへ配置し、テストを実行します。
1件以上の未skipテストが成功し、コード・テスト・入力が変更されていない場合だけ
実験を作成します。期待値は手計算・既知の境界条件などから決め、実装の出力を
写したテストや常に成功するテストを使わないでください。

別の作業票であっても、同じAgentで処理した場合は独立査読を名乗りません。
必要なら `roles.implementation_review` で別のbackend/modelを設定できます。
不承認の実装はプロセスを起動せず、失敗結果として報告します。
テスト実行の失敗は通常の `retry` / `skip-failed` で記録を残して処理します。

実行前レビューは `validation_calls` に記録し、`max_validation_calls`（既定20）で制限します。
研究の実時間上限も守ります。テスト自体は最大60秒・作業の残り時間以内です。
テスト用の小さな条件を使い、探索・確認の評価seedを先に試して選別しないでください。
テスト中の計算は `max_runs` とは別であり、回数上限はAPI料金の上限ではありません。

## 2. 入力データと実行環境を残す

Agentが初期設定の `data_files` に、研究フォルダからの相対パスを登録します。
例えば `{"data_files": ["data/train.csv", "data/test.csv"]}` です。
既存資料なら `imports/source/...` も指定できます。合計100MiB以内に対応します。
リンク、パス逸脱、隠しファイル・状態・コードフォルダ、認証用の鍵は受け付けません。
データが不要な合成計算では空の配列にし、生成規則とseedの役割を実装に記載します。

検証・実験は入力ファイルのハッシュを照合し、作業票ごとの `inputs/` へ固定コピーを保存します。
実装・テストは `os.environ["RLK_INPUT_DIR"]` 配下の相対パスから読みます。
レビュー後に原本が変わった場合は実験を起動しません。実行中の固定入力改変も拒否します。
OSのアクセス制限による読み取り専用サンドボックスではありません。

事前登録にデータの相対パス・サイズ・SHA256、実行設定、Python・OS、
インストール済みPythonパッケージの版を含めます。`environment.json` と
`requirements-lock.txt` も保存します。記録対象の環境変数はスレッド数・GPU選択の3項目だけで、
トークンや環境変数全体は出力しません。Pythonパッケージの一覧は環境全体の記録であり、
OSライブラリ・ドライバ・ハードウェアの完全な再現や自動インストールは保証しません。

## 3. 探索と確認を分ける

通常のサイクルは `exploration` です。閾値に達しても報告・知見には探索段階と表示します。
固定条件での確認を希望する場合、Agentが結果本文の `digest(result)` を提示したうえで、
次の内部入口を使います。利用者にコマンド入力を要求しません。

```console
rlk confirm PROJECT --cycle 1 --experiment e1 --hash RESULT_HASH --seeds 101 102 103
```

完了済み・停止していない研究の、閾値到達した実測結果が対象です。
コード、指標、対照・介入、入力データ、実行環境を維持し、過去に使用・予約したseedを拒否します。
結果の最新ハッシュと実行前検証済みの実装が必要です。確認は追加の1サイクルとして記録し、
時間・作業回数・実験回数の予算をリセットしません。予算不足や条件変更は分岐して扱います。

全seedが完了し、閾値に到達し、レビューもsupportedである場合に、その確認サイクルを
`threshold_replicated`と記録します。それ以外は`confirmation_inconclusive`です。
元の探索結果を確認済みへ上書きしません。新しいseedでの確認は独立したデータセットでの
外的妥当性検証の代わりではありません。事前登録した検定を追加する場合は
[確認実験の証跡](EVIDENCE.md#確認実験の事前登録)を参照してください。旧方式は記述的再確認です。

## 4. 途中結果を報告する

seedが1件以上完了した後に、予算切れ・停止・実行エラーが起きた場合は `partial` とします。
完了済み測定値、完了数 `n`、予定数 `planned_n`、停止理由 `stop_reason` を保存し、
完了済みseedの統計と証跡を照合して報告します。未完了seedは集計へ混ぜません。
途中結果は差が大きくても `threshold_met=false` とし、supportedや確認実験の元には使えません。
1件も完了しなかった場合は従来どおりfailedです。コード・入力の改変は証跡不正として拒否します。

## 5. スキルの動作と有用性を分ける

有効化時は `behavior_validated`（動作検証済み・有用性未評価）です。
事例比較は結果を見る前に、次の内部入口でスキル版、指標、評価方法、改善幅、正常事例と
悪化検出事例、各入力を固定します。

```console
rlk skill-evaluation-plan PROJECT SKILL_NAME --file utility-plan.json
```

計画の形式:

```json
{
  "version": "ACTIVE_SKILL_VERSION",
  "metric": "欠落を正しく検出できた割合",
  "method": "同じ過去入力の判定を、スキルなし・ありで比較する",
  "direction": "maximize",
  "minimum_improvement": 0.1,
  "cases": [
    {"id": "missing", "kind": "normal", "input": {"baseline": 2}},
    {"id": "valid", "kind": "adverse", "input": {"baseline": 2, "treatment": 1}}
  ]
}
```

入口が返した `protocol_hash` を使い、全事例についてスキルなし・ありを実際に比較します。
各評価のJSON証跡に `case_id`, `mode`（baseline / with_skill）, `skill_version`,
`protocol_hash`, `metric`, `input`, `outcome`（評価した出力と判定根拠）, `score` を保存します。
スコアは適用結果から評価し、欠損を架空の数値で補いません。
スクリプト型は実行結果を、文章型は固定した採点基準による出力評価を使います。

`skill-assess PROJECT SKILL_NAME --file assessment.json` に、計画と同じversion・metric・method・
direction・minimum_improvement、protocol_hash、casesを渡します。各caseはid・kindと、
`baseline` / `with_skill` の `{"score": 数値, "evidence": "evaluation/結果.json"}` を持ちます。
両モードと事前計画の入力一致、全事例の記載、証跡とスコア・版・指標の一致を検査します。

1件も悪化せず平均改善幅が事前閾値以上なら `utility_supported`、悪化があれば `regression`、
不足なら `inconclusive` です。証跡を固定コピーで保存し、スキル適用時に改変を検査します。
有用性評価は人・Agentの採点の妥当性を自動証明するものではなく、指定事例での比較です。
悪化した版は `skill-disable` で無効化できます。新たな評価計画は過去の評価を履歴へ保存します。

## 旧データ

旧設定には新項目の既定値を補います。保存済みの実測結果と、既に待機中の旧executeは読めます。
旧executeには未実施の実行前レビューやデータハッシュを後付けで捏造せず、未レビューと表示します。
新しく受理する実装には実行前レビューを必須にします。旧結果の確認実験は、検証済み実装を作る
新しい研究へ分岐してください。
