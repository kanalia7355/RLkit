"""共通srcを本当にimportして実行し、版と並列更新を検証する。"""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit.config import LoopError
from research_loop_kit.demo import ANSWERS, respond
from research_loop_kit.engine import Engine
from research_loop_kit.guards import verify_evidence
from research_loop_kit.setup import initialize
from research_loop_kit.sessions import Sessions


class SharedSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "研究"
        initialize(self.root, {"backend": "demo", "seeds": [1], "experiments_per_cycle": 2,
                               "max_cycles": 2, "autonomy": "bounded"})
        self.engine = Engine(self.root)
        e = self.engine
        e.answer(ANSWERS)
        e.deepen()
        e.run()
        e.answer({q: "固定" for q in e.questions()})
        e.propose()
        e.run()
        e.accept(e.status()["proposal_hash"])

    def test_shared_module_reused_across_experiments_and_cycles(self):
        self.engine.run()
        state = self.engine.status()
        self.assertEqual(state["phase"], "complete")
        self.assertTrue((self.root / "src/research/quadratic.py").is_file())
        self.assertTrue((self.root / "experiments/cycle-001/e1/experiment.py").is_file())
        versions = {r["manifest"]["shared_source_hash"] for h in state["history"] for r in h["results"]}
        self.assertEqual(len(versions), 1)
        later = [j for j in state["jobs"] if j["kind"] == "implement" and j["cycle"] == 2]
        self.assertTrue(all(j["result"]["shared_files"] == {} for j in later))
        for entry in state["history"]:
            self.assertEqual(len(verify_evidence(self.root, entry)), 2)

    def test_execute_uses_frozen_src_even_after_working_src_changes(self):
        job = self.engine.claim({"implement"})
        response = respond(job, self.engine.status())
        self.engine.submit(job["id"], job["token"], response)
        (self.root / "src/research/quadratic.py").write_text("raise RuntimeError('latest must not execute')\n", encoding="utf-8")
        execute = self.engine.claim({"execute"})
        result = self.engine.work(execute)
        self.assertEqual(result["status"], "done")
        recorded = next(j for j in self.engine.status()["jobs"] if j["id"] == execute["id"])["result"]
        self.assertTrue(recorded["threshold_met"])
        snapshot = self.engine.ticket_dir(execute) / "code/src/research/quadratic.py"
        self.assertNotIn("latest must not execute", snapshot.read_text(encoding="utf-8"))

    def test_conflicting_parallel_updates_do_not_overwrite_src(self):
        first = self.engine.claim({"implement"})
        second = self.engine.claim({"implement"})
        a = respond(first, self.engine.status())
        b = respond(second, self.engine.status())
        b["shared_files"]["research/quadratic.py"] += "\n# conflicting version\n"
        self.engine.submit(first["id"], first["token"], a)
        with self.assertRaisesRegex(LoopError, "競合"):
            self.engine.submit(second["id"], second["token"], b)
        self.assertEqual((self.root / "src/research/quadratic.py").read_text(encoding="utf-8"), a["shared_files"]["research/quadratic.py"])

    def test_path_escape_and_invalid_shared_python_rejected(self):
        job = self.engine.claim({"implement"})
        for changes in ({"../escape.py": "x=1"}, {"research/method.py": "def broken("}):
            response = respond(job, self.engine.status())
            response["shared_files"] = changes
            with self.assertRaises(LoopError):
                self.engine.submit(job["id"], job["token"], response)
        self.assertFalse((self.root / "escape.py").exists())

    def test_shared_snapshot_tamper_blocks_review(self):
        self.engine.run()
        entry = self.engine.status()["history"][0]
        result = entry["results"][0]
        path = self.root / result["evidence"] / "code/src/research/quadratic.py"
        path.write_text("# replaced\n", encoding="utf-8")
        with self.assertRaisesRegex(LoopError, "コード"):
            verify_evidence(self.root, entry)

    def test_branch_copies_common_src_without_sharing_mutable_files(self):
        hub_root = Path(self.temp.name) / "hub"
        hub_root.mkdir()
        hub = Sessions(hub_root)
        first = hub.open()["session_id"]
        origin = hub.select(first, "new", name="元研究")
        original = hub_root / origin["path"] / "src/research/helper.py"
        original.write_text("def metric(x):\n    return x * x\n", encoding="utf-8")
        second = hub.open()["session_id"]
        branch = hub.select(second, "branch", project_id=origin["project_id"], name="別条件")
        copied = hub_root / branch["path"] / "src/research/helper.py"
        self.assertEqual(copied.read_bytes(), original.read_bytes())
        copied.write_text("def metric(x):\n    return abs(x)\n", encoding="utf-8")
        self.assertIn("x * x", original.read_text(encoding="utf-8"))
        self.assertFalse(Engine(hub_root / branch["path"]).status()["authorized"])


if __name__ == "__main__":
    unittest.main()
