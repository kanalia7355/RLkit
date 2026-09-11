---
name: cycle-completeness-guard
description: Require evidence checks and saved reports before the next cycle.
---

# cycle-completeness-guard

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

レビュー提出時の完了ゲートを必須とする。実測照合、サイクル報告、検査記録、KB、分類、履歴、横断比較、スキル候補、問題記録のMarkdown本文保存を検査する。失敗時は次候補を作成しない。DBのcompletion_gate_passedイベントが確定の根拠。ファイル存在だけを完了根拠にしない。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
