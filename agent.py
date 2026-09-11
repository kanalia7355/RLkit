"""Agent用の内部入口。clone後のpipインストールは不要。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from research_loop_kit.agent_entry import main

if __name__ == "__main__":
    raise SystemExit(main(ROOT))
