---
name: experiment-knowledge-base
description: Preserve supported, inconclusive and failed findings for later proposals.
---

# experiment-knowledge-base

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

KNOWLEDGE.mdに実験ID、判定、解釈、限界とサイクル参照を保存する。次の候補はhistoryと過去の否定結果を読む。未支持仮説を既知の事実に昇格させない。知見と今後の問いを分ける。DBを正本としMarkdownはexportで再生成する。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
