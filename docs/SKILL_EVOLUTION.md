# 報告書と承認付きスキル育成 — v0.4

## 報告会の成果物

research-reportスキルとreferences/report-structure.mdを同梱する。
各サイクルの完了ゲートでMEETING_REPORT-NNN.mdも必須出力とし、本文保存を照合する。
背景・方法・実測表・考察・結論・次の方針・相談事項・参考資料を含む。
外部資料はユーザー申告と確認済み実測を区別する。単なる週次進捗一覧ではない。
weekly系、PDF/PPTX変換、外部投稿は既定に含めない。

## 実行される流れ

1. サイクル完了時、未登録の再利用知見（なければ実験失敗）から最大1件を検出する。
2. skill_designジョブが根拠を読み、設計JSONを生成する。研究の実装/レビューとは別ジョブ。
3. 目的・適用条件・入出力・手順・資源・references・検証・リスク・無効化方法を必須検査する。
4. reports/skill-sN-DESIGN.mdとSKILL_EVOLUTION.mdへ設計を保存し、承認を待つ。
5. 起動中のAgentが設計とハッシュを示す。ユーザーの採用意図を得た後だけskill-acceptする。
6. skill_buildが承認資源を実装する。ランタイムがファイル化・構文確認・unittestを実行する。
7. テスト成功・資源一致・検証中の改変なしを確認した版を、研究DBのactive_skillsへ登録する。
8. 次に発行する該当段階の作業票へSKILL.mdとreferencesを読み込む。既発行の票は変更しない。

設計の承認で、その範囲の実装・テスト・反映まで許可する。各段階で形式的な再承認は挟まない。
設計内容を変更するときは新しい設計を提示する。研究方針の承認やbounded運転はスキル承認の代わりにならない。
却下・設計修正後は古い実装の再試行と反映を拒否する。

## 必須の資源と検査範囲

- SKILL.md: name/description、適用条件、手順、referencesへの用途付きリンク。
- references/*.md: 出典、必要な仕様・知見の本文、用途。候補のサイクル報告を出典に最低1件含める。
- tests/test_*.py: 少なくとも1件のunittest。正常と異常の期待動作を設計し、実装に対応した検査を行う。
- scripts/、assets/: 必要な場合は承認資源一覧に含める。不要なら手順欄に理由を記す。

パス逸脱・未承認資源・参照リンク欠落・出典欠落・Python構文エラーを拒否する。
テスト失敗、ゼロ件、skipを含む結果では有効化しない。テストは研究と同じOS権限で動くため、
ネットワーク・インストール・データ変更を生成テストに含めないよう作業票で指示する。
これはOSサンドボックスではない。テスト合格はスキルの全判断品質の保証ではない。
現在の資源形式はMarkdown/Python/JSON/text/CSV。バイナリ資源は未対応。

## 保存・適用・復旧

版は研究内の.rlk/skill-releases/へ保存する。テストログを保持し、反映はDBの参照切替で行う。
同梱スキルやグローバルスキルを上書きしない。別研究には自動配布しない。
同名の研究スキルを改訂した場合は新しい版を参照する。skill-disableで適用を外せる。
読み込み時に資源ハッシュを照合し、検証後の改変を検出したら停止する。

Agent内部操作（ユーザー自身のコマンド入力は不要）:

```console
python agent.py select SESSION --action improve --project PROJECT
python agent.py work SESSION status
python agent.py work SESSION skill-next
python agent.py work SESSION skill-submit JOB --token TOKEN --file RESPONSE_PATH
python agent.py work SESSION skill-accept s1 --hash DESIGN_HASH
python agent.py work SESSION skill-run
python agent.py work SESSION skill-revise s1 --hash DESIGN_HASH --feedback "修正内容"
python agent.py work SESSION skill-reject s1 --hash DESIGN_HASH
python agent.py work SESSION skill-disable SKILL_NAME
```

active方式ではskill-runの代わりにskill-next/skill-submitで今のAgentが実装する。
失敗はskill-fail、停止確認を伴う回収はskill-recover --process-stopped、再試行はskill-retry。
同じ試行の部分成果物を流用せず、新しい試行に保存する。失敗版を有効化しない。
実験がcompleteでも、再セッションのimproveから育成できる。研究実行はこのモードでは禁止する。

設計・実装それぞれmax_attempts回、各試行agent_timeout_seconds以内。テストは残り時間かつ最大60秒。
スキル呼出しはskill_callsに記録し、研究の計算予算をリセットしない。設計改訂はユーザーの指示で追加する。
pauseは研究とスキルの新規起動を止める。改善モードで継続する意図が示されたらskill-resumeでスキルだけを再開する。
研究のpaused状態と実験予算は変更しない。
