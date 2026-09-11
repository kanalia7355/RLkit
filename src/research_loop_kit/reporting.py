"""研究報告・知見・運用上の問題はローカルMarkdownへ出力する。"""

from collections import defaultdict


def meeting_report(state, entry):
    answers = state["answers"]
    reviews = entry["review"]["experiments"]
    lines = [f"# 研究報告書 — {state['config']['name']}", "",
             f"対象: サイクル {entry['cycle']} / 採用方針: `{entry['proposal_hash']}`", "",
             "## 要旨", "", entry["direction"], "",
             f"{len(entry['results'])}件の実験を報告する。数値の差は記述統計であり、統計的有意差の検定は未実施。", "",
             *[f"- {r['id']}: {r['assessment']} — {r['interpretation']}" for r in reviews], "",
             "## 背景・目的", "", f"テーマ: {answers.get('topic', '未記録')}", "",
             f"関心: {answers.get('interest', '未記録')}", "", f"目的: {answers.get('motivation', '未記録')}", "",
             "## 方法", "", f"データ（申告）: {answers.get('data', '未記録')}", "",
             f"資源・制約（申告）: {answers.get('resources', '未記録')} / {answers.get('constraints', '未記録')}", ""]
    specs = {p["id"]: p for p in entry.get("proposal", {}).get("experiments", [])}
    for r in entry["results"]:
        spec = r.get("manifest", {}).get("experiment", specs.get(r["id"], {}))
        lines += [f"### {r['id']}: {spec.get('title', '実験名未記録')}", ""]
        for key, label in (("hypothesis", "仮説"), ("method", "手順・固定条件"), ("baseline", "対照"),
                           ("treatment", "介入"), ("metric", "指標・単位"), ("direction", "評価方向"),
                           ("min_effect", "採用する改善幅"), ("success_rule", "判定根拠"), ("stop_rule", "停止条件")):
            lines += [f"- {label}: {spec.get(key, '未記録')}"]
        lines += [f"- 実行seed: {r.get('manifest', {}).get('seeds', '未実行')}", ""]
    lines += ["## 結果", "", "| 実験 | 状態 | 対照平均 | 介入平均 | 改善幅平均 | n | 閾値到達 |",
              "|---|---|---:|---:|---:|---:|---|"]
    for r in entry["results"]:
        lines += [f"| {r['id']} | {r['status']} | {r.get('baseline_mean', '—')} | {r.get('treatment_mean', '—')} | {r.get('effect_mean', '—')} | {r.get('n', 0)} | {r['threshold_met']} |"]
    for r in entry["results"]:
        if r.get("error"):
            lines += ["", f"失敗記録 {r['id']}: {r['error']}", ""]
    lines += ["", "## 考察・限界", ""]
    for r in reviews:
        lines += [f"### {r['id']}: {r['assessment']}", "", r["interpretation"], "", f"限界: {r['limitations']}", ""]
    lines += ["## 結論・次の方針", "", *[f"- {x}" for x in entry["review"]["reusable_lessons"]], "",
              *[f"- 次の検証: {x}" for x in entry["review"]["next_questions"]], "",
              "## 報告会での相談事項", "", "以下は次の検証に向けた相談候補であり、未決定事項です。", "",
              *[f"- {x}" for x in entry["review"]["next_questions"]], "",
              "## 参考資料・実験証跡", "", "先行情報（ユーザー申告・外部資料の検証状態は別途確認）:", "",
              answers.get("prior_work", "未調査"), "",
              f"- [サイクル報告](cycle-{entry['cycle']:03d}.md)",
              f"- [検証記録](cycle-{entry['cycle']:03d}-CHECKS.md)"]
    for r in entry["results"]:
        if "evidence" in r:
            path = "../" + r["evidence"]
            lines += [f"- {r['id']}: [事前登録]({path}/preregistration.json) / [分析]({path}/analysis.json) / [コード]({path}/code/experiment.py)"]
    return "\n".join(lines) + "\n"


