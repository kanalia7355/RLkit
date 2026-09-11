"""承認・失敗・再セッションを含むスキル育成と報告書の実経路検証。"""

import copy
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit.config import LoopError
from research_loop_kit.demo import ANSWERS, respond
from research_loop_kit.engine import Engine
from research_loop_kit.evolution import validate_design, validate_build
from research_loop_kit.prompts import render
from research_loop_kit.sessions import Sessions
from research_loop_kit.setup import initialize


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "研究"
        initialize(self.root, {"backend": "demo", "seeds": [1], "experiments_per_cycle": 1})
        self.engine = Engine(self.root)

    def design_ready(self):
        e = self.engine
        e.answer(ANSWERS)
        e.deepen()
        e.run()
        e.answer({q: "固定" for q in e.questions()})
        e.propose()
        e.run()
        e.accept(e.status()["proposal_hash"])
        e.run()
        return e.status()["skill_candidates"][0]

    def test_report_contains_measured_values_methods_and_evidence(self):
        self.design_ready()
        state = self.engine.status()
        result = state["history"][0]["results"][0]
        text = (self.root / "reports/MEETING_REPORT-001.md").read_text(encoding="utf-8")
        self.assertIn(str(result["baseline_mean"]), text)
        self.assertIn(result["manifest"]["experiment"]["method"], text)
        self.assertIn(result["evidence"] + "/preregistration.json", text)
        self.assertIn("MEETING_REPORT-001.md", state["history"][0]["completion_gate"]["documents"])
        for family in (".agents", ".claude", ".gemini", ".opencode"):
            self.assertTrue((self.root / family / "skills/research-report/references/report-structure.md").is_file())

    def test_design_needs_separate_exact_approval(self):
        candidate = self.design_ready()
        self.assertEqual(candidate["status"], "approval")
        self.engine.run(skills_only=True)
        self.assertFalse(self.engine.status().get("active_skills"))
        self.assertFalse(any(j["kind"] == "skill_build" for j in self.engine.status()["jobs"]))
        with self.assertRaises(LoopError):
            self.engine.skill_decision(candidate["id"], "accept", "stale")
        self.engine.skill_decision(candidate["id"], "reject", candidate["design_hash"])
        self.assertEqual(self.engine.status()["skill_candidates"][0]["status"], "rejected")

    def test_approval_builds_tests_activates_and_disable_stops_injection(self):
        candidate = self.design_ready()
        self.engine.skill_decision(candidate["id"], "accept", candidate["design_hash"])
        self.engine.run(skills_only=True)
        state = self.engine.status()
        active = state["active_skills"][candidate["design"]["name"]]
        self.assertEqual(active["tests_passed"], 3)
        self.assertTrue((self.root / active["path"] / "references/evidence.md").is_file())
        job = {"kind": "review", "id": 900, "token": "test", "payload": {}}
        prompt = render(job, state, self.root / "response.json", self.root)
        self.assertIn("承認・検証済み研究スキル: demo-evidence-check", prompt)
        self.engine.disable_skill(active["name"])
        self.assertNotIn("承認・検証済み研究スキル: demo-evidence-check",
                         render(job, self.engine.status(), self.root / "response.json", self.root))
        self.assertTrue((self.root / active["path"] / "test.stderr.log").is_file())

    def test_failed_behavior_test_never_activates(self):
        candidate = self.design_ready()
        self.engine.skill_decision(candidate["id"], "accept", candidate["design_hash"])
        job = self.engine.claim({"skill_build"})
        response = respond(job, self.engine.status())
        response["files"]["scripts/check.py"] = "def valid(value):\n    return True\n"
        with self.assertRaises(LoopError):
            self.engine.submit(job["id"], job["token"], response)
        state = self.engine.status()
        self.assertFalse(state.get("active_skills"))
        self.assertEqual(next(j for j in state["jobs"] if j["id"] == job["id"])["status"], "failed")
        self.engine.retry(job["id"])
        self.engine.run(skills_only=True)
        self.assertTrue(self.engine.status().get("active_skills"))

    def test_missing_references_or_unapproved_resources_are_rejected(self):
        candidate = self.design_ready()
        design = copy.deepcopy(candidate["design"])
        design["references"] = []
        with self.assertRaises(LoopError):
            validate_design(design)
        self.engine.skill_decision(candidate["id"], "accept", candidate["design_hash"])
        job = self.engine.claim({"skill_build"})
        response = respond(job, self.engine.status())
        response["files"]["../outside.py"] = "print(1)"
        with self.assertRaises(LoopError):
            validate_build(response, candidate["design"])
        del response["files"]["../outside.py"]
        response["files"]["SKILL.md"] = response["files"]["SKILL.md"].replace("(references/evidence.md)", "(missing.md)")
        with self.assertRaises(LoopError):
            validate_build(response, candidate["design"])

    def test_later_approval_does_not_restart_expired_research(self):
        candidate = self.design_ready()
        with self.engine.store.transaction() as db:
            state = self.engine.store.state(db)
            state["started"] = time.time() - 100000
            self.engine.store.save(db, state)
        runs = self.engine.status()["runs"]
        self.engine.skill_decision(candidate["id"], "accept", candidate["design_hash"])
        self.engine.run(skills_only=True)
        self.assertTrue(self.engine.status().get("active_skills"))
        self.assertEqual(self.engine.status()["runs"], runs)

    def test_improve_session_allows_skills_but_blocks_experiments(self):
        hub = Sessions(Path(self.temp.name))
        menu = hub.open()
        selection = hub.select(menu["session_id"], "new", name="改善用")
        again = hub.open()
        hub.select(again["session_id"], "improve", project_id=selection["project_id"])
        self.assertTrue(hub.target(again["session_id"], "skill-next").is_dir())
        for command in ("run", "next", "submit", "accept", "configure"):
            with self.assertRaises(LoopError):
                hub.target(again["session_id"], command)

    def test_revision_revokes_failed_build_and_requires_new_approval(self):
        candidate = self.design_ready()
        self.engine.skill_decision(candidate["id"], "accept", candidate["design_hash"])
        job = self.engine.claim({"skill_build"})
        self.engine.fail(job["id"], job["token"], "設計の変更が必要")
        self.engine.skill_decision(candidate["id"], "revise", candidate["design_hash"], "対象条件を絞る")
        with self.assertRaises(LoopError):
            self.engine.retry(job["id"])
        self.engine.run(skills_only=True)
        self.assertEqual(self.engine.status()["skill_candidates"][0]["status"], "approval")
        self.assertFalse(self.engine.status().get("active_skills"))

    def test_modified_active_skill_is_not_loaded(self):
        candidate = self.design_ready()
        self.engine.skill_decision(candidate["id"], "accept", candidate["design_hash"])
        self.engine.run(skills_only=True)
        state = self.engine.status()
        active = next(iter(state["active_skills"].values()))
        (self.root / active["path"] / "references/evidence.md").write_text("変更", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "変更"):
            render({"kind": "review", "id": 900, "token": "test", "payload": {}}, state, self.root / "response.json", self.root)

    def test_resume_skills_preserves_research_pause(self):
        candidate = self.design_ready()
        self.engine.pause()
        self.engine.skill_decision(candidate["id"], "accept", candidate["design_hash"])
        self.assertIsNone(self.engine.claim({"skill_build"}))
        self.engine.resume_skills()
        self.engine.run(skills_only=True)
        self.assertTrue(self.engine.status()["paused"])
        self.assertTrue(self.engine.status()["active_skills"])


if __name__ == "__main__":
    unittest.main()
