"""研究共通srcの蓄積と、実験ごとのコード版固定。"""

import ast
from pathlib import Path
import re

from .config import LoopError, dump
from .importing import no_links
from .store import digest, write_new


def validate_sources(sources):
    if not isinstance(sources, dict) or len(sources) > 200:
        raise LoopError("shared_filesは最大200件のPythonソース辞書です")
    if any(not isinstance(v, str) for v in sources.values()) or sum(len(v) for v in sources.values()) > 2_000_000:
        raise LoopError("共通ソースは文字列、合計200万文字以内です")
    names = set()
    for name, code in sources.items():
        if not isinstance(name, str) or not re.fullmatch(r"(?:[a-zA-Z_][a-zA-Z0-9_]*/)*[a-zA-Z_][a-zA-Z0-9_]*\.py", name):
            raise LoopError("共通ソースはsrcからの相対Pythonパスを指定してください")
        if name.lower() in names:
            raise LoopError("大文字小文字だけが異なる共通ソースは使えません")
        names.add(name.lower())
        try:
            ast.parse(code, filename=name)
        except SyntaxError as exc:
            raise LoopError(f"共通ソースの構文エラー: {exc}") from exc


def read_sources(root):
    directory = root / "src"
    if not directory.exists():
        return {}
    no_links(directory)
    sources = {}
    for path in sorted(directory.rglob("*.py")):
        no_links(path)
        if not path.resolve().is_relative_to(directory.resolve()):
            raise LoopError("共通ソースの外部参照は禁止です")
        sources[path.relative_to(directory).as_posix()] = path.read_text(encoding="utf-8")
    validate_sources(sources)
    return sources


def prepare(root, job, result):
    base = job["payload"].get("shared_sources", {})
    changes = result.get("shared_files", {})
    validate_sources(changes)
    snapshot = dict(base, **changes)
    validate_sources(snapshot)
    current = read_sources(root)
    validate_sources(dict(current, **changes))
    for name, code in changes.items():
        if current.get(name) not in (base.get(name), code):
            raise LoopError(f"共通ソースの並列変更が競合しました: {name}。最新srcを確認して別モジュール名に分けてください")
    result["shared_snapshot"] = snapshot
    result["shared_source_hash"] = digest(snapshot)


def save_same(path, text):
    if path.exists():
        no_links(path)
        if path.read_text(encoding="utf-8") != text:
            raise LoopError(f"既存の実験記録と内容が異なります: {path}")
    else:
        write_new(path, text)


def publish(root, job, result):
    """DBの実装受理トランザクション内。競合を再確認してから保存する。"""
    prepare(root, job, result)
    # 実行する内容はこの版。root/srcは以降の実装に使う作業用ソース。
    version = root / ".rlk/source-versions" / result["shared_source_hash"]
    for name, code in result["shared_snapshot"].items():
        save_same(version / "src" / name, code)
    for name, code in result.get("shared_files", {}).items():
        path = root / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        no_links(path.parent)
        if path.exists():
            no_links(path)
        path.write_text(code, encoding="utf-8")
    folder = root / "experiments" / f"cycle-{job['cycle']:03d}" / job["payload"]["experiment"]["id"]
    for name, code in result["files"].items():
        save_same(folder / name, code)
    save_same(folder / "experiment.json", dump({"experiment": job["payload"]["experiment"],
              "proposal_hash": job["payload"]["proposal_hash"], "shared_source_hash": result["shared_source_hash"],
              "source_version": version.relative_to(root).as_posix()}) + "\n")
    result["experiment_path"] = folder.relative_to(root).as_posix()


def code_files(implementation):
    return dict(implementation["files"], **{"src/" + p: text for p, text in implementation.get("shared_snapshot", {}).items()})


def read_code(directory):
    result = {}
    for path in directory.rglob("*.py"):
        no_links(path)
        result[path.relative_to(directory).as_posix()] = path.read_text(encoding="utf-8")
    return result
