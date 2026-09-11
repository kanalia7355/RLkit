---
name: skill-candidate-detector
description: Record grounded improvement candidates after experiment review.
---

# skill-candidate-detector

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

再利用知見と失敗をSKILL_CANDIDATES.mdへ記録する。同じ知見の反復は候補、単発は要審査として区別し、サイクルまたは作業IDを根拠にする。候補は研究成果とは限らない。
新しい知見または失敗から毎サイクル最大1件をskill_designへ送り、設計をSKILL_EVOLUTION.mdと設計書に保存する。
設計の承認後はauto-skill-pipelineが実装・検証・反映まで進める。未承認版を有効化しない。
問題はISSUES.mdへ保存し、GitHub Issueへ投稿しない。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
