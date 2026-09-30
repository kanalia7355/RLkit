"""根拠付きスキル候補 → 設計承認 → 検証済み版の有効化。"""

import ast
from importlib.resources import files
from pathlib import PurePosixPath
import re
import sys

from .config import LoopError, dump, nonempty, strings
from .fsutil import write_new
from .providers import process_run
from .store import digest

KINDS = ("skill_design", "skill_build")
PHASES = ("deepen", "ideas", "plan", "implement", "review")


def detect(state, store, db, entry):
    """毎サイクル最大1案を設計する。研究予算内で実行し、採用は別承認。"""
    candidates = state.setdefault("skill_candidates", [])
    lessons = entry["review"]["reusable_lessons"]
    if not lessons:
        lessons = [r["error"] for r in entry["results"] if r.get("error")]
    for lesson in lessons:
        key = digest(lesson)
        if any(c["key"] == key for c in candidates):
            continue
        candidate = {
            "id": f"s{len(candidates) + 1}",
            "key": key,
            "observation": lesson,
            "evidence": f"reports/cycle-{entry['cycle']:03d}.md",
            "cycle": entry["cycle"],
            "status": "designing",
        }
        candidates.append(candidate)
        store.job(db, 0, "skill_design", {"candidate": candidate})
        break


def safe_path(path):
    if not isinstance(path, str) or "\\" in path or not re.fullmatch(r"[A-Za-z0-9_./-]+", path):
        raise LoopError("スキルのファイルパスが不正です")
    parts = PurePosixPath(path).parts
    if not parts or path.startswith("/") or any(p in ("..", ".") for p in path.split("/")):
        raise LoopError("スキルのパス逸脱は許可されません")
    if path != "SKILL.md" and (parts[0] not in ("references", "scripts", "tests", "assets") or len(parts) < 2):
        raise LoopError("SKILL.md / references / scripts / tests / assets 内を指定してください")
    if PurePosixPath(path).suffix not in (".md", ".py", ".json", ".txt", ".csv"):
        raise LoopError("スキル資源はMarkdown/Python/JSON/text/CSVに対応しています")


def validate_design(result):
    for key in (
        "name",
        "description",
        "purpose",
        "trigger",
        "non_goals",
        "inputs",
        "outputs",
        "procedure",
        "risks",
        "validation",
        "rollback",
    ):
        nonempty(result.get(key), key)
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", result["name"]):
        raise LoopError("スキル名は小文字英数字とハイフン、63文字以下です")
    if (files("research_loop_kit") / "assets" / "skills" / result["name"]).is_dir():
        raise LoopError("同梱スキルを直接置換しません。研究固有の名前で設計してください")
    phases = result.get("phases")
    strings(phases, "phases")
    if not phases or len(set(phases)) != len(phases) or set(phases) - set(PHASES):
        raise LoopError("適用する実験段階を指定してください")
    resources = result.get("resources")
    if not isinstance(resources, list) or not resources or len(resources) > 30:
        raise LoopError("必要資源一覧resourcesが必須です")
    paths = []
    for resource in resources:
        if not isinstance(resource, dict):
            raise LoopError("資源はpath/purposeのオブジェクトです")
        safe_path(resource.get("path"))
        nonempty(resource.get("purpose"), "resource purpose")
        paths.append(resource["path"])
    if len(paths) != len(set(paths)) or "SKILL.md" not in paths:
        raise LoopError("SKILL.mdを含む重複のない資源一覧が必要です")
    refs = result.get("references")
    if not isinstance(refs, list) or not refs:
        raise LoopError("根拠資料referencesが必須です")
    for ref in refs:
        if not isinstance(ref, dict):
            raise LoopError("referenceはpath/source/relevanceのオブジェクトです")
        for key in ("path", "source", "relevance"):
            nonempty(ref.get(key), f"reference {key}")
        if ref["path"] not in paths or not ref["path"].startswith("references/") or not ref["path"].endswith(".md"):
            raise LoopError("referencesの本文を同梱資源に含めてください")
    if not any(p.startswith("tests/test_") and p.endswith(".py") for p in paths):
        raise LoopError("承認後に実行するtests/test_*.pyが必須です")


