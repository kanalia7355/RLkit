# 配布・リリース

RLkitは独立したGitHubリポジトリとして公開され、[MIT License](../LICENSE)を採用している。
現在の版はpyproject.tomlとパッケージの__version__を正本にする。研究データをツール配布へ自動で含めない。

## 開発者向け手順

1. テスト、lint、Agent指示の現行契約との一致を確認する。
2. 別エージェントの敵対的レビューを受け、指摘を修正して再検証する。
3. wheelとソースZIPを生成し、リポジトリ外への展開・外部インストールを検証する。
4. PRを作りCIを確認する。リリース公開・マージはその依頼範囲で行う。

```console
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps --wheel-dir dist
python tools/export_project.py --output dist/source-new.zip
python tools/verify_release.py --archive dist/source-new.zip --wheel dist/research_loop_kit-0.9.0-py3-none-any.whl
```

ZIPは既存名を上書きしない。EXPORT_MANIFEST.jsonにハッシュ一覧を保存する。
研究状態、workspaces、.rlk、.git、認証情報、ビルド結果、実験ログを収録対象から外す。
これは内容から秘密を全自動検出する仕組みではない。公開対象は明示したツールのファイル群。

## 利用者の入口

cloneまたはZIP展開後、そのフォルダをAgentで開く。通常操作は会話で行い、pipや内部コマンド入力を利用者に求めない。
Python 3.10以上が内部処理に必要。外部CLI方式にはインストール・認証・応答先への権限が別途必要。
認証付き4製品の実運用は未検証。[検証記録](VALIDATION.md)を参照する。

元システムからの独立化の経緯は[ARCHITECTURE.md](ARCHITECTURE.md)と[SKILL_MIGRATION.md](SKILL_MIGRATION.md)へ保持する。
今後の一般化は[ROADMAP.md](ROADMAP.md)に従う。
