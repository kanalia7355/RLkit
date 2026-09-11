"""clone直後と新しいAgentセッションで、研究の選択をやり直す入口。"""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .config import LoopError, QUESTIONS, dump, make_config, nonempty
from .engine import Engine
from .setup import initialize
from .store import digest


ACTIONS = {
    "continue": "前回の方針・予算のまま続ける",
    "review": "方針・結果だけを見る（実験を動かさない）",
    "improve": "スキル設計の確認・承認・反映を進める（実験を動かさない）",
    "revise": "前回の方針を修正して、別の研究として提案し直す",
    "reselect": "保存済みの候補から選び直す",
    "branch": "関心・データを引き継ぎ、設定を変えて分岐する",
    "new": "別テーマの研究を始める",
}


def can_continue(state):
    if state["phase"] == "complete":
        return "完了済みです。追加の実験は分岐して始められます"
    if state["started"] and time.time() - state["started"] >= state["config"]["max_wall_seconds"]:
        return "前回の時間予算が終了しています。結果を見るか、分岐してください"
    return None


class Sessions:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.home = self.root / ".research"
        self.db_path = self.home / "sessions.sqlite3"

    @contextmanager
    def db(self, create=False):
        if not create and not self.db_path.exists():
            raise LoopError("新しいセッションの入口を先に開いてください")
        self.home.mkdir(exist_ok=True)
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created REAL, body TEXT)")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def catalog(self):
        entries = []
        for base in (self.home / "projects", self.root / "workspaces"):
            if not base.exists():
                continue
            if base.is_symlink() or not base.resolve().is_relative_to(self.root):
                raise LoopError("研究フォルダがclone先の外を参照しています")
            for directory in sorted(base.iterdir()):
                if not directory.is_dir():
                    continue
                if directory.is_symlink() or not directory.resolve().is_relative_to(self.root):
                    raise LoopError("研究の外部参照を自動で読み込みません")
                if not (directory / ".rlk/state.sqlite3").exists():
                    continue
                state = Engine(directory).status()
                # 旧版の動作実証を利用者の研究として提示しない。
                if base.name == "workspaces" and state["config"]["backend"] == "demo":
                    continue
                relative = directory.relative_to(self.root).as_posix()
                entries.append({"id": digest(relative)[:16], "path": relative, "state": state,
                                "fingerprint": digest(state)})
        return entries

    def menu(self):
        last_selection = None
        if self.db_path.exists():
            previous_db = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=30)
            try:
                for (body,) in previous_db.execute("SELECT body FROM sessions ORDER BY created DESC"):
                    previous = json.loads(body)
                    if previous["status"] == "selected":
                        last_selection = previous["selection"]
                        break
            finally:
                previous_db.close()
        projects = []
        for entry in self.catalog():
            state = entry["state"]
            remaining = state["config"]["max_wall_seconds"]
            if state["started"]:
                remaining = max(0, int(remaining - (time.time() - state["started"])))
            proposals = []
            for job in state["jobs"]:
                if job["kind"] == "plan" and job["status"] == "done":
                    proposals.append({"job": job["id"], "cycle": job["cycle"], "proposal": job["result"],
                                      "hash": digest(job["result"])})
            plan = state.get("proposal") or (proposals[-1]["proposal"] if proposals else None)
            disabled = can_continue(state)
            choices = [{"id": action, "label": label, "available": True} for action, label in ACTIONS.items()]
            for choice in choices:
                if choice["id"] == "continue" and disabled:
                    choice.update(available=False, reason=disabled)
                if choice["id"] == "revise" and not plan:
                    choice.update(available=False, reason="保存済みの方針がまだありません")
                if choice["id"] == "reselect" and not state.get("candidates"):
                    choice.update(available=False, reason="保存済み候補がまだありません")
            projects.append({"id": entry["id"], "name": state["config"]["name"], "path": entry["path"],
                             "fingerprint": entry["fingerprint"], "phase": state["phase"], "cycle": state["cycle"],
                             "topic": state["answers"].get("topic"), "interest": state["answers"].get("interest"),
                             "plan": plan, "plan_versions": proposals, "candidates": state.get("candidates", []),
                             "last_results": state["history"][-1:] , "settings": state["config"],
                             "paused": state["paused"],
                             "remaining": {"seconds": remaining,
                                           "agent_calls": max(0, state["config"]["max_agent_calls"]-state["agent_calls"]),
                                           "runs": max(0, state["config"]["max_runs"]-state["runs"])},
                             "unfinished": [{"id": j["id"], "kind": j["kind"], "status": j["status"], "error": j["error"]}
                                            for j in state["jobs"] if j["status"] in ("pending", "running", "failed")],
                             "choices": choices})
        menu = {"kind": "resume" if projects else "setup", "projects": projects, "last_selection": last_selection,
                "opening": "前回の方針と進捗を確認して、今回の進め方を選びましょう。" if projects else
                           "研究を始めましょう。どんなテーマに関心がありますか？ 特に気になっていることも教えてください。",
                "first_questions": dict(list(QUESTIONS.items())[:2]) if not projects else {},
                "instruction": "ユーザーへコマンド入力を求めず、会話で回答・選択を得る。選択までは実験を起動しない。"}
        if len(projects) == 1 and not projects[0]["plan"] and projects[0]["phase"] in ("interview", "questions"):
            questions = Engine(self.root / projects[0]["path"]).questions()
            menu.update(kind="setup_resume", first_questions=dict(list(questions.items())[:2]),
                        opening=f"「{projects[0]['name']}」のセットアップが途中です。" +
                                (next(iter(questions.values())) if questions else "回答済みの内容から深掘り・方針提案へ進めます。"))
        return menu

    def open(self):
        menu = self.menu()
        session = {"id": uuid.uuid4().hex, "status": "awaiting_choice", "selection": None,
                   "snapshots": {p["id"]: p["fingerprint"] for p in menu["projects"]}}
        with self.db(create=True) as db:
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (session["id"], time.time(), dump(session)))
        return dict(menu, session_id=session["id"])

    @staticmethod
    def _read(db, session_id):
        row = db.execute("SELECT body FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise LoopError("不明なセッションです。入口を開き直してください")
        return json.loads(row[0])

    def select(self, session_id, action, project_id=None, name=None, settings=None, feedback="", candidate_ids=None, plan_job=None):
        if action not in ACTIONS:
            raise LoopError("選択肢が不明です")
        settings = settings or {}
        if not isinstance(settings, dict):
            raise LoopError("設定変更はJSONオブジェクトが必要です")
        if action in ("continue", "review", "improve") and (settings or feedback or candidate_ids or plan_job is not None):
            raise LoopError("設定・候補・方針を変更する場合は分岐を選択してください")
        with self.db() as db:
            session = self._read(db, session_id)
            if session["status"] != "awaiting_choice":
                raise LoopError("このセッションでは選択済みです。別の進め方を選ぶには入口を開き直してください")
            source = None
            if action != "new":
                source = next((e for e in self.catalog() if e["id"] == project_id), None)
                if not source or session["snapshots"].get(project_id) != source["fingerprint"]:
                    raise LoopError("表示後に研究状態が変わりました。最新の入口を開いて選び直してください")
                if action == "continue" and can_continue(source["state"]):
                    raise LoopError(can_continue(source["state"]))
            if action in ("new", "branch", "revise", "reselect"):
                nonempty(name, "新しい研究の名前")
                cfg = dict(source["state"]["config"]) if source else {}
                cfg.update(settings)
                cfg["name"] = name
                selected = []
                old_plan = None
                if source:
                    old_plan = source["state"].get("proposal")
                    plan_jobs = [j for j in source["state"]["jobs"] if j["kind"] == "plan" and j["status"] == "done"]
                    if plan_job is not None:
                        match = next((j for j in plan_jobs if j["id"] == plan_job), None)
                        if not match:
                            raise LoopError("選択した方針版がありません")
                        old_plan = match["result"]
                    elif not old_plan and plan_jobs:
                        old_plan = plan_jobs[-1]["result"]
                if action == "reselect":
                    if not candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
                        raise LoopError("重複しない候補IDを指定してください")
                    by_id = {c["id"]: c for c in source["state"].get("candidates", [])}
                    if set(candidate_ids) - set(by_id):
                        raise LoopError("保存済み候補にないIDです")
                    selected = [by_id[cid] for cid in candidate_ids]
                    cfg["experiments_per_cycle"] = len(selected)
                elif action == "revise":
                    nonempty(feedback, "修正したい内容")
                    if not old_plan:
                        raise LoopError("修正する方針がありません")
                    # 方針を作った時点の候補を参照し、別サイクルの同名IDと混同しない。
                    source_job = next((j for j in reversed(source["state"]["jobs"])
                                       if j["kind"] == "plan" and j["result"] == old_plan), None)
                    selected = source_job["payload"]["candidates"] if source_job else []
                    if not selected or cfg["experiments_per_cycle"] > len(selected):
                        raise LoopError("元の候補数を超える変更はbranchで候補から生成してください")
                cfg = make_config(cfg)
                directory = self.home / "projects" / ("study-" + uuid.uuid4().hex[:12])
                initialize(directory, cfg)
                engine = Engine(directory)
                if source:
                    with engine.store.transaction() as research_db:
                        state = engine.store.state(research_db)
                        state["answers"] = {k: v for k, v in source["state"]["answers"].items()
                                            if action != "branch" or k in QUESTIONS}
                        state["prior_research"] = {"path": source["path"], "fingerprint": source["fingerprint"],
                                                   "action": action, "feedback": feedback, "proposal": old_plan,
                                                   "answers": source["state"]["answers"],
                                                   "deepening": source["state"].get("deepening"),
                                                   "history": source["state"]["history"]}
                        if action in ("revise", "reselect"):
                            state.update(phase="planning", cycle=1, candidates=selected,
                                         deepening=source["state"].get("deepening"))
                            engine.store.job(research_db, 1, "plan", {"candidates": selected, "previous_proposal": old_plan,
                                                                     "feedback": feedback, "user_selected_candidate_ids": candidate_ids})
                        engine.store.event(research_db, "branched", {"source": source["path"], "action": action})
                        engine.store.save(research_db, state)
                path = directory.relative_to(self.root).as_posix()
                target_id = digest(path)[:16]
            else:
                path, target_id = source["path"], source["id"]
            selection = {"action": action, "project_id": target_id, "path": path,
                         "mode": "read_only" if action == "review" else "skills" if action == "improve" else "work"}
            session.update(status="selected", selection=selection)
            db.execute("UPDATE sessions SET body=? WHERE id=?", (dump(session), session_id))
            return dict(selection, session_id=session_id, next_step="状態を確認し、保存済みの段階から会話を進める。新しい計画は改めて提示する。")

    def target(self, session_id, command):
        with self.db() as db:
            session = self._read(db, session_id)
            if session["status"] != "selected":
                raise LoopError("この新しいセッションの進め方がまだ選ばれていません")
            selected = session["selection"]
            if selected["mode"] == "read_only" and command not in ("status", "questions", "doctor"):
                raise LoopError("結果を見るモードです。実験・状態の変更は別の入口で選んでください")
            if selected["mode"] == "skills" and command not in ("status", "doctor", "export", "skill-next", "skill-submit",
                    "skill-run", "skill-accept", "skill-reject", "skill-revise", "skill-disable", "skill-fail", "skill-recover", "skill-retry", "skill-resume"):
                raise LoopError("スキル改善モードでは研究実験を操作できません")
            path = (self.root / selected["path"]).resolve()
            if not path.is_relative_to(self.root):
                raise LoopError("選択先がclone先の外です")
            return path
