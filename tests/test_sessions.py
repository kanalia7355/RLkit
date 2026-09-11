"""cloneの自動入口から、再セッションと研究分岐までを検証する。"""

import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research_loop_kit.agent_entry import hook, main
from research_loop_kit.config import LoopError
from research_loop_kit.demo import ANSWERS, respond
from research_loop_kit.engine import Engine
from research_loop_kit.sessions import Sessions
from research_loop_kit.store import digest


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hub = Sessions(self.root)

    def create(self, **settings):
        menu = self.hub.open()
        result = self.hub.select(menu["session_id"], "new", name="関心から始める研究", settings=settings)
        return result, Engine(self.root / result["path"])

    def planned(self):
        choice, engine = self.create(backend="demo", seeds=[1, 2])
        engine.answer(ANSWERS)
        engine.deepen()
        engine.run()
        engine.answer({q: "具体的な対照を固定" for q in engine.questions()})
        engine.propose()
        engine.run()
        return choice, engine

    def test_first_open_asks_topic_without_creating_a_study(self):
        menu = self.hub.open()
        self.assertEqual(menu["kind"], "setup")
        self.assertIn("topic", menu["first_questions"])
        self.assertEqual(self.hub.catalog(), [])
        with self.assertRaises(LoopError):
            self.hub.target(menu["session_id"], "run")

    def test_multiple_studies_show_last_choice_without_selecting_it(self):
        first, _ = self.create()
        second, _ = self.create()
        menu = self.hub.open()
        self.assertEqual(len(menu["projects"]), 2)
        self.assertEqual(menu["kind"], "resume")
        self.assertEqual(menu["last_selection"]["project_id"], second["project_id"])
        with self.assertRaises(LoopError):
            self.hub.target(menu["session_id"], "run")
        selected = self.hub.select(menu["session_id"], "continue", project_id=first["project_id"])
        self.assertEqual(self.hub.open()["last_selection"]["project_id"], selected["project_id"])

    def test_relaunch_requires_new_choice(self):
        choice, engine = self.create()
        engine.answer({"topic": "画像", "interest": "境界の曖昧さ"})
        menu = Sessions(self.root).open()
        self.assertEqual(menu["kind"], "setup_resume")
        self.assertNotEqual(menu["session_id"], choice["session_id"])
        self.assertEqual(menu["projects"][0]["interest"], "境界の曖昧さ")
        self.assertNotIn("topic", menu["first_questions"])
        self.assertNotIn("interest", menu["first_questions"])
        with self.assertRaises(LoopError):
            self.hub.target(menu["session_id"], "next")

    def test_continue_preserves_state_and_budget(self):
        choice, engine = self.planned()
        engine.accept(engine.status()["proposal_hash"])
        before = digest(engine.status())
        menu = self.hub.open()
        result = self.hub.select(menu["session_id"], "continue", project_id=choice["project_id"])
        self.assertEqual(result["path"], choice["path"])
        self.assertEqual(digest(engine.status()), before)

    def test_view_only_blocks_mutations_through_real_entry(self):
        choice, engine = self.create()
        menu = self.hub.open()
        result = self.hub.select(menu["session_id"], "review", project_id=choice["project_id"])
        self.hub.target(result["session_id"], "status")
        with self.assertRaises(LoopError):
            self.hub.target(result["session_id"], "resume")
        self.assertEqual(main(self.root, ["work", result["session_id"], "run"]), 2)

    def test_stale_menu_rejected(self):
        choice, engine = self.create()
        menu = self.hub.open()
        engine.answer({"topic": "別セッションからの更新"})
        with self.assertRaises(LoopError):
            self.hub.select(menu["session_id"], "continue", project_id=choice["project_id"])

    def test_branch_settings_do_not_change_original_or_reuse_deep_answers(self):
        choice, engine = self.planned()
        before = digest(engine.status())
        menu = self.hub.open()
        branch = self.hub.select(menu["session_id"], "branch", project_id=choice["project_id"], name="設定比較",
                                 settings={"max_parallel_experiments": 2, "seeds": [101, 102]})
        new = Engine(self.root / branch["path"])
        state = new.status()
        self.assertEqual(state["phase"], "interview")
        self.assertFalse(state["authorized"])
        self.assertEqual(state["agent_calls"], 0)
        self.assertEqual(state["config"]["seeds"], [101, 102])
        self.assertEqual(state["prior_research"]["path"], choice["path"])
        self.assertEqual(digest(engine.status()), before)
        new.deepen()
        new.run()
        self.assertEqual(len(new.questions()), state["config"]["deep_questions"])

    def test_select_candidates_reaches_new_proposal_and_execution(self):
        choice, engine = self.planned()
        before = digest(engine.status())
        menu = self.hub.open()
        branch = self.hub.select(menu["session_id"], "reselect", project_id=choice["project_id"],
                                 name="選び直した実験", candidate_ids=["c3", "c5"])
        new = Engine(self.root / branch["path"])
        new.run()
        proposal = new.status()["proposal"]
        self.assertEqual([p["candidate_id"] for p in proposal["experiments"]], ["c3", "c5"])
        self.assertEqual(new.status()["phase"], "approval")
        self.assertEqual(new.status()["runs"], 0)
        new.accept(new.status()["proposal_hash"])
        new.run()
        self.assertEqual(new.status()["phase"], "complete")
        self.assertEqual(digest(engine.status()), before)

    def test_revise_saved_plan_version_without_overwriting(self):
        choice, engine = self.planned()
        first = engine.status()["proposal"]
        first_job = next(j["id"] for j in engine.status()["jobs"] if j["kind"] == "plan")
        engine.revise("第二版")
        job = engine.claim()
        revised = respond(job, engine.status())
        revised["direction"] = "第二版の方針"
        engine.submit(job["id"], job["token"], revised)
        menu = self.hub.open()
        self.assertEqual(len(menu["projects"][0]["plan_versions"]), 2)
        branch = self.hub.select(menu["session_id"], "revise", project_id=choice["project_id"], name="初版から分岐",
                                 plan_job=first_job, feedback="初版の比較を変える")
        new = Engine(self.root / branch["path"])
        job = new.status()["jobs"][0]
        self.assertEqual(job["payload"]["previous_proposal"], first)
        self.assertEqual(engine.status()["proposal"]["direction"], "第二版の方針")

    def test_complete_project_offers_branch_instead_of_continue(self):
        choice, engine = self.planned()
        engine.accept(engine.status()["proposal_hash"])
        engine.run()
        menu = self.hub.open()
        option = next(x for x in menu["projects"][0]["choices"] if x["id"] == "continue")
        self.assertFalse(option["available"])
        with self.assertRaises(LoopError):
            self.hub.select(menu["session_id"], "continue", project_id=choice["project_id"])

    def test_invalid_candidate_does_not_create_branch(self):
        choice, engine = self.planned()
        menu = self.hub.open()
        with self.assertRaises(LoopError):
            self.hub.select(menu["session_id"], "reselect", project_id=choice["project_id"], name="無効", candidate_ids=["c999"])
        self.assertEqual(len(self.hub.catalog()), 1)

    def test_hook_is_readonly_and_compaction_keeps_selection(self):
        output = hook(self.root, "claude", {"source": "startup"})
        self.assertIn("関心", output["systemMessage"])
        self.assertFalse((self.root / ".research").exists())
        compact = hook(self.root, "claude", {"source": "compact"})
        self.assertNotIn("systemMessage", compact)
        self.assertIn("維持", compact["hookSpecificOutput"]["additionalContext"])
        worker = hook(self.root, "gemini", {"source": "startup", "cwd": str(self.root / ".rlk/jobs/1")})
        self.assertEqual(worker, {})

    def test_actual_uninstalled_clone_entry_and_hook_protocol(self):
        clone = self.root / "clone folder"
        clone.mkdir()
        shutil.copy(ROOT / "agent.py", clone)
        shutil.copytree(ROOT / "src", clone / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        def call(*args, payload=None):
            proc = subprocess.run([sys.executable, str(clone / "agent.py"), *args],
                                  cwd=self.root, input=json.dumps(payload) if payload else None,
                                  capture_output=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)
        initial = call("hook", "--provider", "gemini", payload={"source": "startup"})
        self.assertEqual(initial["hookSpecificOutput"]["hookEventName"], "SessionStart")
        menu = call("open")
        choice = call("select", menu["session_id"], "--action", "new", "--name", "会話から研究")
        state = call("work", choice["session_id"], "status")
        self.assertEqual(state["config"]["name"], "会話から研究")
        self.assertEqual(state["phase"], "interview")
        again = call("open")
        self.assertEqual(again["kind"], "setup_resume")


if __name__ == "__main__":
    unittest.main()
