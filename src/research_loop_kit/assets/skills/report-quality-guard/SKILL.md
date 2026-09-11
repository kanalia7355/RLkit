---
name: report-quality-guard
description: Check measured facts against experiment reports before accepting a cycle.
---

# report-quality-guard

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

事前登録、実測、コード、報告の対応を確認する。verify_evidenceは保存されたseed別数値から平均・改善幅・標準偏差・閾値判定を再計算する。自然言語の数値主張はAgentが照合する。目的・方法・事実・解釈・限界を明確にし、閾値到達を統計的有意差や因果的証明としない。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
