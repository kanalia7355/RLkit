# 研究フォルダと既存研究の取り込み

## 実際に作成される構成

一つのclone先で複数の研究を管理できる。ユーザーが選んだ研究名は状態DBに保存し、
フォルダは名前の重複を避けるstudy-IDで作成する。

```text
RLkit/
└─ .research/
   ├─ sessions.sqlite3                 セッションごとの研究選択
   ├─ import-staging/                  取り込み途中の一時保存先
   └─ projects/
      └─ study-xxxxxxxxxxxx/
         ├─ AGENT_GUIDE.md             Agentの研究操作手順
         ├─ AGENTS.md / CLAUDE.md / GEMINI.md
         ├─ .agents/skills/             Codex等のスキルとreferences
         ├─ .claude/skills/             Claude Code向け
         ├─ .gemini/skills/             Gemini CLI向け
         ├─ .opencode/skills/           OpenCode向け
         ├─ imports/                   インポートした場合のみ
         │  ├─ MANIFEST.json           元の場所・選択ファイル・サイズ・ハッシュ
         │  ├─ CONTEXT.md              既存方針・進捗・未解決事項の整理
         │  └─ source/                 選択した資料の複製（元の相対構造を保持）
         ├─ .rlk/
         │  ├─ state.sqlite3           方針・回答・状態・作業・試行・承認の正本
         │  ├─ jobs/
         │  │  └─ 8/                   作業ID（固定番号ではない）
         │  │     └─ attempt-1/         再試行はattempt-2へ
         │  │        ├─ prompt.md      AI作業の場合の指示
         │  │        ├─ response.json  AI作業の場合の応答
         │  │        ├─ code/experiment.py   数値実験の場合の実装
         │  │        ├─ preregistration.json 計画・コード・seed・環境の記録
         │  │        ├─ progress.json       seed完了時点の進捗
         │  │        ├─ analysis.json       集計結果
         │  │        └─ seed-11/            seedごとの実行先
         │  │           ├─ metrics.json
         │  │           ├─ stdout.log
         │  │           └─ stderr.log
         │  └─ skill-releases/          承認後に検証した研究スキルの版とログ
         └─ reports/
            ├─ PROPOSAL.md
            ├─ MEETING_REPORT-001.md    報告会用の研究報告書
            ├─ cycle-001.md
            ├─ cycle-001-CHECKS.md
            ├─ KNOWLEDGE.md / COMPARISON.md / CLUSTERS.md
            ├─ SESSION_LOG.md / ISSUES.md
            ├─ SKILL_CANDIDATES.md / SKILL_EVOLUTION.md
            ├─ skill-s1-DESIGN.md       スキル設計ができた場合
            ├─ IMPORT_REPORT.md        インポートした場合
            └─ knowledge.json / status.json
```

AI作業と数値実験は別の作業IDを持つ。図のattempt-1に全ファイルが常に揃うわけではない。
実験ID e1などとサイクル番号は事前登録・報告書に記録する。コード、測定値、ログは試行ごとに保存し、
再試行で以前の結果を上書きしない。importsのコードは資料として保存し、取り込み時に実行しない。

.researchはGitの対象外。研究のバックアップにはこのフォルダ全体を保存する。

## 既存研究を取り込む

Agentに「このフォルダの研究を取り込んで続けたい」と伝える。

1. 元フォルダと対象資料を選ぶ。報告書、コード、設定、測定結果、必要なデータなど。
2. Agentが対象ファイルの一覧とサイズをプレビューし、引き継ぐ範囲を示す。
3. 既存方針・済んだ実験・結果・未解決事項を整理し、確認済みの基本回答を記録する。
4. 新しい研究フォルダへ選択資料を複製する。元フォルダを移動・書換えしない。
5. 未回答の項目だけを確認し、資料と進捗を踏まえて深掘り・次の実験方針の提案へ進む。

ユーザーにPythonや設定JSONの入力を求めない。既に取り込み対象が明示されていれば、
同じ選択の確認を繰り返さずにその範囲で進める。

取り込みは既存資料のスナップショットと研究文脈の引継ぎ。実行中のプロセス、途中の計算チェックポイント、
他ツールの状態DBをそのまま復元する機能ではない。過去結果を今回の再検証済み実測として登録しない。
既存コードを再利用する場合も、次の計画を提示し採用された後に実行契約へ合わせる。

## Agentの内部操作

```console
python agent.py open
python agent.py import-preview --source C:/Research/existing --files report.md src/experiment.py results/metrics.json
python agent.py import-study SESSION --source C:/Research/existing --files report.md src/experiment.py results/metrics.json --hash PREVIEW_HASH --name "研究の継続" --context .research/import-context.json
```

contextの形式:

```json
{
  "summary": "既存の研究方針、実施済み実験、結果の解釈、未解決事項。未確認の点は明記する。",
  "answers": {
    "topic": "確認済みの研究テーマ",
    "interest": "確認済みの関心"
  }
}
```

answersは通常の基本質問IDから確認済みのものだけを埋める。不明項目を推測で埋めない。
必要なら--settingsで新しい研究の運転設定を渡す。元研究の予算・承認・スキルを自動移行しない。
取り込みが選択済みのセッションでは、通常のwork SESSIONから不足回答・深掘り・提案へ進める。

## 取り込み時の検査

ファイルは元フォルダからの相対パスで明示選択する。最大200ファイル、合計100MiB。
大きなデータセットは必要な資料を取り込み、データの所在・利用条件を研究設定で整理する。
ディレクトリの丸ごと再帰コピーはしない。リンク・ジャンクション・パス逸脱を拒否する。
.git、.rlk、.research、Agent設定ディレクトリ、.env*、.pem/.keyなどは対象外。
これは全ての秘密情報を自動検出する仕組みではないため、資料選択時に内容を確認する。

プレビューとコピー時にハッシュを照合し、変更された資料は再確認する。
コピー失敗時の途中成果物はimport-stagingに残り、通常の研究一覧には公開しない。
コピー後のフォルダ公開とセッションDB確定は単一原子操作ではないため、直後の障害では
研究が一覧にあるのにセッションが未選択となる場合がある。openから保存済み研究を選び直す。
