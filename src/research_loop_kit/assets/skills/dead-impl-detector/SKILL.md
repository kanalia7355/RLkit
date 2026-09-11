---
name: dead-impl-detector
description: Review ignored configuration and unused code before experiment execution.
---

# dead-impl-detector

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

inspect_codeが報告する未使用config/cfg/paramsとトップレベル定義の参照を確認する。意図した設定が実際の計算に渡るかコードを読む。外部利用やコールバックの可能性があるため静的警告だけで欠陥と断定しない。動的配線や効果検証はこの検査に含まれない。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
