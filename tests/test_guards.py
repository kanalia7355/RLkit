"""ガードを実際のレビュー受理経路から検証する。"""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit.config import LoopError
from research_loop_kit.demo import ANSWERS, respond
from research_loop_kit.engine import Engine
from research_loop_kit.guards import inspect_code
from research_loop_kit.setup import initialize


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "研究"
        initialize(self.root, {"backend": "demo", "seeds": [1, 2], "max_cycles": 2,
                               "autonomy": "bounded", "experiments_per_cycle": 1})
        self.engine = Engine(self.root)

    def review_ready(self):
        e = self.engine
        e.answer(ANSWERS)
        e.deepen()
        e.run()
        e.answer({q: "条件固定" for q in e.questions()})
        e.propose()
        e.run()
        e.accept(e.status()["proposal_hash"])
        while job := e.claim({"implement"}):
            e.work(job)
        e.run(experiments_only=True)
        job = e.claim({"review"})
        return job, respond(job, e.status())

    def test_tampered_metrics_block_next_cycle(self):
        job, response = self.review_ready()
        r = job["payload"]["results"][0]
        path = self.root / r["evidence"] / "seed-1/metrics.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["treatment"] += 1
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(LoopError, "測定値"):
            self.engine.submit(job["id"], job["token"], response)
        state = self.engine.status()
        self.assertEqual(state["history"], [])
        self.assertFalse(any(j["cycle"] == 2 for j in state["jobs"]))

    def test_missing_log_blocks_completion(self):
        job, response = self.review_ready()
        r = job["payload"]["results"][0]
        (self.root / r["evidence"] / "seed-1/stdout.log").unlink()
        with self.assertRaisesRegex(LoopError, "ログ"):
            self.engine.submit(job["id"], job["token"], response)
        self.assertEqual(self.engine.status()["history"], [])

    def test_failed_report_gate_rolls_back_and_resubmission_recovers(self):
        job, response = self.review_ready()
        with patch("research_loop_kit.engine.verify_reports", side_effect=LoopError("本文不一致")):
            with self.assertRaisesRegex(LoopError, "本文不一致"):
                self.engine.submit(job["id"], job["token"], response)
        self.assertEqual(self.engine.status()["history"], [])
        self.engine.submit(job["id"], job["token"], response)
        state = self.engine.status()
        self.assertEqual(state["cycle"], 2)
        self.assertIn("completion_gate", state["history"][0])
        for name in ("KNOWLEDGE.md", "SESSION_LOG.md", "CLUSTERS.md", "COMPARISON.md",
                     "SKILL_CANDIDATES.md", "ISSUES.md", "cycle-001.md", "cycle-001-CHECKS.md"):
            self.assertIn(name, state["history"][0]["completion_gate"]["documents"])
            self.assertTrue((self.root / "reports" / name).is_file())

    def test_progress_and_audit_are_actual_execution_outputs(self):
        job, _ = self.review_ready()
        r = job["payload"]["results"][0]
        progress = json.loads((self.root / r["evidence"] / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(progress["completed_seeds"], [1, 2])
        self.assertEqual(progress["remaining_seeds"], [])
        self.assertEqual(progress["eta_seconds_estimate"], 0)
        self.assertIn("code_audit", r["manifest"])

    def test_static_advisory_detects_ignored_config_and_encoding(self):
        audit = inspect_code({"experiment.py": "def compute(config):\n    return 3\nopen('result.txt', 'w')\n"})
        self.assertEqual(audit["status"], "warning")
        self.assertTrue(any("設定引数" in x for x in audit["findings"]))
        self.assertTrue(any("encoding" in x for x in audit["findings"]))
        clean = inspect_code({"experiment.py": "def compute(config):\n    return config['x']\ncompute({'x': 3})\nopen('x', 'wb')\n"})
        self.assertEqual(clean["findings"], [])

    def test_adapted_skills_are_distributed_and_loaded_into_tickets(self):
        job, _ = self.review_ready()
        text = Path(self.engine.ticket(job)["prompt"]).read_text(encoding="utf-8")
        self.assertIn("name: cycle-completeness-guard", text)
        self.assertIn("name: experiment-review-panel", text)
        self.assertIn("GitHub Issue", text)
        for family in (".agents", ".claude", ".gemini", ".opencode"):
            self.assertEqual(len(list((self.root / family / "skills").glob("*/SKILL.md"))), 18)


if __name__ == "__main__":
    unittest.main()
