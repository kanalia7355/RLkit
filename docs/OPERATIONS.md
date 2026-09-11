# 日常の操作と復旧

v0.2では、利用者はclone先でAgentを開き、会話で研究を選びます。
再起動時の入口は [STARTUP.md](STARTUP.md)、Agent自身の操作はルートのRESEARCH_START.mdが正本です。
以下は既存ランタイムの内部操作リファレンスです。通常の利用者に入力を求めるものではありません。

以降のPROJECTは研究フォルダです。CLIは `rlk` または `python -m research_loop_kit`。

| 操作 | コマンド |
|---|---|
| 状態・計画・仕事の確認 | rlk status PROJECT |
| 未回答の質問 | rlk questions PROJECT |
| 会話で得た回答の登録 | rlk answer PROJECT --file answers.json |
| 設定変更（深掘り開始前） | rlk configure PROJECT --file settings.json |
| 深掘り質問を作る仕事の準備 | rlk deepen PROJECT |
| 深掘り回答後の候補作成 | rlk propose PROJECT |
| 現在のAgentで仕事を取得 | rlk next PROJECT |
| 仕事を完了 | rlk submit PROJECT JOB --token TOKEN --file response.json |
| 提案を修正 | rlk revise PROJECT --feedback "修正したい点と追加回答" |
| 提案を採用 | rlk accept PROJECT --hash HASH |
| 外部CLIで処理 | rlk run PROJECT |
| 計算実験だけを実行 | rlk run PROJECT --experiments-only |
| 新規起動を止める | rlk pause PROJECT |
| 一時停止を解除 | rlk resume PROJECT |
| レポートの再出力 | rlk export PROJECT |
| 不完了の仕事・CLIの所在確認 | rlk doctor PROJECT |

## 失敗した場合

失敗は自動で無限に再試行しません。statusにerrorが残り、実測途中のログやmetrics.jsonも残ります。
依存関係やデータの準備不足なら、それを直してから `rlk retry PROJECT JOB`。
新しいtoken・attemptの仕事になるため、以前の仕事票への応答を流用しないでください。

実装・実行の失敗をこれ以上試さず分析に含める場合:

```console
rlk skip-failed PROJECT JOB
```

結果はfailed / threshold_met=falseとなり、過去の失敗試行は保持されます。
失敗した深掘り・計画・レビューを完了扱いにして先に進む機能はありません。
失敗を解消できない場合はそこで停止します。

## Agentや端末を閉じた場合

runningの仕事は起動時に自動で再実行しません。元のAgentが生きていれば、そのtokenで完了します。
元のAgentと実験プロセスが停止済みであることを確認してから:

```console
rlk recover PROJECT JOB --token TOKEN --reason "元の端末とプロセスの終了を確認した" --process-stopped
rlk retry PROJECT JOB
```

復旧後は古いtokenでのsubmitを拒否します。recoverはプロセスを停止するコマンドではありません。
実験実行時はseed起動前にもtokenを確認するため、回収した古い仕事は次seedを起動できません。
停止確認前の回収は、既に走っている処理と重複するおそれがあります。

## 時間と回数

seedの起動前に予算を予約します。途中で落ちても予算は返却しません。
最初の方針採用からの経過時間には、ユーザー確認や一時停止の時間も含まれます。
pauseは実行済みプロセスの中断ではなく、新規作業と次seedの起動を停止します。
外部CLIと実験プロセスのタイムアウトでは、子プロセスを含めて停止します。

予算を変更して既存の実験を上書き再開する機能はありません。Agentの再開メニューで
「設定を変えて分岐」を選ぶと、前の回答・方針・結果への参照を持った新しい研究が作られます。

## 実験の入出力

作業票の実装応答はPythonファイルの内容をfilesオブジェクトで返します。
ランタイムがそのコードを専用フォルダへ配置し、次の形式で実行します。

```console
python experiment.py --seed 11 --output /absolute/path/to/metrics.json
```

出力はUTF-8 JSONで、次の3フィールドだけを含みます。

```json
{"seed": 11, "baseline": 0.52, "treatment": 0.61}
```

これは形式の例であり、実装は計算から数値を求める必要があります。
NaN・Infinity・boolの数値・seed違い・欠損を拒否します。
Pythonファイルは同じフォルダの補助モジュールに分割できます。
入力データは実装から明示したパスを読みます。ファイル権限の隔離やデータ取得は自動化しません。

各試行に計画とコードのハッシュを保存します。外部データのハッシュや依存パッケージの固定は
研究ごとの実装・環境準備で追加してください。現段階の環境記録はPythonとOSであり、
完全な環境再現を保証するものではありません。
