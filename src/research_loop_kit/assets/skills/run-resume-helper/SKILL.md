---
name: run-resume-helper
description: Recover interrupted experiments using preserved attempts and tokens.
---

# run-resume-helper

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

runningを再起動だけで失敗と決めない。実プロセス停止を確認してrecoverし、retryで新しい試行を作る。progress.jsonを手掛かりに既存結果を確認するが、現版のretryは全seedを新しい試行で実行する。部分seed統合は未対応。古い成果物・失敗・消費予算を残す。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
