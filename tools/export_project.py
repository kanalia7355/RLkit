"""公開用ソースだけを明示的な範囲からZIPへ保存する。"""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ("pyproject.toml", "README.md", ".gitignore", "setup.ps1", "setup.sh", "agent.py",
         "AGENTS.md", "CLAUDE.md", "GEMINI.md", "RESEARCH_START.md", ".claude/settings.json", ".gemini/settings.json")
TREES = {"src": {".py", ".md"}, "tests": {".py"}, "docs": {".md"},
         "examples": {".json"}, "tools": {".py"}, ".github": {".yml", ".yaml", ".md"},
         ".agents/skills": {".md"}}


def export(destination):
    destination = Path(destination).resolve()
    selected = [ROOT / name for name in FILES]
    for folder, suffixes in TREES.items():
        selected.extend(p for p in (ROOT / folder).rglob("*")
                        if p.is_file() and p.suffix in suffixes and "__pycache__" not in p.parts)
    for optional in ("LICENSE", "LICENSE.md"):
        if (ROOT / optional).is_file():
            selected.append(ROOT / optional)
    selected = sorted(set(selected))
    manifest = {}
    contents = []
    for path in selected:
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError(f"パッケージ外の参照は配布しません: {path}")
        name = path.relative_to(ROOT).as_posix()
        content = path.read_bytes()
        manifest[name] = hashlib.sha256(content).hexdigest()
        contents.append((name, content))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in contents:
            archive.writestr(name, content)
        archive.writestr("EXPORT_MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps({"archive": str(destination), "files": len(manifest),
                      "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="独立公開用のソースZIPを作成")
    parser.add_argument("--output", required=True)
    export(parser.parse_args().output)
