# 研究を始める・前回から再開する

これは進行役Agent用の手順です。ユーザーには研究内容と選択肢を会話で示します。
ユーザーにコマンド入力、設定JSONの作成、pipインストールを要求しないでください。
clone先には実装とスキルが揃っています。Agentが同梱の内部入口を使います。

報告・不具合・改善候補は研究フォルダのreports内のMarkdownへ保存します。
GitHub Issue作成や外部投稿を既定の研究手順に含めません。問題はISSUES.mdに記録します。
実験監視時は同梱run-sentinel、復旧時はrun-resume-helperのSKILL.mdを読みます。
同梱スキルの移植範囲・未対応はdocs/SKILL_MIGRATION.mdを参照します。
報告会向け成果物はreports/MEETING_REPORT-NNN.md。weekly運転を前提にしません。
再開メニューのimproveは「スキル設計の確認・承認・育成」。完了済み研究でも選べます。
このモードではskill-next/skill-submit/skill-run/skill-accept/skill-revise/skill-reject/skill-disableと
スキル用の失敗・復旧・再試行操作だけを行い、研究の実験は起動しません。
具体的な設計を見せて承認されたら実装・テスト・反映まで続けます。研究方針の承認で代用しません。

## 既存研究を取り込む場合

ユーザーが既存研究の継続・インポートを希望したら、通常の新規テーマ質問を繰り返さず
docs/FOLDERS_AND_IMPORT.mdの手順を使う。元フォルダ、対象資料、現在の方針・進捗を整理する。
import-previewで選択資料を確認し、import-studyで新しい研究へ複製する。
確認済みの基本回答は引き継ぎ、不足項目だけを尋ねる。ユーザーにJSONやコマンド入力を要求しない。
元コードを取り込み時に実行しない。過去結果と今回の実測を区別し、次の計画を提示してから実験を始める。

## 最初の応答

新規セッション、アプリ再起動による再開、clear、会話のforkでは、新しい入口を開きます。
前回の会話にsession_idが残っていても、今回の選択済みIDとして再利用しません。
コンテキスト圧縮だけなら元のsession_idを維持し、状態を確認するだけにします。

1. このファイルのあるclone先を基準に、Agent自身が `python agent.py open` を実行する。
   Pythonコマンド名が異なるOSでは `python3` または `py -3` を使う。pipは不要。
   Python 3.10以上が見つからなくても最初の関心の質問は会話で始められる。
   保存・実験に必要になった時点で環境準備の不足を伝え、勝手に回答を保存済みにしない。
2. `kind=setup` なら「どんなテーマに関心がありますか？ 特に気になることも教えてください」
   と質問を始める。空の選択メニューを挟まない。最初の回答から研究名を相談して決める。
3. `kind=resume` ならprojectsから前回の研究の名前・方針・進捗・直近結果・残り予算を示す。
   複数研究がある場合はlast_selectionの研究を前回として紹介し、今回使う研究を選ぶ。
   last_selectionがなければ前回を推測しない。候補名を省略したIDだけの質問にはしない。
   `kind=setup_resume` なら、前回どこまで答えたかを短く示し、未回答の質問から続ける。
   ユーザーがその質問に回答したらcontinueを選び、回答を登録する。回答済みの質問は繰り返さない。
4. 返されたsession_idをこのセッション内で保持する。選択するまで実験を起動しない。
   入口を毎ターン開き直さず、最初の回答待ちを維持する。
   ユーザーが「前の研究を同じ条件で続けて」と既に選択を明示していれば、その意図で選んでよい。

## 再開時の選択肢

状況に合うものを少数ずつ示し、必要な詳細を続けて尋ねます。自由記述も受け付けます。

| 選択 | 会話で確認する内容 | 保存への影響 |
|---|---|---|
| 続ける | 前回の研究・方針、止まった段階、今回行いたい作業 | 同じ研究。予算・試行をリセットしない |
| 結果だけ見る | 方針、候補、実測、失敗、どの比較を見たいか | 読み取り専用 |
| 方針を修正する | 修正したい点、どの保存版を基にするか | 新しい研究へ分岐し、提案から確認 |
| 候補を選び直す | 保存済み候補の名前・仮説・理由から、採用したい候補を複数選ぶ | 新しい研究へ分岐し、選んだ候補で計画 |
| 設定を変えて分岐 | 引き継ぐ関心・データ、変更する条件と予算 | 回答を引き継いだセットアップへ |
| 別テーマを始める | 新しいテーマと関心 | 以前の研究を保持し、新規セットアップ |

詳細設定では、候補総数、提案ワーカー数、採用実験数、Agent同時数、実験同時数、seed、
サイクル数、時間・試行・AI作業回数、確認頻度、Agent/モデル設定を必要に応じて調整する。
「続ける」は既存条件の継続。「分岐」は新しい予算と未承認の計画になることを説明する。
完了済みや時間上限の研究で、継続できるかのような選択肢を出さない。
runningが残る場合は、処理中か停止済みかを確認し、自動で回収・再実行しない。

## Agentの内部操作

以下をユーザーへの操作案内にしない。会話の意図を受けてAgentが実行します。
全てclone先基準です。`SESSION` はopenで返ったid、`PROJECT` は一覧のidです。

```console
python agent.py select SESSION --action new --name "研究名"
python agent.py select SESSION --action continue --project PROJECT
python agent.py select SESSION --action review --project PROJECT
python agent.py select SESSION --action branch --project PROJECT --name "別条件" --settings .research/settings-draft.json
python agent.py select SESSION --action revise --project PROJECT --name "方針改訂" --feedback "変更点" --plan-job 4
python agent.py select SESSION --action reselect --project PROJECT --name "候補比較" --candidates c2 c4
```

設定ファイルは変更分のJSONをAgentが作る。回答ファイルなども `.research/` 内に保存する。
表示後に別セッションで研究が更新された場合、選択は拒否される。最新メニューを開き直す。

選択後は研究フォルダの `AGENT_GUIDE.md` を読む。ただし、そこでの `rlk COMMAND PROJECT ...` は
全て `python agent.py work SESSION COMMAND ...` に置き換える。projectのパスは入口が決める。
例:

```console
python agent.py work SESSION status
python agent.py work SESSION questions
python agent.py work SESSION answer --file .research/answers-draft.json
python agent.py work SESSION configure --file .research/settings-draft.json
python agent.py work SESSION deepen
python agent.py work SESSION next
python agent.py work SESSION submit JOB --token TOKEN --file RESPONSE_PATH
python agent.py work SESSION propose
python agent.py work SESSION accept --hash HASH
python agent.py work SESSION run --experiments-only
```

これで既存の深掘り・候補生成・提案・実装・実験・レビューへつながる。
同じ方針を続行する選択で、既に採用済みの計画の承認を取り直さない。
その研究がpausedで、ユーザーが続行を選んだ場合は内部のresumeで一時停止を解除する。
分岐は過去結果への参照を残すが、計画の承認と実験予算を流用しない。
別の研究に切り替えたいときは新しいopenで選択する。元の研究は削除しない。

## 起動時の表示と制約

CLAUDE.md / GEMINI.md / AGENTS.mdが自動読み込みの入口です。
Claude CodeとGemini CLIにはSessionStart hookも同梱し、状態に合う挨拶と文脈を注入します。
hookは研究を作成・実行しません。無効化されている場合も指示ファイルから始めます。
Agent自体がユーザー入力まで返答を生成しない場合は、最初の「こんにちは」などで
セットアップ/再開の質問を出します。無入力での自発的な発話を全製品で保証しません。