def validate_build(result, design):
    content = result.get("files")
    if not isinstance(content, dict) or set(content) != {r["path"] for r in design["resources"]}:
        raise LoopError("実装資源一覧が承認済み設計と一致しません")
    for name, text in content.items():
        safe_path(name)
        nonempty(text, name)
        if len(text) > 200_000:
            raise LoopError("スキル資源が大きすぎます")
        if name.endswith(".py"):
            try:
                ast.parse(text, filename=name)
            except SyntaxError as exc:
                raise LoopError(f"スキル実装の構文エラー: {exc}") from exc
    skill = content["SKILL.md"]
    header = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", skill, re.S)
    if not header or not re.search(r"^name: " + re.escape(design["name"]) + r"\s*$", header[1], re.M):
        raise LoopError("SKILL.mdのfrontmatter nameが設計と一致しません")
    if not re.search(r"^description: \S.+$", header[1], re.M):
        raise LoopError("SKILL.mdのdescriptionが必要です")
    for ref in design["references"]:
        if f"({ref['path']})" not in skill:
            raise LoopError("SKILL.mdから各referencesへのリンクが必要です")
        if ref["source"] not in content[ref["path"]]:
            raise LoopError("references本文に承認済みの出典を記載してください")


def build(root, job, result, timeout):
    design = job["payload"]["design"]
    validate_build(result, design)
    version = digest(result["files"])
    relative = f".rlk/skill-releases/{design['name']}/{job['id']}-{job['attempt']}-{version}"
    directory = root / relative
    for name, text in result["files"].items():
        write_new(directory / name, text)
    process_run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
        directory,
        directory / "test.stdout.log",
        directory / "test.stderr.log",
        min(timeout, 60),
    )
    log = (directory / "test.stderr.log").read_text(encoding="utf-8")
    match = re.search(r"Ran ([1-9][0-9]*) tests?", log)
    if not match or "\nOK" not in log or "skipped=" in log:
        raise LoopError("少なくとも1件の未skipテスト成功が必要です")
    # テストが資源を書き換えた版を承認済みの実装として採用しない。
    if any(
        (directory / name).is_symlink()
        or not (directory / name).resolve().is_relative_to(directory.resolve())
        or (directory / name).read_text(encoding="utf-8") != text
        for name, text in result["files"].items()
    ):
        raise LoopError("検証中にスキル資源が変更されました")
    return {
        "name": design["name"],
        "path": relative,
        "version": version,
        "files": list(result["files"]),
        "phases": design["phases"],
        "tests_passed": int(match[1]),
        "quality_status": "behavior_validated",
        "design_hash": job["payload"]["design_hash"],
    }


def documents(state):
    output = {}
    index = ["# スキル設計・反映状況", "", "設計承認は研究方針の採用とは別です。未承認版は反映しません。", ""]
    for candidate in state.get("skill_candidates", []):
        index += [
            f"- {candidate['id']}: {candidate['status']} / {candidate['observation']}",
            f"  根拠: [{candidate['evidence']}](../{candidate['evidence']})",
        ]
        if "design" in candidate:
            name = f"skill-{candidate['id']}-DESIGN.md"
            design = candidate["design"]
            output[name] = (
                f"# スキル設計 {candidate['id']}: {design['name']}\n\n"
                f"状態: {candidate['status']}\n\n承認対象ハッシュ: `{candidate['design_hash']}`\n\n"
                "承認後はこの資源一覧・適用範囲内で実装、テスト、反映まで進めます。\n\n"
                f"```json\n{dump(design)}\n```\n"
            )
            index += [f"  設計: [{name}]({name})"]
    for skill in state.get("active_skills", {}).values():
        assessment = skill.get("utility_assessment")
        quality = assessment["status"] if assessment else "behavior_validated（有用性未評価）"
        index += [
            f"- 検証段階: {quality}",
            f"- 有効版: {skill['name']} / `{skill['version']}` / テスト {skill['tests_passed']}件",
            f"  保存先: `{skill['path']}` / 適用: {', '.join(skill['phases'])}",
        ]
    output["SKILL_EVOLUTION.md"] = "\n".join(index) + "\n"
    return output


