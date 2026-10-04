"""空の研究フォルダへ共通スキルとAgent入口を配置する。"""

from importlib.resources import files
from pathlib import Path

from .config import LoopError, make_config
from .fsutil import write_new
from .store import Store


def initialize(root, overrides=None):
    root = Path(root).resolve()
    config = make_config(overrides)
    if root.exists() and any(root.iterdir()):
        raise LoopError("初期化先には空のフォルダを指定してください。既存の設定は上書きしません")
    root.mkdir(parents=True, exist_ok=True)
    write_new(root / "src/research/__init__.py", '"""研究内で共有する処理。"""\n')
    (root / "experiments").mkdir()
    assets = files("research_loop_kit") / "assets"
    instructions = (assets / "AGENT_GUIDE.md").read_text(encoding="utf-8")
    write_new(root / "AGENT_GUIDE.md", instructions)
    for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        write_new(root / name, "# Research Loop Kit\n\nこの研究の操作手順は `AGENT_GUIDE.md` を読んでください。\n")
    ensure_skills(root)
    write_new(root / ".gitignore", ".rlk/\n.env\n.env.*\n__pycache__/\n*.pyc\n")
    write_new(
        root / "START_HERE.md",
        "# 研究を始める\n\nこのフォルダを好きなAI Agentで開き、「AGENT_GUIDE.mdを読んで、研究のセットアップから進めて」と伝えてください。\n\nCLIから始める場合は `rlk interview .`。実行状態は `rlk status .`、一時停止は `rlk pause .` です。\n",
    )
    state = {
        "schema_version": 1,
        "config": config,
        "phase": "interview",
        "answers": {},
        "cycle": 0,
        "agent_calls": 0,
        "runs": 0,
        "started": None,
        "paused": False,
        "authorized": False,
        "history": [],
    }
    Store(root).initialize(state)
    return str(root)


def ensure_skills(root):
    """起動先へ未配置の同梱スキルを追加する。既存スキルは変更しない。"""
    from .fsutil import is_link

    root = Path(root).resolve()
    assets = files("research_loop_kit") / "assets/skills"

    def copy_resources(source, target):
        for item in source.iterdir():
            if item.is_dir():
                copy_resources(item, target / item.name)
            else:
                try:
                    write_new(target / item.name, item.read_text(encoding="utf-8"))
                except FileExistsError:
                    pass

    for family in (".agents", ".claude", ".gemini", ".opencode"):
        parent = root / family
        destination = parent / "skills"
        if any(path.exists() and (is_link(path) or not path.is_dir()) for path in (parent, destination)):
            continue
        if parent.is_symlink() or destination.is_symlink():
            continue
        for skill in assets.iterdir():
            if skill.is_dir():
                target = destination / skill.name
                if target.exists() or target.is_symlink():
                    continue
                copy_resources(skill, target)
