# Agentの接続

通常はclone先でAgentを開くだけです。自動読み込み・起動hook・再開メニューは
[STARTUP.md](STARTUP.md)を参照してください。以下は内部実行と、外部CLIへ仕事を渡す場合の説明です。

共通契約は「UTF-8のprompt.mdを読み、指定先へresponse.jsonを書く」です。
CLIの会話出力からJSONを推測して切り出さないため、各CLIの画面形式や表示ログに依存しません。

## 起動中のAgent

`backend: active` が既定です。AGENT_GUIDE.mdを明示的に読ませれば、固有のスキル検出に
対応しないAgentでも使えます。生成時にAGENTS.md、CLAUDE.md、GEMINI.mdと
`.agents/.claude/.gemini/.opencode` 配下の共通スキルを配置します。
配置先の自動検出の差異があっても、ガイドと仕事票を読む経路を利用できます。
仕事票には担当スキルの本文も入るため、外部CLIがスキルを自動発見できなくても内容が届きます。

## 外部CLI

設定を深掘り開始前に保存します。たとえば基本は現在のAgent、候補作成とレビューだけ外部CLIへ渡す設定:

```json
{
  "backend": "active",
  "roles": {
    "ideas": {"backend": "claude"},
    "review": {"backend": "codex"}
  }
}
```

`rlk configure PROJECT --file provider-settings.json` で登録できます。
`roles` のキーはdeepen / ideas / plan / implement / implementation_review / review / skill_design / skill_build。
モデルを指定する場合は、利用中のCLIで利用できるmodel名を `model` へ入れます。
未指定ならそのCLIのユーザー設定を引き継ぎます。モデル名をツール側で固定しません。
追加オプションは `agent_args`（引数の配列）です。

外部CLIだけを進めるには `rlk run PROJECT`。activeの仕事があれば先に `rlk next` で
処理してください。各役割の生成後にactiveの仕事が現れた場合、runはその仕事を残して戻ります。
`rlk next` は外部CLI用に設定された仕事も現在のAgentで引き受けられます。

組み込んだ起動形式:

| backend | 形式 |
|---|---|
| codex | codex exec --skip-git-repo-check --sandbox workspace-write PROMPT |
| claude | claude -p PROMPT |
| gemini | gemini -p PROMPT |
| opencode | opencode run PROMPT |

PROMPTは仕事票を指す短い文章です。CLIにはその仕事票と応答先への読み書き権限が必要です。
read-only設定のままなら応答ファイルが作れず失敗になります。権限の調整はCLI側で行います。

### 権限確認をスキップして動かす前提

外部CLI方式は、**人が承認ダイアログに答えない無人実行**です。各CLIは、Claude Codeの
`--dangerously-skip-permissions` に相当する「ファイル書き込み・コマンド実行を確認なしで許可する」
設定で起動することを前提にしています。既定の権限のままでは `response.json` の書き込みが
承認待ちのまま拒否され、作業はタイムアウトまたは失敗として記録されます。

自動承認のオプションは `agent_args`（役割ごとなら `roles.<役割>.agent_args`）で渡します。

```json
{
  "roles": {
    "ideas": {"backend": "claude", "agent_args": ["--dangerously-skip-permissions"]},
    "review": {"backend": "gemini", "agent_args": ["--yolo"]}
  }
}
```

| backend | 自動承認の指定例 |
|---|---|
| claude | `--dangerously-skip-permissions`（または `--permission-mode bypassPermissions`） |
| codex | 組み込み引数の `--sandbox workspace-write` で作業フォルダへの書き込みを許可 |
| gemini | `--yolo` |
| opencode | 設定ファイルの `permission` で編集・コマンド実行を許可 |

オプション名はCLIの版で変わることがあるため、利用中の版の公式資料で確認してください。

この設定では、AIが生成した指示やコードが利用者のOS権限で確認なしに実行されます。
作業フォルダの分離はセキュリティ上のサンドボックスではありません。
**信頼できる研究データ・Agentだけを使い、必要ならコンテナや専用ユーザー・VMの中で実行してください。**
認証情報や他の研究を同じ環境に置かないことを推奨します。

2026-09-11に確認した公式資料:

- [Codex非対話実行](https://developers.openai.com/codex/noninteractive/)
- [Claude Codeプログラム実行](https://code.claude.com/docs/en/headless)
- [Gemini CLI headless](https://geminicli.com/docs/cli/headless/)
- [OpenCode CLI](https://opencode.ai/docs/cli/)

資料に基づく接続実装であり、これら4製品の認証付き実運用試験はまだ実施していません。

## Windowsのnpm shim

`.cmd` / `.bat` / `.ps1` のshimへ、生成したプロンプトをシェル文字列として渡しません。
該当するインストール形式ではactive方式を使うか、custom_commandをnode.exeと実際の
CLI JavaScript入口へのパスの配列として設定してください。パスはインストール先に合わせます。
ネイティブ実行ファイルなら通常のbackendで起動できます。

## 任意Agent

```json
{
  "backend": "custom",
  "custom_command": ["/absolute/path/to/agent", "run"],
  "model": "",
  "agent_args": []
}
```

最後の引数に短いPROMPTを追加して起動します。作業ディレクトリは試行専用フォルダです。
応答ファイルが不正、出力欠落、非ゼロ終了、タイムアウトなら失敗として保存します。
認証情報を設定JSONへ書かないでください。CLI固有のログイン設定を使います。

実機の複数サイクル・起動前中断復旧の検証入口は[証跡の仕様](EVIDENCE.md#外部cliの実運用受入試験)を参照してください。固定回答試験と認証付き実運用試験を区別して報告します。
