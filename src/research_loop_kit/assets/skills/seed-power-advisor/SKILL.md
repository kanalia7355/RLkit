---
name: seed-power-advisor
description: Identify sample-size limitations when planning or reviewing experiments.
---

# seed-power-advisor

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

計画時にseed数、独立な実験単位、対応関係、実用上必要な差を明示する。現版は対応seedの記述統計のみで、検出力計算・p値・信頼区間は未実装。元研究の非対応検定の最小p値をこの設計に流用しない。統計的結論が必要なら不足をopen_questionsへ残す。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
