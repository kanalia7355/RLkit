"""研究共通srcの蓄積と、実験ごとのコード版固定。

共通srcの全文はジョブのpayloadや結果へ埋め込まず、内容アドレスの版フォルダ
`.rlk/source-versions/<hash>/src/` に一度だけ保存し、DBにはハッシュだけを残す。
"""

import ast
import hashlib
import re

from .config import LoopError, dump
from .fsutil import no_links, rollback_files, write_atomic, write_new
from .store import digest

VERSIONS = ".rlk/source-versions"
_NAME = re.compile(r"(?:[a-zA-Z_][a-zA-Z0-9_]*/)*[a-zA-Z_][a-zA-Z0-9_]*\.py")


def validate_sources(sources):
    if not isinstance(sources, dict) or len(sources) > 200:
        raise LoopError("shared_filesは最大200件のPythonソース辞書です")
    if any(not isinstance(v, str) for v in sources.values()) or sum(len(v) for v in sources.values()) > 2_000_000:
        raise LoopError("共通ソースは文字列、合計200万文字以内です")
    names = set()
    for name, code in sources.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise LoopError("共通ソースはsrcからの相対Pythonパスを指定してください")
        if name.lower() in names:
            raise LoopError("大文字小文字だけが異なる共通ソースは使えません")
        names.add(name.lower())
        try:
            ast.parse(code, filename=name)
        except SyntaxError as exc:
            raise LoopError(f"共通ソースの構文エラー: {exc}") from exc


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hashes(sources):
    return {name: text_hash(code) for name, code in sources.items()}


def read_code(directory, base=None):
    """directory配下の.pyを読む。baseまでの途中のリンクを拒否する。"""
    base = directory if base is None else base
    result = {}
    for path in sorted(directory.rglob("*.py")):
        no_links(path, base)
        result[path.relative_to(directory).as_posix()] = path.read_text(encoding="utf-8")
    return result


def read_sources(root):
    directory = root / "src"
    if not directory.exists():
        return {}
    no_links(directory, root)
    sources = read_code(directory, root)
    validate_sources(sources)
    return sources


def save_same(path, text, base):
    if path.exists():
        no_links(path, base)
        if path.read_text(encoding="utf-8") != text:
            raise LoopError(f"既存の実験記録と内容が異なります: {path}")
    else:
        write_new(path, text)


def store_version(root, sources):
    """共通srcの版を内容アドレスで保存する。同じ版の再保存は内容一致を確認するだけ。"""
    version = digest(sources)
    for name, code in sources.items():
        save_same(root / VERSIONS / version / "src" / name, code, root)
    return version


def load_version(root, version):
    directory = root / VERSIONS / version / "src"
    sources = read_code(directory, root) if directory.exists() else {}
    if digest(sources) != version:
        raise LoopError(f"共通srcの保存版が変更または欠損しています: {version}")
    return sources


def base_sources(root, payload):
    """実装ジョブ作成時の共通src。旧版のpayload（全文埋め込み）も読める。"""
    if "shared_source_hash" in payload:
        return load_version(root, payload["shared_source_hash"])
    return payload.get("shared_sources", {})


def experiment_folder(job):
    return f"experiments/cycle-{job['cycle']:03d}/{job['payload']['experiment']['id']}"


def prepare(root, job, result):
    """書き込みを伴わない検証。実行版のsnapshotを返し、resultへハッシュと保存先を記録する。"""
    base = base_sources(root, job["payload"])
    changes = result.get("shared_files", {})
    validate_sources(changes)
    snapshot = dict(base, **changes)
    validate_sources(snapshot)
    current = read_sources(root)
    validate_sources(dict(current, **changes))
    for name, code in changes.items():
        if current.get(name) not in (base.get(name), code):
            raise LoopError(
                f"共通ソースの並列変更が競合しました: {name}。最新srcを確認して別モジュール名に分けてください"
            )
    result.pop("shared_snapshot", None)
    result["shared_source_hash"] = digest(snapshot)
    result["shared_source_files"] = file_hashes(snapshot)
    result["experiment_path"] = experiment_folder(job)
    return snapshot


def publish(root, job, result, rollback):
    """実装受理トランザクションの最後（DB更新の後、commitの前）に呼ぶ。

    内容アドレスの版フォルダは追記のみ。作業用srcと実験ファイルは、
    DBのcommitまで元の内容を保持し、保存・commit失敗時に戻す。
    """
    snapshot = prepare(root, job, result)
    folder = root / result["experiment_path"]
    paths = [root / "src" / name for name in result.get("shared_files", {})]
    paths += [folder / name for name in result["files"]]
    paths.append(folder / "experiment.json")
    # 呼出元のExitStackはDBトランザクションより外側で閉じ、commit失敗も復旧する。
    rollback.enter_context(rollback_files(paths, root))
    version = store_version(root, snapshot)
    for name, code in result.get("shared_files", {}).items():
        path = root / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        no_links(path.parent, root)
        if path.exists():
            no_links(path, root)
        write_atomic(path, code)
    for name, code in result["files"].items():
        save_same(folder / name, code, root)
    record = {
        "experiment": job["payload"]["experiment"],
        "proposal_hash": job["payload"]["proposal_hash"],
        "shared_source_hash": version,
        "source_version": f"{VERSIONS}/{version}",
    }
    save_same(folder / "experiment.json", dump(record) + "\n", root)


def code_files(root, implementation):
    """実行するコード一式。旧版の結果（shared_snapshot埋め込み）も読める。"""
    if "shared_snapshot" in implementation:
        shared = implementation["shared_snapshot"]
    else:
        shared = load_version(root, implementation["shared_source_hash"])
    return dict(implementation["files"], **{"src/" + p: text for p, text in shared.items()})
