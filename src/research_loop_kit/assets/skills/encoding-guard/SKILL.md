---
name: encoding-guard
description: Check text I/O encoding when implementing experiments.
---

# encoding-guard

lab_exの同名スキルの観点を汎用契約へ再実装したもの。元スクリプトの完全移植ではない。

実装の入出力はencodingを指定する。数値JSONとログはUTF-8で保存する。バイナリ入力にテキスト変換を強制しない。inspect_codeの注意箇所を確認し、必要な修正は実装応答へ含める。実行後の登録済みコードは書き換えない。

報告・不具合・改善候補の既定保存先は研究フォルダ内のMarkdown。外部投稿は行わない。
