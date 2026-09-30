"""研究の計画・実装・実測・確認段階と、スキル有用性の境界検証。"""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit import evolution, quality
from research_loop_kit.cli import main
from research_loop_kit.config import LoopError, dump
from research_loop_kit.demo import ANSWERS, respond
from research_loop_kit.engine import Engine
from research_loop_kit.guards import verify_evidence
from research_loop_kit.setup import initialize
from research_loop_kit.store import digest


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "研究"

    def accepted(self, **overrides):
        config = dict(backend="demo", seeds=[1, 2], experiments_per_cycle=1, max_cycles=1)
        config.update(overrides)
        initialize(self.root, config)
        if config.get("data_files"):
            (self.root / "data").mkdir()
            (self.root / "data/input.csv").write_text("x\n3\n", encoding="utf-8")
        e = Engine(self.root)
        e.answer(ANSWERS)
        e.deepen()
        e.run()
        e.answer({k: "条件固定" for k in e.questions()})
        e.propose()
        e.run()
        e.accept(e.status()["proposal_hash"])
        return e

    def ready_to_execute(self, engine):
        implementation = engine.claim({"implement"})
        self.assertEqual(engine.work(implementation)["status"], "done")
        review = engine.claim({"implementation_review"})
        self.assertEqual(engine.work(review)["status"], "done")
        return engine.claim({"execute"})

    def complete(self, **overrides):
        e = self.accepted(**overrides)
        e.run()
        self.assertEqual(e.status()["phase"], "complete")
        return e

    def test_execution_requires_separate_review_and_passing_tests(self):
        e = self.accepted()
        e.work(e.claim({"implement"}))
        self.assertIsNone(e.claim({"execute"}))
        j = e.claim({"implementation_review"})
        r = respond(j, e.status())
        self.assertIn(
            "code",
            json.loads(
                (e.ticket(j) and Path(e.ticket(j)["prompt"]).read_text()).split("入力:\n```json\n")[1].split("\n```")[0]
            ),
        )
        e.submit(j["id"], j["token"], r)
        execution = e.claim({"execute"})
        self.assertIsNotNone(execution)
        self.assertEqual(execution["payload"]["validation"]["tests_passed"], 3)
        self.assertEqual(e.status()["validation_calls"], 1)

    def test_mismatched_plan_checks_cannot_approve(self):
        e = self.accepted()
        e.work(e.claim({"implement"}))
        j = e.claim({"implementation_review"})
        r = respond(j, e.status())
        r["checks"]["metric"]["status"] = "failed"
        with self.assertRaisesRegex(LoopError, "不一致"):
            e.submit(j["id"], j["token"], r)
        self.assertIsNone(e.claim({"execute"}))

    def test_failed_review_test_never_starts_experiment_and_can_retry(self):
        e = self.accepted()
        e.work(e.claim({"implement"}))
        j = e.claim({"implementation_review"})
        r = respond(j, e.status())
        r["tests"] = {
            "test_wrong.py": "import unittest\nclass Wrong(unittest.TestCase):\n    def test_wrong(self):\n        self.assertEqual(1, 2)\n"
        }
        with self.assertRaises(LoopError):
            e.submit(j["id"], j["token"], r)
        self.assertIsNone(e.claim({"execute"}))
        e.retry(j["id"])
        next_job = e.claim({"implementation_review"})
        self.assertEqual(e.work(next_job)["status"], "done")
        self.assertIsNotNone(e.claim({"execute"}))

    def test_rejected_implementation_is_reported_without_running(self):
        e = self.accepted()
        e.work(e.claim({"implement"}))
        j = e.claim({"implementation_review"})
        r = respond(j, e.status())
        r.update(decision="rejected", summary="対照条件が計画と違う")
        r["checks"]["baseline"]["status"] = "failed"
        e.submit(j["id"], j["token"], r)
        e.run()
        self.assertEqual(e.status()["runs"], 0)
        self.assertEqual(e.status()["history"][0]["results"][0]["status"], "failed")
        self.assertIn("不承認", (self.root / "reports/MEETING_REPORT-001.md").read_text(encoding="utf-8"))

    def test_validation_call_budget_is_enforced(self):
        e = self.accepted(experiments_per_cycle=2, max_validation_calls=1)
        with self.assertRaisesRegex(LoopError, "実行前レビュー回数"):
            e.run()
        self.assertEqual(e.status()["validation_calls"], 1)
        self.assertEqual(e.status()["runs"], 2)

    def test_data_snapshot_and_environment_are_saved_and_checked(self):
        e = self.complete(data_files=["data/input.csv"])
        entry = e.status()["history"][0]
        result = entry["results"][0]
        manifest = result["manifest"]
        self.assertEqual(manifest["data_manifest"][0]["bytes"], 4)
        self.assertTrue(manifest["environment"]["python"])
        evidence = self.root / result["evidence"]
        self.assertTrue((evidence / "requirements-lock.txt").is_file())
        frozen = evidence / "inputs/data/input.csv"
        self.assertEqual(frozen.read_bytes(), (self.root / "data/input.csv").read_bytes())
        (self.root / "data/input.csv").write_text("x\n99\n", encoding="utf-8")
        verify_evidence(self.root, entry)  # original changes do not alter the completed experiment
        frozen.write_text("x\n99\n", encoding="utf-8")
        with self.assertRaisesRegex(LoopError, "入力データ"):
            verify_evidence(self.root, entry)

    def test_data_change_after_review_prevents_execution(self):
        e = self.accepted(data_files=["data/input.csv"])
        j = self.ready_to_execute(e)
        (self.root / "data/input.csv").write_text("x\n4\n", encoding="utf-8")
        result = e.work(j)
        self.assertIn("入力データ", result["error"])
        self.assertEqual(e.status()["runs"], 0)

    def test_validation_record_tampering_prevents_execution(self):
        e = self.accepted()
        j = self.ready_to_execute(e)
        folder = self.root / j["payload"]["validation"]["evidence"]
        (folder / "tests/test_contract.py").write_text("# changed", encoding="utf-8")
        self.assertIn("検証", e.work(j)["error"])
        self.assertEqual(e.status()["runs"], 0)

    def test_input_paths_reject_escape_links_and_credentials(self):
        e = self.accepted()
        for path in ("../outside.csv", ".env", "/tmp/data.csv", "data/../secret.csv"):
            with self.subTest(path=path), self.assertRaises(LoopError):
                quality.data_manifest(e.root, [path])

    def test_confirmation_reuses_frozen_protocol_and_fresh_seeds(self):
        e = self.complete()
        source = e.status()["history"][0]["results"][0]
        self.assertEqual(e.status()["history"][0]["claim_status"]["e1"], "exploratory")
        for seeds in ([1], [1, 101], [101, 101]):
            with self.assertRaises(LoopError):
                e.confirm(1, "e1", digest(source), seeds)
        self.assertEqual(
            main(
                [
                    "confirm",
                    str(e.root),
                    "--cycle",
                    "1",
                    "--experiment",
                    "e1",
                    "--hash",
                    digest(source),
                    "--seeds",
                    "101",
                    "102",
                ]
            ),
            0,
        )
        e.run()
        entry = e.status()["history"][1]
        confirmation = entry["results"][0]
        self.assertEqual(confirmation["manifest"]["code_hash"], source["manifest"]["code_hash"])
        self.assertEqual(confirmation["manifest"]["experiment"], source["manifest"]["experiment"])
        self.assertEqual(confirmation["manifest"]["seeds"], [101, 102])
        self.assertEqual(entry["claim_status"]["e1"], "confirmed")
        verify_evidence(self.root, entry)
        self.assertIn("確認実験", (self.root / "reports/MEETING_REPORT-002.md").read_text(encoding="utf-8"))
        self.assertIn("探索段階", (self.root / "reports/KNOWLEDGE.md").read_text(encoding="utf-8"))

    def test_confirmation_does_not_reset_budgets_and_rejects_stale_result(self):
        e = self.complete(max_runs=2)
        source = e.status()["history"][0]["results"][0]
        with self.assertRaisesRegex(LoopError, "ハッシュ"):
            e.confirm(1, "e1", "wrong", [101])
        with self.assertRaisesRegex(LoopError, "予算"):
            e.confirm(1, "e1", digest(source), [101])
        self.assertEqual(e.status()["runs"], 2)

    def test_partial_results_are_reported_but_cannot_support_claims(self):
        e = self.complete(seeds=[1, 2, 3], max_runs=1)
        entry = e.status()["history"][0]
        result = entry["results"][0]
        self.assertEqual((result["status"], result["n"], result["planned_n"]), ("partial", 1, 3))
        self.assertFalse(result["threshold_met"])
        self.assertTrue(result["stop_reason"])
        verify_evidence(self.root, entry)
        report = (self.root / "reports/MEETING_REPORT-001.md").read_text(encoding="utf-8")
        self.assertIn("1 / 3", report)
        self.assertIn("実験予算", report)
        j = next(j for j in e.status()["jobs"] if j["kind"] == "review")
        bad = copy.deepcopy(j["result"])
        bad["experiments"][0]["assessment"] = "supported"
        with self.assertRaises(LoopError):
            e.validate_result(j, bad, e.status())
        with self.assertRaises(LoopError):
            e.confirm(1, "e1", digest(result), [101])

    def test_seed_failure_preserves_only_completed_measurements(self):
        e = self.accepted(seeds=[1, 2, 3])
        j = self.ready_to_execute(e)
        from research_loop_kit import engine as module

        original = module.process_run
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise LoopError("seed2 failure")
            return original(*args, **kwargs)

        with patch.object(module, "process_run", side_effect=fail_second):
            self.assertEqual(e.work(j)["status"], "done")
        e.run()
        entry = e.status()["history"][0]
        self.assertEqual(entry["results"][0]["n"], 1)
        self.assertEqual(e.status()["runs"], 2)
        verify_evidence(self.root, entry)

    def activated_skill(self):
        e = self.complete()
        candidate = e.status()["skill_candidates"][0]
        e.skill_decision(candidate["id"], "accept", candidate["design_hash"])
        e.run(skills_only=True)
        active = next(iter(e.status()["active_skills"].values()))
        return e, active

    def assessment(self, active, scores=((0, 1), (1, 1))):
        planned = {
            "version": active["version"],
            "metric": "欠落を正しく検出",
            "direction": "maximize",
            "minimum_improvement": 0.25,
            "method": "同一の過去入力に対するスキルなし・ありの判定を比較",
            "cases": [
                {
                    "id": f"case-{i}",
                    "kind": "normal" if i == 0 else "adverse",
                    "input": {"baseline": 2} if i == 0 else {"baseline": 2, "treatment": 1},
                }
                for i in range(len(scores))
            ],
        }
        protocol = Engine(self.root).plan_skill_assessment(active["name"], planned)
        cases = []
        for i, (baseline, improved) in enumerate(scores):
            case = {"id": f"case-{i}", "kind": "normal" if i == 0 else "adverse"}
            for mode, score in (("baseline", baseline), ("with_skill", improved)):
                name = f"evaluation/{i}-{mode}.json"
                path = self.root / name
                path.parent.mkdir(exist_ok=True)
                path.write_text(
                    dump(
                        {
                            "case_id": case["id"],
                            "mode": mode,
                            "skill_version": active["version"],
                            "metric": "欠落を正しく検出",
                            "protocol_hash": protocol,
                            "score": score,
                            "input": {"baseline": 2} if i == 0 else {"baseline": 2, "treatment": 1},
                            "outcome": "保存した出力と期待した欠落・正常判定を比較した",
                        }
                    ),
                    encoding="utf-8",
                )
                case[mode] = {"score": score, "evidence": name}
            cases.append(case)
        return {
            "version": active["version"],
            "protocol_hash": protocol,
            "metric": "欠落を正しく検出",
            "direction": "maximize",
            "minimum_improvement": 0.25,
            "method": "同一の過去入力に対するスキルなし・ありの判定を比較",
            "cases": cases,
        }

    def test_skill_usefulness_is_separate_versioned_and_tamper_checked(self):
        e, active = self.activated_skill()
        self.assertEqual(active["quality_status"], "behavior_validated")
        assessment = self.assessment(active)
        e.assess_skill(active["name"], assessment)
        updated = e.status()["active_skills"][active["name"]]
        self.assertEqual(updated["quality_status"], "utility_supported")
        evidence = updated["utility_assessment"]
        evolution.verify_utility(e.root, evidence)
        file = e.root / evidence["evidence"] / "case-000.json"
        file.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(LoopError, "比較証跡"):
            evolution.verify_utility(e.root, evidence)
        e.disable_skill(active["name"])
        self.assertFalse(e.status()["active_skills"])
        self.assertEqual(e.status()["skill_candidates"][0]["status"], "disabled")

    def test_regression_is_not_labeled_useful(self):
        e, active = self.activated_skill()
        e.assess_skill(active["name"], self.assessment(active, scores=((0, 1), (1, 0))))
        self.assertEqual(e.status()["active_skills"][active["name"]]["quality_status"], "regression")

    def test_skill_evaluation_requires_matching_evidence_and_fixed_version(self):
        e, active = self.activated_skill()
        assessment = self.assessment(active)
        bad = copy.deepcopy(assessment)
        bad["version"] = "old"
        with self.assertRaisesRegex(LoopError, "スキル版"):
            e.assess_skill(active["name"], bad)
        bad = copy.deepcopy(assessment)
        bad["cases"][0]["with_skill"]["score"] = 999
        with self.assertRaisesRegex(LoopError, "スコア"):
            e.assess_skill(active["name"], bad)
        path = self.root / assessment["cases"][0]["with_skill"]["evidence"]
        body = json.loads(path.read_text(encoding="utf-8"))
        body["input"] = {"different": True}
        path.write_text(dump(body), encoding="utf-8")
        with self.assertRaisesRegex(LoopError, "比較入力"):
            e.assess_skill(active["name"], assessment)
