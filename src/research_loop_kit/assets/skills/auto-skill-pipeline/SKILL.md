---
name: auto-skill-pipeline
description: Design research skill improvements from evidence and implement, test and activate them after design approval.
---

# 承認付きスキル育成

候補検出 → 設計 → 設計の提示 → 承認 → 実装 → 検証 → 研究への反映を扱う。
研究方針の採用だけでスキルの反映を許可されたと解釈しない。
設計時と実装時には[必須仕様](references/design-contract.md)を読む。

skill_designでは根拠、適用範囲、必要資源、検証方法を具体化する。
設計のMarkdownとハッシュをユーザーに示す。承認後は同じ範囲内の実装・テスト・有効化を続け、段階ごとに再承認を要求しない。
仕様変更が必要なら実装を失敗として記録し、設計修正へ戻す。反映先は選択中の研究だけ。
skill_buildはJSONで全資源を返す。ランタイムが実ファイル化とunittestを行い、成功版のみ有効化する。
テスト不合格版・未承認版・候補の文章を有効スキルとして読み込まない。
候補設計は毎サイクル最大1件。各設計・実装の試行回数はmax_attempts、時間はagent_timeout_seconds以内。
スキル呼出しはskill_callsに別記する。研究の計算予算を再開・リセットせず、報告会後の承認でも育成できる。
外部投稿・共有・親リポジトリの自己改修をしない。
