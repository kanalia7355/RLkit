"""ファイル操作の共通処理: リンク検査・新規作成・原子的な置換。"""

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import stat
import tempfile

from .config import LoopError

_REPARSE_POINT = 0x400  # Windowsのジャンクション等


def is_link(path):
    info = Path(path).lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def no_links(path, base):
    """base配下で、baseからpathまでの各要素がリンク・ジャンクションでないことを確認する。

    base自体とその親（macOSの/var -> /private/var、~/Dropboxのリンク等）は利用者の
    環境であり検査しない。baseは呼出元で解決済みの実パスを渡す。
    """
    path, base = Path(path), Path(base)
    try:
        relative = path.relative_to(base)
    except ValueError:
        raise LoopError(f"基準フォルダ外のパスです: {path}") from None
    current = base
    for part in relative.parts:
        current = current / part
        if is_link(current):
            raise LoopError("リンク・ジャンクション経由のファイルは扱いません")


def write_new(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def write_atomic(path, text):
    """同じフォルダの一時ファイルへ書いてから置換し、途中状態の文書を残さない。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


@contextmanager
def rollback_files(paths, base):
    """DBのcommitまで元ファイルを保持し、例外時に複数ファイルの更新を戻す。

    単一ファイルの置換は原子的だが、DBと複数ファイルをまたぐ原子性はない。
    この復旧は捕捉できる例外用で、プロセスの強制終了・電源断は対象外。
    """
    originals = {}
    directories = set()
    with tempfile.TemporaryDirectory(prefix="publish-", dir=base / ".rlk") as temporary:
        for index, path in enumerate(paths):
            parent = path.parent
            while not parent.exists():
                directories.add(parent)
                parent = parent.parent
            no_links(parent, base)
            if path.exists() or path.is_symlink():
                no_links(path, base)
                backup = Path(temporary) / str(index)
                shutil.copy2(path, backup)
                originals[path] = backup
            else:
                originals[path] = None
        try:
            yield
        except BaseException:
            for path, backup in reversed(list(originals.items())):
                if backup is None:
                    path.unlink(missing_ok=True)
                else:
                    os.replace(backup, path)
            for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
                if directory.exists() and not any(directory.iterdir()):
                    directory.rmdir()
            raise