def assess_utility(root, active, assessment):
    """テスト合格とは別に、固定版スキルの有無による事例比較を検査・保存する。"""
    import uuid

    from .config import number, read_json
    from .fsutil import no_links

    if not isinstance(assessment, dict) or assessment.get("version") != active["version"]:
        raise LoopError("有用性評価は現在のスキル版を指定してください")
    directory = root / active["path"]
    content = {}
    for name in active["files"]:
        path = directory / name
        no_links(path, root)
        content[name] = path.read_text(encoding="utf-8")
    if digest(content) != active["version"]:
        raise LoopError("有効スキルの内容が変更されています")
    protocol = active.get("utility_protocol")
    if not protocol or assessment.get("protocol_hash") != protocol["hash"]:
        raise LoopError("事例と指標を固定した有用性評価計画が先に必要です")
    no_links(root / protocol["evidence"], root)
    if read_json(root / protocol["evidence"]) != protocol["plan"]:
        raise LoopError("事前の有用性評価計画が変更されています")
    for key in ("version", "metric", "method", "direction", "minimum_improvement"):
        if assessment.get(key) != protocol["plan"][key]:
            raise LoopError("有用性評価の条件が事前計画と異なっています")
    planned_cases = {c["id"]: c for c in protocol["plan"]["cases"]}
    for key in ("metric", "method"):
        nonempty(assessment.get(key), key)
    direction = assessment.get("direction")
    if direction not in ("minimize", "maximize"):
        raise LoopError("有用性の評価方向が必要です")
    threshold = number(assessment.get("minimum_improvement"), "最小改善幅")
    if threshold <= 0:
        raise LoopError("有用性の最小改善幅は正の数値です")
    cases = assessment.get("cases")
    if not isinstance(cases, list) or not 2 <= len(cases) <= 100:
        raise LoopError("正常事例と悪化を検出する事例を含む2〜100件の比較が必要です")
    ids, kinds, records, improvements = set(), set(), [], []
    for case in cases:
        if not isinstance(case, dict):
            raise LoopError("比較事例はオブジェクトです")
        nonempty(case.get("id"), "事例ID")
        if case["id"] in ids or case.get("kind") not in ("normal", "adverse"):
            raise LoopError("事例IDは重複不可、kindはnormal / adverseです")
        if case["id"] not in planned_cases or case["kind"] != planned_cases[case["id"]]["kind"]:
            raise LoopError("比較事例が事前計画と異なっています")
        ids.add(case["id"])
        kinds.add(case["kind"])
        pair = []
        for mode in ("baseline", "with_skill"):
            item = case.get(mode)
            if not isinstance(item, dict):
                raise LoopError("スキルなし・ありの両方の証跡が必要です")
            name = item.get("evidence")
            nonempty(name, "評価証跡パス")
            if (
                "\\" in name
                or ":" in name
                or PurePosixPath(name).is_absolute()
                or any(p in ("", ".", "..") or p.startswith(".") for p in name.split("/"))
            ):
                raise LoopError("評価証跡は研究内の通常ファイルを指定してください")
            path = root / name
            no_links(path, root)
            if not path.is_file() or path.stat().st_size > 2_000_000:
                raise LoopError("評価証跡は2MB以内のJSONファイルです")
            evidence = read_json(path)
            if not isinstance(evidence, dict) or any(
                evidence.get(k) != value
                for k, value in {
                    "case_id": case["id"],
                    "mode": mode,
                    "skill_version": active["version"],
                    "metric": assessment["metric"],
                    "protocol_hash": protocol["hash"],
                }.items()
            ):
                raise LoopError("評価証跡の事例・モード・スキル版・指標が一致しません")
            if "input" not in evidence:
                raise LoopError("比較した入力が証跡に必要です")
            nonempty(evidence.get("outcome"), "評価対象の出力と判定根拠")
            score = number(evidence.get("score"), "評価証跡のスコア")
            if number(item.get("score"), "申告スコア") != score:
                raise LoopError("申告スコアと保存した評価証跡が一致しません")
            pair.append(evidence)
            records.append({"case_id": case["id"], "mode": mode, "source": name, "body": evidence})
        if pair[0]["input"] != pair[1]["input"] or pair[0]["input"] != planned_cases[case["id"]]["input"]:
            raise LoopError("スキルの有無で比較入力が異なっています")
        sign = 1 if direction == "maximize" else -1
        improvements.append(sign * (pair[1]["score"] - pair[0]["score"]))
    if ids != set(planned_cases):
        raise LoopError("事前計画の全事例を比較してください")
    if kinds != {"normal", "adverse"}:
        raise LoopError("正常事例と悪化検出事例の両方が必要です")
    mean = sum(improvements) / len(improvements)
    status = (
        "regression"
        if any(x < 0 for x in improvements)
        else "utility_supported"
        if mean >= threshold
        else "inconclusive"
    )
    folder = root / ".rlk/skill-evaluations" / active["name"] / uuid.uuid4().hex
    files = {}
    for i, record in enumerate(records):
        filename = f"case-{i:03d}.json"
        content = dump(record)
        write_new(folder / filename, content)
        files[filename] = digest(record)
    result = dict(
        assessment,
        status=status,
        mean_improvement=mean,
        improvements=improvements,
        evidence=folder.relative_to(root).as_posix(),
        evidence_hashes=files,
        limits="指定事例・指標による比較。スコアの妥当性・他の研究への一般化は別途レビューする。",
    )
    write_new(folder / "assessment.json", dump(result))
    return result