def supporting_documents(state):
    knowledge = ["# 実験知見", "", "DBの履歴から再生成。支持・未支持・失敗を区別する。", ""]
    session = ["# サイクル履歴", "", "各行の根拠はサイクル報告と実測ファイル。", ""]
    comparison = ["# 実験横断比較", "", "異なる指標・条件間の順位は付けない。差は記述統計。", ""]
    candidates = ["# スキル改善候補", "", "設計承認後に実装・検証・反映する。進捗は[スキル育成](SKILL_EVOLUTION.md)。外部投稿なし。", ""]
    clusters = defaultdict(list)
    recurring = defaultdict(list)
    for entry in state["history"]:
        link = f"[サイクル {entry['cycle']}](cycle-{entry['cycle']:03d}.md)"
        session += [f"- {link}: {entry['direction']} / {len(entry['results'])}実験 / 方針 `{entry['proposal_hash']}`"]
        # 意味の推測分類をせず、採用済み方針の完全一致で分類する。
        clusters[entry["direction"]].append(link)
        knowledge += [f"## {link}", ""]
        for review in entry["review"]["experiments"]:
            knowledge += [f"- {review['id']} / {review['assessment']}: {review['interpretation']}",
                          f"  限界: {review['limitations']}"]
        for lesson in entry["review"]["reusable_lessons"]:
            recurring[lesson].append(link)
        for result in entry["results"]:
            spec = result.get("manifest", {}).get("experiment", {})
            comparison += [f"- {link} / {result['id']} / {result['status']}: "
                           f"指標={spec.get('metric', '未測定')} / 方向={spec.get('direction', '未測定')} / "
                           f"改善幅={result.get('effect_mean', '未測定')} / n={result.get('n', 0)}"]
        knowledge.append("")
    for lesson, links in recurring.items():
        candidates += [f"- {'反復候補' if len(links) > 1 else '単発知見・要審査'}: {lesson}",
                       f"  根拠: {', '.join(links)}"]
    issues = ["# 運用上の問題", "", "既定の報告先はこのMarkdown。GitHub Issueへの自動投稿なし。", ""]
    for attempt in state.get("failed_attempts", []):
        issues += [f"- 作業 {attempt['job']} / 試行 {attempt['attempt']} の失敗履歴: {attempt['body'].get('error', '詳細なし')}"]
    for job in state.get("jobs", []):
        if job.get("error"):
            issues += [f"- 作業 {job['id']} / {job['kind']} / {job['status']}: {job['error']}",
                       "  復旧: プロセス停止と既存成果物を確認し、失敗記録を残して再試行する。"]
            candidates += [f"- エラー対策候補（未採用）: 作業 {job['id']} / {job['kind']}: {job['error']}"]
    if len(issues) == 4:
        issues.append("記録された問題なし。")
    if len(candidates) == 4:
        candidates.append("候補なし。検出対象の知見・失敗がまだありません。")
    cluster_lines = ["# 方針別分類", "", "承認済み方針の完全一致で分類。意味的クラスタリングは未実施。", ""]
    for direction, links in clusters.items():
        cluster_lines += [f"## {direction}", "", *[f"- {link}" for link in links], ""]
    documents = {name: "\n".join(lines) + "\n" for name, lines in {
        "KNOWLEDGE.md": knowledge, "SESSION_LOG.md": session,
        "COMPARISON.md": comparison, "CLUSTERS.md": cluster_lines,
        "SKILL_CANDIDATES.md": candidates, "ISSUES.md": issues}.items()}
    for entry in state["history"]:
        documents[f"MEETING_REPORT-{entry['cycle']:03d}.md"] = meeting_report(state, entry)
    imported = state.get("imported_research")
    if imported:
        lines = ["# 既存研究のインポート", "", imported["summary"], "",
                 "取り込んだ結果は未再検証の過去資料です。新しい実験の測定結果とは分けて扱います。", "",
                 f"取り込み元: `{imported['source']}`", "", "[取り込み記録](../imports/MANIFEST.json)", "",
                 "## 保存した資料", ""]
        lines += [f"- [{f['path']}](../{f['snapshot']}) / {f['bytes']} bytes / SHA256 `{f['sha256']}`" for f in imported["files"]]
        documents["IMPORT_REPORT.md"] = "\n".join(lines) + "\n"
    return documents
