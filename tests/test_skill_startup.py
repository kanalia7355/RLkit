import contextlib
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit.agent_entry import main
from research_loop_kit.engine import Engine
from research_loop_kit.setup import ensure_skills, initialize


class SkillStartupTests(unittest.TestCase):
    def test_agent_start_installs_and_preserves_custom_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            custom = root / ".claude/skills/wiring-smoke-guard/SKILL.md"
            custom.parent.mkdir(parents=True)
            custom.write_text("custom")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(root, ["open"]), 0)
            self.assertEqual(custom.read_text(), "custom")
            installed = root / ".claude/skills/repro-checker/SKILL.md"
            self.assertTrue(installed.is_file())
            modified = installed.stat().st_mtime_ns
            ensure_skills(root)
            self.assertEqual(installed.stat().st_mtime_ns, modified)

    def test_existing_research_gets_missing_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "study"
            initialize(root)
            shutil.rmtree(root / ".claude/skills/repro-checker")
            Engine(root).status()
            self.assertTrue((root / ".claude/skills/repro-checker/references/contract.md").is_file())

    def test_linked_provider_directory_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (root / ".claude").symlink_to(outside, target_is_directory=True)
            ensure_skills(root)
            self.assertEqual(list(outside.iterdir()), [])
