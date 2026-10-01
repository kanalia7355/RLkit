"""無期限再開、稼働時間、旧版期限の互換性を確認する。"""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit import budget
from research_loop_kit.config import LoopError, dump, make_config, upgrade
from research_loop_kit.demo import ANSWERS
from research_loop_kit.engine import Engine
from research_loop_kit.sessions import Sessions, can_continue


class BudgetTests(unittest.TestCase):
    def test_default_unlimited_and_legacy_explicit_deadline(self):
        self.assertIsNone(make_config()["max_wall_seconds"])
        self.assertEqual(make_config({"max_wall_seconds": 60})["wall_time_basis"], "active_jobs")
        self.assertEqual(upgrade({"max_wall_seconds": 60})["wall_time_basis"], "elapsed")
        for cap in (0, -1, True, 1.5, float("inf"), float("nan")):
            with self.subTest(cap=cap), self.assertRaises(LoopError):
                make_config({"max_wall_seconds": cap})
        with self.assertRaises(LoopError):
            make_config({"wall_time_basis": "unknown"})

    def test_active_intervals_exclude_waits_and_skills_and_merge_parallelism(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.executescript(
            "CREATE TABLE jobs(id INTEGER, kind TEXT); CREATE TABLE events(id INTEGER PRIMARY KEY,time REAL,kind TEXT,body TEXT);"
        )
        db.executemany("INSERT INTO jobs VALUES (?,?)", [(1, "execute"), (2, "implement"), (3, "skill_design")])
        events = [
            (10, "claimed", 1),
            (12, "claimed", 2),
            (15, "completed", 1),
            (18, "failed", 2),
            (20, "claimed", 3),
            (100, "completed", 3),
            (200, "claimed", 1),
            (203, "completed", 1),
        ]
        for t, kind, identifier in events:
            db.execute("INSERT INTO events(time,kind,body) VALUES (?,?,?)", (t, kind, json.dumps({"id": identifier})))
        self.assertEqual(budget.active_seconds(db, 5, now=1000), 11)
        self.assertEqual(budget.active_seconds(db, None, now=1000), 0)
        db.execute("INSERT INTO events(time,kind,body) VALUES (300,'claimed','{\"id\":1}')")
        self.assertEqual(budget.active_seconds(db, 5, now=305), 16)
        # retry後の取得済み仕事も計上し、稼働有無不明の時間を勝手に消さない。

    def test_clock_rollback_does_not_refund_completed_or_committed_running_time(self):
        from unittest.mock import patch

        from research_loop_kit.setup import initialize

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "study"
            initialize(root, {"max_wall_seconds": 10})
            e = Engine(root)
            with e.store.transaction() as db:
                state = e.store.state(db)
                state["started"] = 90
                identifier = e.store.job(db, 1, "implement", {})
                db.execute(
                    "INSERT INTO events(time,kind,body) VALUES (100,'claimed',?)", (json.dumps({"id": identifier}),)
                )
                with patch("research_loop_kit.budget.time.time", return_value=105):
                    e.store.save(db, state)
            with patch("research_loop_kit.budget.time.time", return_value=95):
                self.assertEqual(e.status()["active_seconds"], 5)
            with e.store.transaction() as db:
                db.execute(
                    "INSERT INTO events(time,kind,body) VALUES (110,'completed',?)", (json.dumps({"id": identifier}),)
                )
            for now in (120, 105, 95):
                with patch("research_loop_kit.budget.time.time", return_value=now):
                    state = e.status()
                    self.assertEqual(state["active_seconds"], 10)
                    self.assertIn("実時間", e._budget_exhausted(state))

    def test_finite_active_and_elapsed_blockers_use_correct_clock(self):
        state = {
            "config": make_config({"max_wall_seconds": 10}),
            "started": 1,
            "active_seconds": 3,
            "agent_calls": 0,
            "phase": "executing",
        }
        self.assertEqual(budget.remaining_seconds(state, now=1000), 7)
        self.assertIsNone(Engine._budget_exhausted(state))
        self.assertIsNone(can_continue(state))
        state["active_seconds"] = 10
        self.assertIn("実時間", Engine._budget_exhausted(state))
        self.assertIsNotNone(can_continue(state))
        state["config"]["wall_time_basis"] = "elapsed"
        self.assertEqual(budget.remaining_seconds(state, now=5), 6)

    def test_menu_selection_ignores_clock_ticks_but_rejects_state_changes(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temporary:
            hub = Sessions(Path(temporary).resolve())
            menu = hub.open()
            choice = hub.select(
                menu["session_id"],
                "new",
                name="稼働中",
                settings={"backend": "demo", "experiments_per_cycle": 1, "seeds": [1, 2], "max_wall_seconds": 600},
            )
            e = Engine(hub.root / choice["path"])
            e.answer(ANSWERS)
            e.deepen()
            e.run()
            e.answer({q: "固定" for q in e.questions()})
            e.propose()
            e.run()
            e.accept(e.status()["proposal_hash"])
            job = e.claim({"implement"})
            menu = hub.open()
            with patch("research_loop_kit.budget.time.time", return_value=time.time() + 10):
                hub.select(menu["session_id"], "review", project_id=choice["project_id"])
            menu = hub.open()
            e.fail(job["id"], job["token"], "実プロセス起動前の中断")
            with self.assertRaises(LoopError):
                hub.select(menu["session_id"], "review", project_id=choice["project_id"])

    def test_unlimited_old_start_executes_and_menu_serializes_null(self):
        with tempfile.TemporaryDirectory() as temporary:
            hub = Sessions(Path(temporary).resolve())
            menu = hub.open()
            choice = hub.select(
                menu["session_id"],
                "new",
                name="長期中断",
                settings={"backend": "demo", "experiments_per_cycle": 1, "seeds": [1, 2]},
            )
            e = Engine(hub.root / choice["path"])
            e.answer(ANSWERS)
            e.deepen()
            e.run()
            e.answer({q: "固定" for q in e.questions()})
            e.propose()
            e.run()
            e.accept(e.status()["proposal_hash"])
            with e.store.transaction() as db:
                state = e.store.state(db)
                state["started"] = time.time() - 365 * 86400
                e.store.save(db, state)
            self.assertIsNone(can_continue(e.status()))
            e.pause()
            e.resume()
            e.run()
            state = e.status()
            self.assertEqual(state["runs"], 2)
            self.assertEqual(state["phase"], "complete")
            self.assertIsNone(state["diagnostics"]["deadline"])
            self.assertIsNone(state["diagnostics"]["remaining_seconds"])
            self.assertNotIn("Infinity", dump(hub.open()))
            # 稼働時間の派生値はDB本文へ保存しない。
            with e.store.transaction() as db:
                self.assertNotIn("active_seconds", json.loads(db.execute("SELECT body FROM state").fetchone()[0]))
