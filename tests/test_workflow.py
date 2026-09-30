"""分岐、確認入口、診断、停止証跡、参考資料の境界検証。"""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit import references, stopping
from research_loop_kit.agent_entry import main as entry
from research_loop_kit.config import LoopError
from research_loop_kit.demo import ANSWERS, respond
from research_loop_kit.engine import Engine
from research_loop_kit.guards import verify_evidence
from research_loop_kit.sessions import Sessions


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.hub = Sessions(self.root)

    def create(self, **config):
        menu = self.hub.open()
        settings = dict(backend="demo", experiments_per_cycle=1, seeds=[1, 2])
        settings.update(config)
        choice = self.hub.select(menu["session_id"], "new", name="検証", settings=settings)
        return choice, Engine(self.root / choice["path"])

    def plan(self, **config):
        choice, e = self.create(**config)
        e.answer(ANSWERS)
        e.deepen()
        e.run()
        e.answer({q: "固定条件" for q in e.questions()})
        e.propose()
        e.run()
        return choice, e

    def complete(self, **config):
        choice, e = self.plan(**config)
        e.accept(e.status()["proposal_hash"])
        e.run()
        return choice, e

    def test_branch_copies_binary_inputs_and_import_paths_independently(self):
        choice, e = self.create(data_files=["data/raw.bin", "imports/old/input.csv"])
        for name, data in (("data/raw.bin", b"\x00\xff"), ("imports/old/input.csv", b"x\r\n3\r\n")):
            path = e.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        menu = self.hub.open()
        branch = self.hub.select(menu["session_id"], "branch", project_id=choice["project_id"], name="コピー")
        target = Engine(self.root / branch["path"])
        self.assertEqual(target.status()["prior_research"]["data_manifest"][0]["bytes"], 2)
        (e.root / "data/raw.bin").write_bytes(b"changed")
        self.assertEqual((target.root / "data/raw.bin").read_bytes(), b"\x00\xff")
        self.assertEqual((target.root / "imports/old/input.csv").read_bytes(), b"x\r\n3\r\n")

    def test_failed_copy_does_not_publish_study_or_select_session(self):
        choice, _ = self.create(data_files=["data/missing.csv"])
        menu = self.hub.open()
        with self.assertRaises(LoopError):
            self.hub.select(menu["session_id"], "branch", project_id=choice["project_id"], name="失敗")
        self.assertEqual(len(self.hub.catalog()), 1)
        self.assertEqual(list((self.hub.home / "import-staging").iterdir()), [])
        self.hub.select(menu["session_id"], "review", project_id=choice["project_id"])

    def test_input_copy_cannot_overwrite_initialized_instructions(self):
        choice, _ = self.create(data_files=["AGENT_GUIDE.md"])
        menu = self.hub.open()
        with self.assertRaisesRegex(LoopError, "衝突"):
            self.hub.select(menu["session_id"], "branch", project_id=choice["project_id"], name="衝突")
        self.assertEqual(len(self.hub.catalog()), 1)

    def test_changed_copy_is_rejected(self):
        choice, e = self.create(data_files=["data/a.csv"])
        path = e.root / "data/a.csv"
        path.parent.mkdir()
        path.write_text("original", encoding="utf-8")
        menu = self.hub.open()
        from research_loop_kit import sessions

        original = sessions.snapshot_inputs

        def changed(origin, target, expected):
            path.write_text("changed", encoding="utf-8")
            return original(origin, target, expected)

        with patch.object(sessions, "snapshot_inputs", changed), self.assertRaises(LoopError):
            self.hub.select(menu["session_id"], "branch", project_id=choice["project_id"], name="競合")
        self.assertEqual(len(self.hub.catalog()), 1)

    def test_confirmation_through_restart_entry_keeps_protocol_and_budget(self):
        choice, e = self.complete()
        menu = self.hub.open()
        project = menu["projects"][0]
        self.assertTrue(next(c for c in project["choices"] if c["id"] == "confirm")["available"])
        candidate = project["diagnostics"]["confirmation_candidates"][0]
        selected = self.hub.select(menu["session_id"], "confirm", project_id=choice["project_id"])
        sid = selected["session_id"]
        with self.assertRaises(LoopError):
            self.hub.target(sid, "configure")
        self.assertEqual(
            entry(
                self.root,
                [
                    "work",
                    sid,
                    "confirm",
                    "--cycle",
                    "1",
                    "--experiment",
                    "e1",
                    "--hash",
                    candidate["hash"],
                    "--seeds",
                    "101",
                    "102",
                ],
            ),
            0,
        )
        self.assertEqual(entry(self.root, ["work", sid, "run"]), 0)
        self.assertEqual(e.status()["runs"], 4)
        review = e.claim({"review"})
        e.submit(review["id"], review["token"], respond(review, e.status()))
        self.assertEqual(e.status()["history"][-1]["claim_status"]["e1"], "confirmed")
        self.assertEqual(entry(self.root, ["work", sid, "retry", "1"]), 2)

    def test_confirmation_disabled_without_runs_and_for_unfinished_study(self):
        _, e = self.complete(max_runs=2)
        self.assertEqual(e.status()["diagnostics"]["confirmation_candidates"], [])
        menu = self.hub.open()
        self.assertFalse(next(c for c in menu["projects"][0]["choices"] if c["id"] == "confirm")["available"])

    def test_diagnostic_uses_runtime_blocker_and_keeps_review_runnable(self):
        _, e = self.plan(max_agent_calls=6)
        self.assertEqual(e.status()["diagnostics"]["next_actions"][0]["command"], "accept_or_revise")
        e.accept(e.status()["proposal_hash"])
        diagnostic = e.status()["diagnostics"]
        pending = diagnostic["jobs"][0]
        self.assertIsNone(pending["blocker"])
        e.work(e.claim({"implement"}))
        self.assertEqual(e.status()["agent_calls"], 6)
        e.work(e.claim({"implementation_review"}))
        e.work(e.claim({"execute"}))
        review = next(j for j in e.status()["diagnostics"]["jobs"] if j["kind"] == "review")
        self.assertIsNone(review["blocker"])
        e.pause()
        self.assertEqual(e.status()["diagnostics"]["next_actions"][0]["command"], "resume")
        self.assertEqual(e.status()["diagnostics"]["jobs"][0]["blocker"], "wait")

    def test_stopping_record_detects_early_stop_and_tampering(self):
        _, e = self.complete()
        h = e.status()["history"][0]
        result = h["results"][0]
        record = e.root / result["evidence"] / "seed-1/termination.json"
        body = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(body["iterations"], 8)
        self.assertEqual(body["reason"], "fixed_iterations")
        body["iterations"] = 7
        record.write_text(json.dumps(body), encoding="utf-8")
        with self.assertRaisesRegex(LoopError, "停止"):
            verify_evidence(e.root, h)

    def test_missing_stopping_hook_fails_preflight_before_real_runs(self):
        _, e = self.plan()
        e.accept(e.status()["proposal_hash"])
        implementation = e.claim({"implement"})
        result = respond(implementation, e.status())
        result["files"]["experiment.py"] = result["files"]["experiment.py"].replace(
            ", stop=StopController.from_environment()", ""
        )
        e.submit(implementation["id"], implementation["token"], result)
        gate = e.claim({"implementation_review"})
        response = e.work(gate)
        self.assertIn("error", response)
        self.assertEqual(e.status()["runs"], 0)
        self.assertIsNone(e.claim({"execute"}))

    def test_new_plans_require_policy_but_legacy_tickets_remain_readable(self):
        _, e = self.plan()
        state = e.status()
        plan = copy.deepcopy(state["proposal"])
        plan["experiments"][0].pop("stop_policy")
        with self.assertRaisesRegex(LoopError, "stop_policy"):
            Engine._check_plan({"payload": {"require_stop_policy": True}}, plan, state)
        Engine._check_plan({"payload": {}}, plan, state)
        result = respond({"kind": "implement", "payload": {"experiment": plan["experiments"][0]}}, state)
        directory = self.root / "legacy-execution"
        directory.mkdir()
        for name, text in result["shared_files"].items():
            path = directory / "src" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        code = directory / "experiment.py"
        code.write_text(result["files"]["experiment.py"], encoding="utf-8")
        output = directory / "metrics.json"
        subprocess.run(
            [sys.executable, str(code), "--seed", "999", "--output", str(output)],
            env=dict(os.environ, PYTHONPATH=str(directory / "src")),
            check=True,
            timeout=10,
        )
        metrics = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(metrics["seed"], 999)
        self.assertGreater(metrics["baseline"], metrics["treatment"])

    def test_adaptive_policies_are_applied_by_real_execution(self):
        for kind in ("convergence", "no_improvement"):
            _, e = self.plan()
            e.revise("構造化した適応停止を使う")
            job = e.claim({"plan"})
            response = respond(job, e.status())
            policy = dict(kind=kind, max_iterations=8, min_iterations=3, patience=2, tolerance=1000000)
            if kind == "no_improvement":
                policy["direction"] = "minimize"
            response["experiments"][0].update(stop_policy=policy, stop_rule="3回以降に適応停止", method="最大8更新")
            e.submit(job["id"], job["token"], response)
            e.accept(e.status()["proposal_hash"])
            e.run()
            result = e.status()["history"][0]["results"][0]
            record = json.loads((e.root / result["evidence"] / "seed-1/termination.json").read_text(encoding="utf-8"))
            self.assertEqual(record["reason"], kind)
            self.assertEqual(record["iterations"], 3)

    def test_read_reference_requires_location_and_report_marks_unverified(self):
        _, e = self.plan()
        plan = copy.deepcopy(e.status()["proposal"])
        plan["references"] = [
            {"id": "r1", "source": "論文A", "claim": "収束", "relevance": "停止基準", "status": "read"}
        ]
        with self.assertRaises(LoopError):
            references.validate_references(plan)
        plan["references"][0].update(locator="第2節", note="条件付きの主張")
        plan["experiments"][0]["reference_ids"] = ["unknown"]
        with self.assertRaises(LoopError):
            references.validate_references(plan)
        plan["experiments"][0]["reference_ids"] = ["r1"]
        references.validate_references(plan)
        self.assertIn("外部未検証", "\n".join(references.report_lines(plan["references"])))


