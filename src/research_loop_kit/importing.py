"""選択された既存研究の資料を、実行しないスナップショットとして取り込む。"""

import hashlib
from pathlib import Path, PurePosixPath
import stat

from .config import LoopError, QUESTIONS, dump, nonempty
from .store import digest, write_new

MAX_FILES = 200
MAX_BYTES = 100 * 1024 * 1024
EXCLUDED = {".git", ".rlk", ".research", ".agents", ".claude", ".gemini", ".opencode", "__pycache__", ".venv", "node_modules", ".ssh", ".aws", ".azure", ".kube"}


def no_links(path):
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise LoopError("リンク・ジャンクション経由の資料は取り込めません")


def preview(source, paths):
    root = Path(source).absolute()
    no_links(root)
    if not root.is_dir():
        raise LoopError("取り込み元はフォルダを指定してください")
    if not paths or len(paths) > MAX_FILES or len(set(paths)) != len(paths):
        raise LoopError(f"重複のないファイルを1〜{MAX_FILES}件指定してください")
    manifest = []
    total = 0
    for name in sorted(paths):
        if not isinstance(name, str) or "\\" in name or ":" in name:
            raise LoopError("資料パスは取り込み元からの相対パスを/区切りで指定してください")
        relative = PurePosixPath(name)
        if relative.is_absolute() or any(p in ("..", ".", "") for p in name.split("/")):
            raise LoopError("資料のパス逸脱は許可されません")
        if set(relative.parts) & EXCLUDED or any(p.lower().startswith('.env') for p in relative.parts) or relative.suffix.lower() in (".pem", ".key"):
            raise LoopError(f"状態DB・Agent設定・認証情報は資料として取り込みません: {name}")
        path = root / name
        no_links(path)
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise LoopError(f"通常ファイルを指定してください: {name}")
        size = path.stat().st_size
        total += size
        if total > MAX_BYTES:
            raise LoopError("選択資料は合計100MiB以内にしてください")
        sha = hashlib.sha256()
        read_bytes = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                read_bytes += len(chunk)
                if read_bytes > size:
                    raise LoopError("読み取り中に資料のサイズが変わりました。再確認してください")
                sha.update(chunk)
        if read_bytes != size:
            raise LoopError("読み取り中に資料のサイズが変わりました。再確認してください")
        manifest.append({"path": name, "bytes": size, "sha256": sha.hexdigest()})
    result = {"source": str(root.resolve()), "files": manifest, "total_bytes": total}
    return dict(result, hash=digest(result))


def validate_context(context):
    if not isinstance(context, dict) or set(context) != {"summary", "answers"}:
        raise LoopError("取り込み整理はsummaryとanswersのオブジェクトです")
    nonempty(context["summary"], "研究の進捗・既存方針・未解決事項の要約")
    answers = context["answers"]
    if not isinstance(answers, dict) or set(answers) - set(QUESTIONS):
        raise LoopError("answersには確認済みの基本質問IDだけを指定してください")
    for key, value in answers.items():
        nonempty(value, key)


def copy_snapshot(destination, inspection, context):
    """転送中の変更も照合。呼出元の非公開ステージへ書き込む。"""
    source = Path(inspection["source"])
    for entry in inspection["files"]:
        path = source / entry["path"]
        no_links(path)
        with path.open("rb") as stream:
            data = stream.read(entry["bytes"] + 1)
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise LoopError("プレビュー後に資料が変わりました。再確認してください")
        target = destination / "imports/source" / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    write_new(destination / "imports/MANIFEST.json", dump(inspection) + "\n")
    write_new(destination / "imports/CONTEXT.md", "# 既存研究の整理\n\n" + context["summary"] +
              "\n\n取り込み資料は未再検証の過去資料です。新たな実測・採用済み計画・実行権限にはしません。\n")
