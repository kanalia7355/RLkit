"""空の研究フォルダへ共通スキルとAgent入口を配置する。"""

from importlib.resources import files
from pathlib import Path

from .config import LoopError, make_config
from .store import Store, write_new


def initialize(root, overrides=None):
    root = Path(root).resolve()
    config = make_config(overrides)
    if root.exists() and any(root.iterdir()):
        raise LoopError("初期化先には空のフォルダを指定してください。既存の設定は上書きしません")
    root.mkdir(parents=True, exist_ok=True)
    assets = files("research_loop_kit") / "assets"
    instructions = (assets / "AGENT_GUIDE.md").read_text(encoding="utf-8")
    write_new(root / "AGENT_GUIDE.md", instructions)
    for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        write_new(root / name, "# Research Loop Kit\n\nこの研究の操作手順は `AGENT_GUIDE.md` を読んでください。\n")
    skill_root = assets / "skills"
    def copy_resources(source, target):
        for item in source.iterdir():
            if item.is_dir():
                copy_resources(item, target / item.name)
            else:
                write_new(target / item.name, item.read_text(encoding="utf-8"))
    for skill in skill_root.iterdir():
        if not skill.is_dir():
            continue
        for family in (".agents", ".claude", ".gemini", ".opencode"):
            copy_resources(skill, root / family / "skills" / skill.name)
    write_new(root / ".gitignore", ".rlk/\n.env\n.env.*\n__pycache__/\n*.pyc\n")
    write_new(root / "START_HERE.md", "# 研究を始める\n\nこのフォルダを好きなAI Agentで開き、「AGENT_GUIDE.mdを読んで、研究のセットアップから進めて」と伝えてください。\n\nCLIから始める場合は `rlk interview .`。実行状態は `rlk status .`、一時停止は `rlk pause .` です。\n")
    state = {"schema_version": 1, "config": config, "phase": "interview", "answers": {},
             "cycle": 0, "agent_calls": 0, "runs": 0, "started": None,
             "paused": False, "authorized": False, "history": []}
    Store(root).initialize(state)
    return str(root)
