import contextlib
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

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

    def test_crlf_assets_are_installed_as_lf_without_content_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            source = package / "assets/skills/example"
            source.mkdir(parents=True)
            text = "---\nname: example\n---\n日本語の手順\n"
            (source / "SKILL.md").write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
            root = Path(tmp) / "study"
            with patch("research_loop_kit.setup.files", return_value=package):
                ensure_skills(root)
            for family in (".agents", ".claude", ".gemini", ".opencode"):
                self.assertEqual((root / family / "skills/example/SKILL.md").read_bytes(), text.encode("utf-8"))
