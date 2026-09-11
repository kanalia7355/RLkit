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
`roles` のキーはdeepen / ideas / plan / implement / review。
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
