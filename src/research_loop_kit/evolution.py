"""根拠付きスキル候補 → 設計承認 → 検証済み版の有効化。"""

import ast
from importlib.resources import files
from pathlib import PurePosixPath
import re
import sys

from .config import LoopError, dump, nonempty, strings
from .providers import process_run
from .store import digest, write_new

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
        candidate = {"id": f"s{len(candidates)+1}", "key": key, "observation": lesson,
                     "evidence": f"reports/cycle-{entry['cycle']:03d}.md", "cycle": entry["cycle"],
                     "status": "designing"}
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
    for key in ("name", "description", "purpose", "trigger", "non_goals", "inputs", "outputs", "procedure",
                "risks", "validation", "rollback"):
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
    process_run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
                directory, directory / "test.stdout.log", directory / "test.stderr.log", min(timeout, 60))
    log = (directory / "test.stderr.log").read_text(encoding="utf-8")
    match = re.search(r"Ran ([1-9][0-9]*) tests?", log)
    if not match or "\nOK" not in log or "skipped=" in log:
        raise LoopError("少なくとも1件の未skipテスト成功が必要です")
    # テストが資源を書き換えた版を承認済みの実装として採用しない。
    if any((directory / name).is_symlink() or not (directory / name).resolve().is_relative_to(directory.resolve())
           or (directory / name).read_text(encoding="utf-8") != text for name, text in result["files"].items()):
        raise LoopError("検証中にスキル資源が変更されました")
    return {"name": design["name"], "path": relative, "version": version,
            "files": list(result["files"]), "phases": design["phases"],
            "tests_passed": int(match[1]), "design_hash": job["payload"]["design_hash"]}


def documents(state):
    output = {}
    index = ["# スキル設計・反映状況", "", "設計承認は研究方針の採用とは別です。未承認版は反映しません。", ""]
    for candidate in state.get("skill_candidates", []):
        index += [f"- {candidate['id']}: {candidate['status']} / {candidate['observation']}",
                  f"  根拠: [{candidate['evidence']}](../{candidate['evidence']})"]
        if "design" in candidate:
            name = f"skill-{candidate['id']}-DESIGN.md"
            design = candidate["design"]
            output[name] = (f"# スキル設計 {candidate['id']}: {design['name']}\n\n"
                            f"状態: {candidate['status']}\n\n承認対象ハッシュ: `{candidate['design_hash']}`\n\n"
                            "承認後はこの資源一覧・適用範囲内で実装、テスト、反映まで進めます。\n\n"
                            f"```json\n{dump(design)}\n```\n")
            index += [f"  設計: [{name}]({name})"]
    for skill in state.get("active_skills", {}).values():
        index += [f"- 有効版: {skill['name']} / `{skill['version']}` / テスト {skill['tests_passed']}件",
                  f"  保存先: `{skill['path']}` / 適用: {', '.join(skill['phases'])}"]
    output["SKILL_EVOLUTION.md"] = "\n".join(index) + "\n"
    return output
