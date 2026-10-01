---
name: seed-power-advisor
description: Identify sample-size limitations when planning or reviewing experiments.
---

# seed-power-advisor

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

計画時にseed数、独立な実験単位、対応関係、実用上必要な差を明示する。検出力計算は未実装。対応seed差のpaired bootstrap区間は参考値として計算する。確認実験は事前登録したpaired_exceedance_testまたはdescriptive_meanを使える。前者は最小効果を厳密に超えるseedの確率の検定であり、平均差の検定ではない。独立標本の仮定、family補正、予定標本数、欠測を確認する。元研究の非対応検定の最小p値をこの設計に流用しない。統計的結論が必要なら不足をopen_questionsへ残す。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
