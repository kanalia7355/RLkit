"""比較・事前登録・本文固定の偽陽性と改ざんを検証する。"""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from research_loop_kit import confirmation, quality, references, stopping
from research_loop_kit.config import LoopError
from research_loop_kit.demo import ANSWERS
from research_loop_kit.engine import Engine
from research_loop_kit.guards import verify_evidence
from research_loop_kit.sessions import Sessions
from research_loop_kit.store import digest


def protocol(result_hash="source", n=5, family=1):
    return {
        "family_id": "fixed",
        "members": [
            {"cycle": i + 1, "experiment": "e1", "result_hash": result_hash if i == 0 else f"source{i}"}
            for i in range(family)
        ],
        "seed_count": n,
        "method": "paired_exceedance_test",
        "alpha": 0.05,
        "multiplicity": "bonferroni",
        "missing_policy": "inconclusive",
        "rationale": "独立seedというモデル仮定",
    }


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.hub = Sessions(self.root)

    def create(self, complete=False):
        menu = self.hub.open()
        choice = self.hub.select(
            menu["session_id"],
            "new",
            name="品質検証",
            settings={"backend": "demo", "experiments_per_cycle": 1, "seeds": [1, 2]},
        )
        e = Engine(self.root / choice["path"])
        if complete:
            e.answer(ANSWERS)
            e.deepen()
            e.run()
            e.answer({q: "固定" for q in e.questions()})
            e.propose()
            e.run()
            e.accept(e.status()["proposal_hash"])
            e.run()
        return choice, e

    def test_binomial_ties_missing_and_family_adjustment(self):
        spec = {"direction": "maximize", "min_effect": 0.1}
        values = [{"baseline": 0, "treatment": 1}] * 5

        def analyze(p, values=values, **kw):
            return confirmation.analyze(values, spec, {"hash": digest(p), "protocol": p}, **kw)

        single = analyze(protocol())
        self.assertEqual(single["p_value"], 1 / 32)
        self.assertTrue(single["statistical_criterion_met"])
        multiple = analyze(protocol(family=2))
        self.assertEqual(multiple["alpha_per_comparison"], 0.025)
        self.assertEqual(multiple["status"], "threshold_replicated")
        self.assertEqual(analyze(protocol(), complete=False)["status"], "inconclusive")
        self.assertEqual(analyze(protocol(), values[:4])["status"], "inconclusive")
        ties = analyze(protocol(), [{"baseline": 0, "treatment": 0.1}] * 5)
        self.assertEqual(ties["p_value"], 1)
        self.assertEqual(ties["status"], "threshold_replicated")
        p = protocol()
        p["method"] = "descriptive_mean"
        self.assertIsNone(analyze(p)["p_value"])
        self.assertFalse(analyze(p)["statistical_criterion_met"])

    def test_preregistration_is_binding_and_single_use(self):
        _, e = self.create(complete=True)
        source = e.status()["history"][0]["results"][0]
        key = digest(source)
        p = protocol(key)
        registration = e.plan_confirmation(p)
        with self.assertRaises(LoopError):
            e.plan_confirmation(p)
        for seeds, h in ((list(range(101, 106)), None), ([101, 102], registration), (list(range(101, 106)), "bad")):
            with self.assertRaises(LoopError):
                e.confirm(1, "e1", key, seeds, h)
        e.confirm(1, "e1", key, list(range(101, 106)), registration)
        e.run()
        entry = e.status()["history"][-1]
        self.assertEqual(entry["claim_status"]["e1"], "registered_statistical_support")
        verify_evidence(e.root, entry)
        with self.assertRaisesRegex(LoopError, "やり直せません"):
            e.confirm(1, "e1", key, list(range(201, 206)), registration)
        forged = copy.deepcopy(entry)
        forged["results"][0]["confirmation_analysis"]["p_value"] = 0
        with self.assertRaises(LoopError):
            verify_evidence(e.root, forged)
        report = (e.root / "reports/MEETING_REPORT-002.md").read_text(encoding="utf-8")
        self.assertIn("registered_statistical_support", report)
        self.assertNotIn("検定は未実施", report)

    def test_both_comparison_records_replay_and_metrics_are_bound(self):
        _, e = self.create(complete=True)
        entry = e.status()["history"][0]
        r = entry["results"][0]
        policy = r["manifest"]["experiment"]["comparison_policy"]
        # 実行ディレクトリ名はランタイムの保存形式に従う。
        files = list((e.root / r["evidence"]).rglob("comparison.json"))
        self.assertEqual(len(files), 2)
        item = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(item["conditions"]["baseline"]["evaluations"], 1)
        self.assertEqual(item["conditions"]["treatment"]["evaluations"], 8)
        stopping.verify_comparison(item, policy)
        wrong = copy.deepcopy(item)
        wrong["conditions"].pop("baseline")
        with self.assertRaises(ValueError):
            stopping.verify_comparison(wrong, policy)
        with self.assertRaises(ValueError):
            stopping.verify_comparison(item, policy, {"baseline": -999, "treatment": -999})
        item["conditions"]["baseline"]["evaluations"] = 999
        files[0].write_text(json.dumps(item), encoding="utf-8")
        with self.assertRaises(LoopError):
            verify_evidence(e.root, entry)

    def test_contradictory_treatment_sidecars_are_rejected(self):
        _, e = self.create(complete=True)
        entry = e.status()["history"][0]
        r = entry["results"][0]
        path = next((e.root / r["evidence"]).rglob("termination.json"))
        record = json.loads(path.read_text(encoding="utf-8"))
        record["observations"] = [999.0] * len(record["observations"])
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(LoopError, "一致しません"):
            verify_evidence(e.root, entry)
        check = e.root / r["manifest"]["validation"]["evidence"] / "stop-check/termination.json"
        check.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(LoopError):
            quality.verify_comparison(
                check.parent / "comparison.json",
                r["manifest"]["experiment"]["comparison_policy"],
                json.loads((check.parent / "metrics.json").read_text(encoding="utf-8")),
            )

    def test_custom_cli_version_probe_keeps_script_and_role(self):
        from live_acceptance import probe_versions

        from research_loop_kit.config import make_config

        first = self.root / "agent-one.py"
        second = self.root / "agent-two.py"
        for p, version in ((first, "agent-one-v1"), (second, "agent-two-v2")):
            p.write_text(f"import sys\nassert sys.argv[1:] == ['--version']\nprint({version!r})", encoding="utf-8")
        cfg = make_config(
            {
                "backend": "custom",
                "custom_command": [sys.executable, str(first)],
                "roles": {"review": {"custom_command": [sys.executable, str(second)]}},
            }
        )
        versions = probe_versions(self.root, cfg)
        self.assertEqual(versions["deepen"]["version_command"], [sys.executable, str(first), "--version"])
        self.assertEqual(
            (self.root / versions["review"]["version_log"]).read_text(encoding="utf-8").strip(), "agent-two-v2"
        )
        self.assertEqual(
            (self.root / versions["plan"]["version_log"]).read_text(encoding="utf-8").strip(), "agent-one-v1"
        )

    def test_budget_equivalence_and_recording_limits(self):
        policy = {
            "basis": "iterations",
            "unit": "評価",
            "rationale": "同一割当",
            "baseline": {
                "stop_policy": {"kind": "fixed_iterations", "max_iterations": 1},
                "max_evaluations": 1,
                "max_wall_seconds": 60,
            },
            "treatment": {
                "stop_policy": {"kind": "fixed_iterations", "max_iterations": 2},
                "max_evaluations": 2,
                "max_wall_seconds": 60,
            },
        }
        with self.assertRaises(ValueError):
            stopping.validate_comparison(policy)
        policy["basis"] = "independent"
        recorder = stopping.ComparisonRecorder(policy)
        with self.assertRaises(ValueError):
            recorder.record()
        with self.assertRaises(ValueError), recorder.condition("baseline") as c:
            c.step(1, evaluations=2)
        with recorder.condition("baseline") as c:
            self.assertTrue(c.step(1))
        with self.assertRaises(ValueError):
            recorder.condition("baseline")
        with self.assertRaises(ValueError), recorder.condition("treatment") as c:
            c.step(1)  # 未完了の停止記録を受理しない。

    def test_frozen_source_quotes_and_branch_integrity(self):
        choice, e = self.create()
        path = e.root / "data/source.txt"
        path.parent.mkdir()
        path.write_bytes("根拠の本文\n条件: 合成データのみ\n".encode())
        source = e.register_reference("data/source.txt", "取得元を申告", "v1, UTF-8抽出")
        path.write_text("原本の後日変更", encoding="utf-8")
        ref = {
            "id": "r1",
            "source": "取得元を申告",
            "claim": "条件付きの根拠",
            "relevance": "比較",
            "status": "content_checked",
            "locator": "条件の行",
            "note": "限定条件を読む",
            "snapshot_hash": source["hash"],
            "quote": "条件: 合成データのみ",
            "assessment": "conditional",
            "conditions": "合成データだけ",
        }
        plan = {"experiments": [{"reference_ids": ["r1"]}], "references": [ref]}
        references.verify_references(e.root, plan, {source["hash"]: source})
        ref["quote"] = "存在しない引用"
        with self.assertRaises(LoopError):
            references.verify_references(e.root, plan, {source["hash"]: source})
        menu = self.hub.open()
        branch = self.hub.select(menu["session_id"], "branch", project_id=choice["project_id"], name="資料の継承")
        target = self.root / branch["path"]
        self.assertIn("根拠の本文", references.source_text(target, source))
        (target / source["record"]["snapshot"]).write_text("改ざん", encoding="utf-8")
        with self.assertRaises(LoopError):
            references.source_text(target, source)
        for bad in ("", "../outside", ".env"):
            with self.assertRaises(LoopError):
                e.register_reference(bad, "origin", "v1")
        forged = copy.deepcopy(source)
        forged["record"]["sha256"] = "../../outside"
        forged["hash"] = digest(forged["record"])
        with self.assertRaises(LoopError):
            references.source_text(e.root, forged)

    def test_real_subprocess_failures_retry_with_fresh_token(self):
        cases = {
            "invalid_json": "from pathlib import Path\nPath('response.json').write_text('{',encoding='utf-8')",
            "missing_response": "pass",
            "nonzero": "raise SystemExit(7)",
            "timeout": "import time\ntime.sleep(5)",
        }
        for name, code in cases.items():
            with self.subTest(name=name):
                script = self.root / f"{name}.py"
                script.write_text(code, encoding="utf-8")
                menu = self.hub.open()
                choice = self.hub.select(
                    menu["session_id"],
                    "new",
                    name=name,
                    settings={
                        "backend": "custom",
                        "custom_command": [sys.executable, str(script)],
                        "deep_questions": 1,
                        "agent_timeout_seconds": 1,
                    },
                )
                e = Engine(self.root / choice["path"])
                e.answer(ANSWERS)
                e.deepen()
                job = e.claim({"deepen"})
                self.assertIn("error", e.work(job))
                e.retry(job["id"])
                script.write_text(
                    "import json\nfrom pathlib import Path\nPath('response.json').write_text(json.dumps({'understanding':'fixture only','questions':[{'id':'q1','question':'fixed fixture?'}]}),encoding='utf-8')",
                    encoding="utf-8",
                )
                retry = e.claim({"deepen"})
                self.assertNotEqual(job["token"], retry["token"])
                self.assertEqual(e.work(retry)["status"], "done")
                self.assertEqual(e.status()["phase"], "questions")
                self.assertEqual(len(e.status()["failed_attempts"]), 1)
                with self.assertRaises(LoopError):
                    e.submit(job["id"], job["token"], {})

    def test_live_harness_does_not_claim_missing_cli_as_passed(self):
        from live_acceptance import run

        result = run(
            self.root / "live", {"backend": "custom", "custom_command": [str(self.root / "nonexistent-agent")]}, ANSWERS
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["authentication"], "not_verified")
