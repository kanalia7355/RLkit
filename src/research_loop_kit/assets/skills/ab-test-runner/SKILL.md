---
name: ab-test-runner
description: A/Bの条件を比較する計画、実装、レビューで既存のseed対照比較を適用する。
---

# 対照と介入の比較設計

## 適用範囲

plan / implement / review。分野に依存しないAgent手順として利用する。
実行前に[入出力と判断例](references/contract.md)を読み、現在の作業票の契約を優先する。

## 手順

1. Aをbaseline、Bをtreatmentとして計画に記し、変更因子以外の入力、予算、停止条件を固定する。
2. seedごとに同じ対応単位を両条件へ適用する。同じ番号だけでは対応を保証しないのでデータ生成と割当を確認する。
3. experiment.pyは既存の--seed/--output契約とbaseline/treatmentの有限数値を守る。独自の実行口を増やさずランタイムの予算・停止管理を使う。
4. レビューでは各seed、失敗・欠損・途中終了を確認し、既存の集計を照合する。非有意を同等の証明とせず、閾値到達を統計的有意差と呼ばない。
5. 独立群検定や多群比較が必要なら現行の対応比較へ無理に変換しない。planではopen_questions、implementではnotes、reviewではexperimentsのlimitationsとnext_questionsへ記す。追加の確認実験は別計画として扱う。

## 制約

元の独立群Mann–Whitney U検定や世代数プリセットを持ち込まない。現行のpaired比較・確認契約へ適応した手順。
研究データ、実験番号、非公開リポジトリ、元研究固有の定数やコードに依存しない。
未実行・対象なし・必要入力欠落をPASSにしない。状態DBと既存成果物を直接編集しない。
