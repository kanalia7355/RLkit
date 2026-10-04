# 入出力と判断例

## 入力

作業票のplan・固定コード・測定値・履歴から、この手順に必要な情報を読む。
情報が欠ける場合は欠けている項目を列挙する。元プロジェクトのファイルを取りに行かない。

## 出力

- plan: method・metric・limitationsへ検証条件を記し、実行に必要な未解決事項はopen_questionsへ返す。
- implement: files/shared_filesとnotesだけを返す。実測値を捏造しない。
- implementation_review: decision・summary・checks・testsへ返す。testsは既存ランタイムのunittestで実行される。
- review: experimentsのinterpretation/limitations、next_questionsへ返す。新しいJSONキーや別ファイルを独自に追加しない。
- 手動依頼: 当該依頼で許可された成果物だけを作る。作業票内では手動モードへ勝手に切り替えない。

## 判断例

正常: 必要入力が揃い、手順の対象と具体的な証拠を提示できる場合だけ、確認した範囲を記す。
異常: 固定入力または原測定が欠落している場合は未確認とし、計画ではopen_questions、レビューではlimitationsへ返す。
反例: 手順が配布されているだけで自動検査済みと称したり、都合の悪い失敗測定を除外して結論を支持したりしない。

## 適応の根拠

利用者が所有する研究支援スキルのfigure-toolkitの目的を参考に、RLkitの現行作業票・固定入力・seed対照比較へ書き直した。
元資料の実験結果・固有データ・スクリプトは引用・配布していない。出典本文を研究結果の証拠として使用しない。