def verify_utility(root, assessment):
    from .config import read_json
    from .fsutil import no_links

    directory = root / assessment["evidence"]
    no_links(directory, root)
    if read_json(directory / "assessment.json") != assessment:
        raise LoopError("スキルの有用性評価記録が変更されています")
    for name, expected in assessment["evidence_hashes"].items():
        path = directory / name
        no_links(path, root)
        if digest(read_json(path)) != expected:
            raise LoopError("スキルの比較証跡が変更されています")


def plan_utility(root, active, plan):
    """比較結果を見る前に、事例・評価指標・改善幅を固定する。"""
    import uuid

    from .config import number

    if not isinstance(plan, dict) or plan.get("version") != active["version"]:
        raise LoopError("有用性評価計画は現在のスキル版を指定してください")
    for key in ("metric", "method"):
        nonempty(plan.get(key), key)
    if (
        plan.get("direction") not in ("minimize", "maximize")
        or number(plan.get("minimum_improvement"), "最小改善幅") <= 0
    ):
        raise LoopError("評価方向と正の最小改善幅を事前に指定してください")
    cases = plan.get("cases")
    if not isinstance(cases, list) or not 2 <= len(cases) <= 100:
        raise LoopError("2〜100件の比較事例を事前に指定してください")
    if any(
        not isinstance(c, dict)
        or not isinstance(c.get("id"), str)
        or not c["id"]
        or c.get("kind") not in ("normal", "adverse")
        or "input" not in c
        for c in cases
    ):
        raise LoopError("事例ID・normal/adverse・比較入力を事前に指定してください")
    if len({c["id"] for c in cases}) != len(cases) or {c["kind"] for c in cases} != {"normal", "adverse"}:
        raise LoopError("重複しない正常事例と悪化検出事例が必要です")
    # dump also rejects nonfinite inputs before they enter the state database.
    dump(plan)
    path = root / ".rlk/skill-evaluation-plans" / active["name"] / (uuid.uuid4().hex + ".json")
    write_new(path, dump(plan))
    return {"plan": plan, "hash": digest(plan), "evidence": path.relative_to(root).as_posix()}