class StopTests(unittest.TestCase):
    def test_adaptive_policies_replay_and_stop_at_first_valid_reason(self):
        base = dict(max_iterations=10, min_iterations=3, patience=2, tolerance=0.01)
        for kind, values, n in (("convergence", [1, 1, 1], 3), ("no_improvement", [3, 2, 2, 2], 4)):
            policy = dict(base, kind=kind)
            if kind == "no_improvement":
                policy["direction"] = "minimize"
            stop = stopping.StopController(policy)
            for v in values:
                stop.step(v)
            self.assertEqual(stop.record()["iterations"], n)
            self.assertEqual(stopping.verify_record(stop.record(), policy)["reason"], kind)
            with self.assertRaises(ValueError):
                stop.step(1)
        stop = stopping.StopController(dict(base, kind="convergence"))
        for v in range(10):
            stop.step(v)
        self.assertEqual(stop.record()["reason"], "max_iterations")

    def test_invalid_policy_and_observations(self):
        for policy in (
            {"kind": "fixed_iterations", "max_iterations": True},
            {"kind": "fixed_iterations", "max_iterations": 1, "patience": 1},
            {"kind": "convergence", "max_iterations": 2, "min_iterations": 3, "patience": 1, "tolerance": 0.01},
        ):
            with self.assertRaises(ValueError):
                stopping.validate_policy(policy)
        stop = stopping.StopController({"kind": "fixed_iterations", "max_iterations": 1})
        with self.assertRaises(ValueError):
            stop.step(float("nan"))
        with self.assertRaises(ValueError):
            stop.record()


if __name__ == "__main__":
    unittest.main()
