"""配布ZIPの整合性と、元リポジトリ外でのwheel実行を確かめる。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def verify(archive_path, wheel_path):
    archive_path, wheel_path = Path(archive_path).resolve(), Path(wheel_path).resolve()
    with tempfile.TemporaryDirectory(prefix="rlk-release-") as temp:
        root = Path(temp)
        source = root / "source"
        source.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            manifest = json.loads(archive.read("EXPORT_MANIFEST.json"))
            if set(names) != set(manifest) | {"EXPORT_MANIFEST.json"}:
                raise ValueError("配布ファイル一覧とハッシュ一覧が不一致です")
            for name, expected in manifest.items():
                path = (source / name).resolve()
                if not path.is_relative_to(source) or name.startswith("/") or "\\" in name:
                    raise ValueError(f"不正なZIPパス: {name}")
                data = archive.read(name)
                if hashlib.sha256(data).hexdigest() != expected:
                    raise ValueError(f"ハッシュ不一致: {name}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONNOUSERSITE="1")
        env.pop("PYTHONPATH", None)
        for entry in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "RESEARCH_START.md", ".claude/settings.json", ".gemini/settings.json"):
            if not (source / entry).is_file():
                raise ValueError(f"clone後の入口が配布物にありません: {entry}")
        startup = subprocess.run([sys.executable, str(source / "agent.py"), "open"], cwd=root,
                                 env=env, capture_output=True, encoding="utf-8", check=True)
        if json.loads(startup.stdout)["kind"] != "setup":
            raise ValueError("未インストールのcloneで初回セットアップに進めません")
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                       cwd=source, env=env, check=True)
        site = root / "installed"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                        "--target", str(site), str(wheel_path)], cwd=root, env=env, check=True)
        # wheelとソースの実行コード・スキルが同じであることを確認する。
        for source_file in (source / "src" / "research_loop_kit").rglob("*"):
            if source_file.is_file() and source_file.suffix in (".py", ".md"):
                installed_file = site / "research_loop_kit" / source_file.relative_to(source / "src" / "research_loop_kit")
                if installed_file.read_bytes() != source_file.read_bytes():
                    raise ValueError(f"wheelが古い、または同梱漏れです: {source_file.name}")
        env["PYTHONPATH"] = str(site)
        subprocess.run([sys.executable, "-m", "research_loop_kit", "demo", str(root / "demo"), "--cycles", "2"],
                       cwd=root, env=env, check=True)
        subprocess.run([sys.executable, "-m", "research_loop_kit", "init", str(root / "real-project")],
                       cwd=root, env=env, check=True)
        state = json.loads((root / "demo/reports/status.json").read_text(encoding="utf-8"))
        if state["phase"] != "complete" or state["runs"] != 20:
            raise ValueError("独立環境でデモが完了していません")
        if not (root / "demo/reports/MEETING_REPORT-002.md").is_file():
            raise ValueError("報告会用Markdownがありません")
        if not (root / "real-project/.agents/skills/research-report/references/report-structure.md").is_file():
            raise ValueError("参照資料が研究初期化で配布されていません")
        candidate = state["skill_candidates"][0]
        if candidate["status"] != "approval" or state.get("active_skills"):
            raise ValueError("スキルが設計承認前に反映されています")
        # ここだけはデモ候補の承認を模擬する。実研究の設計を承認しない。
        subprocess.run([sys.executable, "-m", "research_loop_kit", "skill-accept", str(root / "demo"),
                        candidate["id"], "--hash", candidate["design_hash"]], cwd=root, env=env, check=True)
        subprocess.run([sys.executable, "-m", "research_loop_kit", "skill-run", str(root / "demo")],
                       cwd=root, env=env, check=True)
        evolved = json.loads((root / "demo/reports/status.json").read_text(encoding="utf-8"))
        if not evolved.get("active_skills") or evolved["runs"] != 20:
            raise ValueError("承認後のスキル育成または実験の分離に失敗しました")
        print(json.dumps({"archive_files": len(manifest), "external_install": "PASS",
                          "clone_entry_without_install": "PASS",
                          "cycles": len(state["history"]), "runs": state["runs"],
                          "new_project_init": "PASS", "meeting_report": "PASS",
                          "approved_skill_evolution": "PASS"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True)
    parser.add_argument("--wheel", required=True)
    args = parser.parse_args()
    verify(args.archive, args.wheel)
