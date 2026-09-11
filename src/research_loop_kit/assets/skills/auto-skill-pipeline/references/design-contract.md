# スキル設計・実装の必須項目

設計JSONで必須:

- name / description / purpose: 名前、適用場面、解決する具体的問題
- trigger / non_goals: 適用条件と対象外
- inputs / outputs / procedure: 入出力の形式・保存先、処理手順
- phases: deepen / ideas / plan / implement / reviewから適用段階を選ぶ
- resources: 全ファイルのpathとpurpose。SKILL.md、references/*.md、tests/test_*.pyは必須
- references: 同梱path、実在するsource、判断を支えるrelevance。候補のevidenceを1件以上含める
- validation: 正常系・異常系と期待する結果。単なるファイル存在検査で実装の正しさを主張しない
- risks / rollback: 依存関係、副作用、停止条件、無効化で戻す方法

scripts/とassets/は必要な場合に必須資源へ列挙する。不要な場合はprocedureで理由を記す。
必要な参照本文をSKILL.mdだけに詰めずreferencesへ分け、SKILL.mdから用途付きのリンクを張る。
出典をURLで書くだけでは同梱referenceの代わりにならない。必要な仕様・知見の要約を本文へ記す。
非公開資料を外部公開しない。検証されていない出典や測定結果を捏造しない。

承認後の実装JSONはfiles辞書。承認資源一覧と完全一致するパスと本文を返す。
テキスト資源は.md/.py/.json/.txt/.csvに対応。バイナリ・外部依存が必要なら設計の範囲を見直す。
unittestで少なくとも1件を成功させ、スキップを使って検証成功にしない。
実装のテストは研究のOS権限で動く。ネットワーク・インストール・データ改変を含めない。
合格はテストした契約の範囲に限る。スキルの全場面での判断品質を保証しない。

反映は版を保存したうえでDBのactive_skillsを切り替える。後続の未発行作業票から適用する。
進行中・発行済みの作業票は書き換えない。改変を検出した有効版は読み込みを停止する。
skill-disable NAMEで有効化を解除する。ファイルと検証ログは削除しない。
