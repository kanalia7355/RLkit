"""実際の入口・状態遷移・プロセスを通した境界検証。"""

from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit.cli import main
from research_loop_kit.config import LoopError, make_config, read_json
from research_loop_kit.demo import ANSWERS, respond
from research_loop_kit.engine import Engine
from research_loop_kit.providers import command, process_run
from research_loop_kit.setup import initialize
from research_loop_kit.store import digest


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "研究 folder"

    def init(self, **overrides):
        cfg = {"backend": "demo", "seeds": [1, 2], "candidate_count": 4,
               "proposal_workers": 2, "experiments_per_cycle": 2, "max_parallel_agents": 2}
        cfg.update(overrides)
        initialize(self.root, cfg)
        return Engine(self.root)

    def proposal(self, **overrides):
        engine = self.init(**overrides)
        engine.answer(ANSWERS)
        engine.deepen()
        engine.run()
        engine.answer({q: "固定seed、合成データ、8更新" for q in engine.questions()})
        engine.propose()
        engine.run()
        self.assertEqual(engine.status()["phase"], "approval")
        return engine

    def accepted(self, **overrides):
        engine = self.proposal(**overrides)
        engine.accept(engine.status()["proposal_hash"])
        return engine

    def test_two_cycles_real_processes_and_knowledge(self):
        engine = self.accepted(max_cycles=2, autonomy="bounded", max_parallel_experiments=2)
        engine.run()
        state = Engine(self.root).status()
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(state["runs"], 8)
        self.assertEqual(len(state["history"]), 2)
        for cycle in state["history"]:
            for result in cycle["results"]:
                self.assertEqual(result["status"], "measured")
                self.assertEqual(result["n"], 2)
                self.assertLess(result["treatment_mean"], result["baseline_mean"])
                self.assertTrue((self.root / result["evidence"] / "preregistration.json").exists())
        self.assertEqual(len(read_json(self.root / "reports/knowledge.json")), 2)
        later_ideas = next(j for j in state["jobs"] if j["cycle"] == 2 and j["kind"] == "ideas")
        self.assertIn("reusable_lessons", (engine.ticket_dir(later_ideas) / "prompt.md").read_text(encoding="utf-8"))

    def test_active_agent_file_handoff_end_to_end(self):
        engine = self.init(backend="active")
        engine.answer(ANSWERS)
        engine.deepen()
        def drain():
            while True:
                job = engine.claim({"deepen", "ideas", "plan", "implement", "review"})
                if not job:
                    break
                ticket = engine.ticket(job)
                response = respond(job, engine.status())
                Path(ticket["response"]).write_text(json.dumps(response), encoding="utf-8")
                self.assertEqual(main(["submit", str(self.root), str(job["id"]), "--token", job["token"],
                                       "--file", ticket["response"]]), 0)
        drain()
        engine.answer({q: "比較条件を固定" for q in engine.questions()})
        engine.propose()
        drain()
        engine.accept(engine.status()["proposal_hash"])
        drain()
        engine.run(experiments_only=True)
        drain()
        self.assertEqual(engine.status()["phase"], "complete")
        self.assertEqual(engine.status()["runs"], 4)

    def test_empty_answers_cannot_start(self):
        engine = self.init()
        with self.assertRaises(LoopError):
            engine.deepen()
        engine.answer({"topic": "計算"})
        with self.assertRaises(LoopError):
            engine.deepen()

    def test_deepening_answers_required(self):
        engine = self.init()
        engine.answer(ANSWERS)
        engine.deepen()
        engine.run()
        with self.assertRaises(LoopError):
            engine.propose()
        self.assertEqual(len(engine.questions()), 4)

    def test_initialization_never_overwrites(self):
        self.root.mkdir()
        target = self.root / "CLAUDE.md"
        target.write_text("既存の内容", encoding="utf-8")
        with self.assertRaises(LoopError):
            initialize(self.root)
        self.assertEqual(target.read_text(encoding="utf-8"), "既存の内容")

    def test_config_invalid_values(self):
        for override in ({"max_cycles": True}, {"seeds": [1, 1]}, {"max_runs": -1},
                         {"backend": "unknown"}, {"candidate_count": 1}, {"mispelled": 2},
                         {"roles": {"review": {"backend": "unknown"}}}, {"max_wall_seconds": float("nan")}):
            with self.subTest(override=override), self.assertRaises(LoopError):
                make_config(override)

    def test_config_freezes_before_deepening(self):
        engine = self.init()
        engine.answer(ANSWERS)
        engine.deepen()
        with self.assertRaises(LoopError):
            engine.configure({"max_runs": 999})

    def test_no_execution_before_acceptance(self):
        engine = self.proposal()
        engine.run()
        self.assertEqual(engine.status()["runs"], 0)
        with self.assertRaises(LoopError):
            engine.accept("stale-hash")
        self.assertEqual(engine.status()["phase"], "approval")

    def test_revision_invalidates_approval(self):
        engine = self.proposal()
        previous = engine.status()["proposal_hash"]
        engine.revise("更新幅を小さくする")
        job = engine.claim()
        result = respond(job, engine.status())
        result["direction"] += "改訂"
        engine.submit(job["id"], job["token"], result)
        with self.assertRaises(LoopError):
            engine.accept(previous)

    def test_open_questions_block_acceptance(self):
        engine = self.proposal()
        engine.revise("データがまだない")
        job = engine.claim()
        result = respond(job, engine.status())
        result["open_questions"] = ["データの取得先"]
        engine.submit(job["id"], job["token"], result)
        with self.assertRaises(LoopError):
            engine.accept(engine.status()["proposal_hash"])

    def test_every_cycle_confirmation(self):
        engine = self.accepted(max_cycles=2)
        engine.run()
        state = engine.status()
        self.assertEqual(state["phase"], "approval")
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["runs"], 4)

    def test_parallel_claim_has_no_duplicates_and_obeys_cap(self):
        engine = self.init(candidate_count=8, proposal_workers=8)
        engine.answer(ANSWERS)
        engine.deepen()
        engine.run()
        engine.answer({q: "固定" for q in engine.questions()})
        engine.propose()
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = list(pool.map(lambda _: Engine(self.root).claim(), range(8)))
        claimed = [j for j in jobs if j]
        self.assertEqual(len(claimed), 2)
        self.assertEqual(len({j["id"] for j in claimed}), 2)

    def test_restart_keeps_claim_and_rejects_old_token(self):
        engine = self.init()
        engine.answer(ANSWERS)
        engine.deepen()
        job = engine.claim()
        restarted = Engine(self.root)
        self.assertIsNone(restarted.claim())
        restarted.fail(job["id"], job["token"], "プロセス停止を確認")
        restarted.retry(job["id"])
        new_job = restarted.claim()
        with self.assertRaises(LoopError):
            restarted.submit(job["id"], job["token"], respond(job, restarted.status()))
        restarted.submit(new_job["id"], new_job["token"], respond(new_job, restarted.status()))
        with self.assertRaises(LoopError):
            restarted.submit(new_job["id"], new_job["token"], respond(new_job, restarted.status()))
        with restarted.store.transaction() as db:
            rows = db.execute("SELECT status FROM attempts ORDER BY attempt").fetchall()
        self.assertEqual([r[0] for r in rows], ["failed", "done"])

    def test_budget_reserved_and_failure_preserved(self):
        engine = self.accepted(max_runs=1)
        engine.run()
        self.assertEqual(engine.status()["runs"], 1)
        failed = [j for j in engine.status()["jobs"] if j["status"] == "failed"]
        self.assertEqual(len(failed), 2)
        for job in failed:
            engine.skip_failed(job["id"])
        engine.run()
        self.assertEqual(engine.status()["phase"], "complete")
        self.assertTrue(all(r["status"] == "failed" for r in engine.status()["history"][0]["results"]))
        with engine.store.transaction() as db:
            for job in failed:
                self.assertEqual(db.execute("SELECT status FROM attempts WHERE job=?", (job["id"],)).fetchone()[0], "failed")

    def test_pause_prevents_claim(self):
        engine = self.init()
        engine.answer(ANSWERS)
        engine.deepen()
        engine.pause()
        self.assertIsNone(engine.claim())
        engine.resume()
        self.assertIsNotNone(engine.claim())

    def test_implementation_traversal_rejected(self):
        engine = self.accepted()
        job = engine.claim({"implement"})
        response = respond(job, engine.status())
        response["files"]["../escape.py"] = "print(1)"
        with self.assertRaises(LoopError):
            engine.submit(job["id"], job["token"], response)
        self.assertFalse((self.root.parent / "escape.py").exists())

    def test_invalid_metric_seed_is_not_success(self):
        engine = self.accepted()
        job = engine.claim({"implement"})
        response = respond(job, engine.status())
        response["files"]["experiment.py"] = response["files"]["experiment.py"].replace('"seed": a.seed', '"seed": 999')
        engine.submit(job["id"], job["token"], response)
        engine.run()
        failed = [j for j in engine.status()["jobs"] if j["status"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("seed", failed[0]["error"])

    def test_nonfinite_metrics_rejected(self):
        bad = Path(self.temp.name) / "bad.json"
        bad.write_text('{"treatment": NaN}', encoding="utf-8")
        with self.assertRaises(LoopError):
            read_json(bad)

    def test_supported_review_requires_measured_threshold(self):
        engine = self.accepted()
        while (job := engine.claim({"implement"})):
            engine.work(job)
        engine.run(experiments_only=True)
        review = engine.claim({"review"})
        response = respond(review, engine.status())
        changed = copy.deepcopy(review)
        changed["payload"]["results"][0]["threshold_met"] = False
        with self.assertRaises(LoopError):
            engine.validate_result(changed, response, engine.status())

    def test_provider_role_and_argv_keep_shell_chars_literal(self):
        cfg = make_config({"backend": "codex", "roles": {"review": {"backend": "custom",
            "custom_command": [sys.executable, "agent.py"], "model": "x; & y"}}})
        argv = command(cfg, "review")
        self.assertEqual(argv[-1], "x; & y")
        self.assertEqual(argv[0], sys.executable)

    def test_real_custom_provider_response_contract(self):
        script = Path(self.temp.name) / "provider.py"
        script.write_text('''import json
from pathlib import Path
Path("response.json").write_text(json.dumps({"understanding":"ファイル連携の動作確認", "questions":[{"id":"q1","question":"測定対象を具体化してください"}]}), encoding="utf-8")
''', encoding="utf-8")
        engine = self.init(backend="custom", custom_command=[sys.executable, str(script)], deep_questions=1)
        engine.answer(ANSWERS)
        engine.deepen()
        engine.run()
        self.assertEqual(engine.status()["phase"], "questions")
        self.assertEqual(len(engine.questions()), 1)

    def test_process_timeout(self):
        directory = Path(self.temp.name)
        with self.assertRaises(subprocess.TimeoutExpired):
            process_run([sys.executable, "-c", "import time; time.sleep(10)"], directory,
                        directory / "out.log", directory / "err.log", 0.1)


if __name__ == "__main__":
    unittest.main()
