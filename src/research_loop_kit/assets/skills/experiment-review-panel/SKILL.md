---
name: experiment-review-panel
description: Review metrics, mechanism and experimental controls from distinct perspectives.
---

# experiment-review-panel

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

レビューでは(1)数値とログの整合性、(2)実装と想定機序、(3)対照条件・交絡・標本数の三観点を順に点検し、interpretationとlimitationsに結論・不一致を記録する。現版は同じAgentの三観点レビューであり独立した複数Agentの合議ではない。閾値到達だけを因果支持にしない。証拠不足はinconclusive、不正な測定はinvalidとする。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
