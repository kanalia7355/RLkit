---
name: run-sentinel
description: Inspect seed progress and budgets while an experiment runs.
---

# run-sentinel

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

試行ディレクトリのprogress.jsonと状態を読む。完了seed・残りseed・経過時間・推定ETAを伝える。ETAは完了seedの平均時間による推定であり保証ではない。最初のseed完了前はETA不明。ログから研究上の収束を推測して自動停止しない。停止条件と予算を守る。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
