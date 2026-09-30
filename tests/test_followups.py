"""レビュー指摘への対応（予算切れ時のレビュー、状態の分離、旧DB移行、書き込み順序など）の検証。"""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit import sessions as sessions_module
from research_loop_kit.config import LoopError
from research_loop_kit.demo import ANSWERS, respond
from research_loop_kit.engine import Engine
from research_loop_kit.evolution import KINDS
from research_loop_kit.guards import paired_bootstrap_ci, verify_evidence
from research_loop_kit.prompts import render
from research_loop_kit.sessions import Sessions
from research_loop_kit.setup import initialize


def edit_state(root, change):
    """テスト用: state本文を直接書き換える（通常の操作では行わない）。"""
    db = sqlite3.connect(Path(root) / ".rlk/state.sqlite3")
    try:
        body = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
        change(body)
        db.execute("UPDATE state SET body=? WHERE id=1", (json.dumps(body, ensure_ascii=False),))
        db.commit()
    finally:
        db.close()


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "研究"

    def accepted(self, **overrides):
        cfg = {
            "backend": "demo",
            "seeds": [1, 2, 3],
            "candidate_count": 4,
            "proposal_workers": 2,
            "experiments_per_cycle": 2,
            "max_cycles": 2,
            "autonomy": "bounded",
        }
        cfg.update(overrides)
        initialize(self.root, cfg)
        engine = Engine(self.root)
        engine.answer(ANSWERS)
        engine.deepen()
        engine.run()
        engine.answer({q: "固定" for q in engine.questions()})
        engine.propose()
        engine.run()
        engine.accept(engine.status()["proposal_hash"])
        return engine

    def until_review(self, engine):
        while True:
            job = engine.claim({"implement"})
            if not job:
                break
            engine.submit(job["id"], job["token"], respond(job, engine.status()))
        engine.run(experiments_only=True)
        self.assertEqual(engine.status()["phase"], "reviewing")

    def finish_review(self, engine):
        job = engine.claim({"review"})
        self.assertIsNotNone(job)
        engine.submit(job["id"], job["token"], respond(job, engine.status()))

    # 3: 予算切れでもレビューと報告は完了する
    def test_review_runs_after_agent_call_budget_is_exhausted(self):
        engine = self.accepted()
        self.until_review(engine)
        edit_state(self.root, lambda s: s.update(agent_calls=s["config"]["max_agent_calls"]))
        self.finish_review(engine)
        state = engine.status()
        self.assertEqual(state["phase"], "complete")
        self.assertIn("回数", state["stop_reason"])
        self.assertEqual(len(state["history"]), 1)
        self.assertFalse([j for j in state["jobs"] if j["kind"] == "ideas" and j["cycle"] == 2])
        self.assertTrue((self.root / "reports/cycle-001.md").is_file())
        self.assertTrue((self.root / "reports/MEETING_REPORT-001.md").is_file())

    def test_review_runs_after_wall_time_is_exhausted(self):
        engine = self.accepted()
        self.until_review(engine)
        edit_state(self.root, lambda s: s.update(started=time.time() - s["config"]["max_wall_seconds"] - 1))
        self.finish_review(engine)
        state = engine.status()
        self.assertEqual(state["phase"], "complete")
        self.assertIn("実時間", state["stop_reason"])

    def test_other_jobs_still_stop_at_budget(self):
        engine = self.accepted()
        edit_state(self.root, lambda s: s.update(agent_calls=s["config"]["max_agent_calls"]))
        with self.assertRaisesRegex(LoopError, "回数の上限"):
            engine.claim({"implement"})

    # 5: 共通srcはハッシュ参照、履歴は別テーブル
    def test_payload_references_shared_source_by_hash_and_ticket_expands_it(self):
        engine = self.accepted()
        engine.run()
        state = engine.status()
        self.assertEqual(state["phase"], "complete")
        for job in state["jobs"]:
            self.assertNotIn("shared_sources", job["payload"])
            if job["result"]:
                self.assertNotIn("shared_snapshot", job["result"])
        later = next(j for j in state["jobs"] if j["kind"] == "implement" and j["cycle"] == 2)
        self.assertIn("shared_source_hash", later["payload"])
        prompt = render(later, state, self.root / "response.json", root=self.root)
        inputs = prompt.split("入力:")[1]
        self.assertIn("def compare", inputs)  # 共通srcは作業票で全文に展開される
        self.assertNotIn('"values"', prompt.split("入力:")[0])  # 履歴はseed別の値を省いて渡す

    def test_history_is_stored_outside_the_state_body(self):
        engine = self.accepted(max_cycles=1)
        engine.run()
        self.assertEqual(engine.status()["phase"], "complete")
        db = sqlite3.connect(self.root / ".rlk/state.sqlite3")
        body = json.loads(db.execute("SELECT body FROM state").fetchone()[0])
        rows = db.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        db.close()
        self.assertNotIn("history", body)
        self.assertEqual(rows, 1)
        self.assertEqual(len(engine.status()["history"]), 1)

    def test_legacy_database_is_migrated(self):
        engine = self.accepted(max_cycles=1)
        engine.run()
        history = engine.status()["history"]
        db = sqlite3.connect(self.root / ".rlk/state.sqlite3")
        db.execute("DROP TABLE history")
        db.commit()
        db.close()

        def legacy(body):
            body["history"] = history
            del body["config"]["max_skill_calls"]

        edit_state(self.root, legacy)
        state = Engine(self.root).status()
        self.assertEqual(state["history"], history)
        self.assertEqual(state["config"]["max_skill_calls"], 20)
        self.assertEqual(len(verify_evidence(self.root, state["history"][0])), 2)

    # 6: DB更新が失敗したら作業用srcを書き換えない
    def test_failed_acceptance_does_not_touch_working_src(self):
        engine = self.accepted()
        job = engine.claim({"implement"})
        response = respond(job, engine.status())
        target = self.root / "src/research/quadratic.py"
        self.assertFalse(target.exists())
        with patch.object(Engine, "_advance", side_effect=RuntimeError("DB更新失敗")):
            with self.assertRaises(RuntimeError):
                engine.submit(job["id"], job["token"], response)
        self.assertFalse(target.exists())
        engine.submit(job["id"], job["token"], response)
        self.assertTrue(target.exists())

    # 低: 統計・スキル上限・セッション整理
    def test_bootstrap_interval_is_recorded_and_verified(self):
        engine = self.accepted(max_cycles=1)
        engine.run()
        entry = engine.status()["history"][0]
        result = entry["results"][0]
        low, high = result["effect_ci95"]
        self.assertLessEqual(low, result["effect_mean"])
        self.assertGreaterEqual(high, result["effect_mean"])
        result["effect_ci95"] = [low - 1, high]
        with self.assertRaisesRegex(LoopError, "再計算"):
            verify_evidence(self.root, entry)
        self.assertIsNone(paired_bootstrap_ci([1.0]))
        self.assertEqual(paired_bootstrap_ci([1.0, 2.0, 3.0]), paired_bootstrap_ci([1.0, 2.0, 3.0]))

    def test_skill_calls_are_capped(self):
        engine = self.accepted(max_cycles=1, max_skill_calls=1)
        self.until_review(engine)
        self.finish_review(engine)
        self.assertTrue([j for j in engine.status()["jobs"] if j["kind"] == "skill_design"])
        edit_state(self.root, lambda s: s.update(skill_calls=1))
        with self.assertRaisesRegex(LoopError, "スキル作業回数"):
            engine.claim(set(KINDS))

    def test_old_sessions_are_pruned(self):
        hub_root = Path(self.temp.name) / "hub"
        hub_root.mkdir()
        hub = Sessions(hub_root)
        first = hub.open()["session_id"]
        db = sqlite3.connect(hub.db_path)
        db.execute("UPDATE sessions SET created=? WHERE id=?", (time.time() - 40 * 24 * 3600, first))
        db.commit()
        db.close()
        with patch.object(sessions_module, "SESSION_KEEP", 1):
            hub.open()
        db = sqlite3.connect(hub.db_path)
        ids = [row[0] for row in db.execute("SELECT id FROM sessions")]
        db.close()
        self.assertNotIn(first, ids)
        self.assertEqual(len(ids), 1)


if __name__ == "__main__":
    unittest.main()
