"""Verify delivery of procedural skills through real setup and job rendering."""

from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit.engine import Engine
from research_loop_kit.prompts import PHASE_SKILLS, render
from research_loop_kit.setup import initialize


class GenericSkillsTests(unittest.TestCase):
    def test_resources_reach_all_agent_families_and_real_job_packets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            initialize(root)
            state = Engine(root).status()
            assets = files("research_loop_kit") / "assets/skills"
            for kind in ("plan", "implement", "implementation_review", "review"):
                packet = render(
                    {"kind": kind, "id": 1, "token": "test", "payload": {}},
                    state,
                    root / "response.json",
                )
                self.assertIn("回答JSONだけ", packet)
                for name in PHASE_SKILLS[kind]:
                    source = assets / name
                    self.assertIn(source.joinpath("SKILL.md").read_text(encoding="utf-8"), packet)
                    for resource in source.rglob("*.md"):
                        relative = resource.relative_to(source)
                        for family in (".agents", ".claude", ".gemini", ".opencode"):
                            copy = root / family / "skills" / name / relative
                            self.assertEqual(copy.read_bytes(), resource.read_bytes())
                    reference = source / "references/contract.md"
                    if reference.is_file():
                        self.assertIn(reference.read_text(encoding="utf-8"), packet)

    def test_distribution_has_no_deleted_plan_links(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "docs/SKILL_MIGRATION.md").exists())
        for path in [root / "README.md", *(root / "docs").glob("*.md")]:
            self.assertNotIn("SKILL_MIGRATION.md", path.read_text(encoding="utf-8"))
        self.assertTrue((root / "docs/SKILLS.md").is_file())


if __name__ == "__main__":
    unittest.main()
