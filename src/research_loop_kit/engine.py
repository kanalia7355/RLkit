"""対話、事前登録、実験、分析を永続ジョブで接続する。"""

import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import platform
import re
import sys
import time
import uuid

from . import evolution, shared_source
from .config import QUESTIONS, LoopError, dump, nonempty, number, read_json, strings, validate
from .fsutil import write_atomic, write_new
from .guards import inspect_code, summarize_effects, verify_evidence, verify_reports
from .prompts import render
from .providers import invoke, process_run
from .reporting import supporting_documents
from .store import Store, digest


def required(obj, keys):
    if not isinstance(obj, dict) or set(keys) - set(obj):
        raise LoopError(f"必要な項目: {', '.join(keys)}")
    for key in keys:
        nonempty(obj[key], key)


class Engine:
    def __init__(self, root):
        self.store = Store(root)
        self.root = self.store.root

    def status(self):
        with self.store.transaction() as db:
            state = self.store.state(db)
            state["history"] = self.store.history(db)
            state["jobs"] = self.store.jobs(db)
            state["failed_attempts"] = self._failed_attempts(db)
            return state

    @staticmethod
    def _failed_attempts(db):
        return [
            dict(row, body=json.loads(row["body"]))
            for row in db.execute("SELECT job,attempt,body FROM attempts WHERE status='failed' ORDER BY job,attempt")
        ]

    def questions(self):
        state = self.status()
        questions = (
            QUESTIONS
            if state["phase"] == "interview"
            else {x["id"]: x["question"] for x in state.get("deepening", {}).get("questions", [])}
        )
        return {k: v for k, v in questions.items() if k not in state["answers"]}

    def answer(self, answers):
        if not isinstance(answers, dict):
            raise LoopError("回答は質問IDと回答のJSONオブジェクトです")
        with self.store.transaction() as db:
            state = self.store.state(db)
            if state["phase"] not in ("interview", "questions"):
                raise LoopError("回答を受け付ける段階ではありません")
            allowed = (
                set(QUESTIONS) if state["phase"] == "interview" else {x["id"] for x in state["deepening"]["questions"]}
            )
            if set(answers) - allowed:
                raise LoopError(f"不明な質問ID: {set(answers) - allowed}")
            for key, value in answers.items():
                nonempty(value, key)
            state["answers"].update(answers)
            self.store.save(db, state)
            self.store.event(db, "answers", answers)

    def configure(self, changes):
        with self.store.transaction() as db:
            state = self.store.state(db)
            if state["phase"] != "interview":
                raise LoopError("設定は深掘り開始前に確定します。別設定の比較は新しい研究フォルダで開始してください")
            state["config"] = validate(dict(state["config"], **changes))
            self.store.save(db, state)
            self.store.event(db, "configure", changes)

    def deepen(self):
        with self.store.transaction() as db:
            state = self.store.state(db)
            if state["phase"] != "interview" or set(QUESTIONS) - set(state["answers"]):
                raise LoopError("基本質問への回答を揃えてください")
            self.store.job(db, 0, "deepen", {"count": state["config"]["deep_questions"]})
            state["phase"] = "deepening"
            self.store.save(db, state)

    def propose(self):
        with self.store.transaction() as db:
            state = self.store.state(db)
            if state["phase"] != "questions":
                raise LoopError("深掘りの回答後に提案を開始できます")
            if any(x["id"] not in state["answers"] for x in state["deepening"]["questions"]):
                raise LoopError("深掘り質問に回答してください")
            self._ideas(db, state)
            self.store.save(db, state)

    def _ideas(self, db, state):
        cfg = state["config"]
        state["cycle"] += 1
        state["phase"] = "ideas"
        state.pop("proposal", None)
        state.pop("proposal_hash", None)
        offset = 0
        lenses = ["新規性・機序", "反証・対照", "実施可能性・低コスト", "頑健性・適用限界"]
        for i in range(cfg["proposal_workers"]):
            count = cfg["candidate_count"] // cfg["proposal_workers"] + (
                i < cfg["candidate_count"] % cfg["proposal_workers"]
            )
            self.store.job(
                db, state["cycle"], "ideas", {"count": count, "offset": offset, "lens": lenses[i % len(lenses)]}
            )
            offset += count

    def accept(self, proposal_hash):
        with self.store.transaction() as db:
            state = self.store.state(db)
            if state["phase"] != "approval" or proposal_hash != state.get("proposal_hash"):
                raise LoopError("表示した最新の提案ハッシュが必要です")
            if state["proposal"]["open_questions"]:
                raise LoopError("未解決事項があります。rlk reviseで方針を修正してください")
            state["authorized"] = True
            state["started"] = state["started"] or time.time()
            self.store.event(db, "accepted", {"proposal_hash": proposal_hash, "config_hash": digest(state["config"])})
            self._implement(db, state)
            self.store.save(db, state)

    def revise(self, feedback):
        nonempty(feedback, "feedback")
        with self.store.transaction() as db:
            state = self.store.state(db)
            if state["phase"] != "approval":
                raise LoopError("方針提案への回答待ちでだけ修正できます")
            self.store.job(
                db,
                state["cycle"],
                "plan",
                {"candidates": state["candidates"], "previous_proposal": state["proposal"], "feedback": feedback},
            )
            state["phase"] = "planning"
            self.store.event(db, "revision_requested", {"feedback": feedback})
            self.store.save(db, state)

    def _implement(self, db, state):
        state["phase"] = "implementing"
        shared = shared_source.read_sources(self.root)
        # 全文はpayloadへ入れず、内容アドレスの版として一度だけ保存する（内容一致なら再利用）。
        version = shared_source.store_version(self.root, shared)
        for experiment in state["proposal"]["experiments"]:
            self.store.job(
                db,
                state["cycle"],
                "implement",
                {
                    "experiment": experiment,
                    "proposal_hash": state["proposal_hash"],
                    "shared_source_hash": version,
                    "shared_source_files": shared_source.file_hashes(shared),
                },
            )

    def pause(self):
        with self.store.transaction() as db:
            state = self.store.state(db)
            state["paused"] = True
            state["skills_paused"] = True
            self.store.save(db, state)
            self.store.event(db, "pause", {"note": "新規起動を停止。既存プロセスはタイムアウト内で終了"})

    def resume(self):
        with self.store.transaction() as db:
            state = self.store.state(db)
            state["paused"] = False
            state["skills_paused"] = False
            self.store.save(db, state)

    def resume_skills(self):
        with self.store.transaction() as db:
            state = self.store.state(db)
            state["skills_paused"] = False
            self.store.save(db, state)

    def skill_decision(self, candidate_id, decision, design_hash=None, feedback=""):
        with self.store.transaction() as db:
            state = self.store.state(db)
            candidate = next((c for c in state.get("skill_candidates", []) if c["id"] == candidate_id), None)
            valid_statuses = ("approval",) if decision == "accept" else ("approval", "building", "active", "disabled")
            if not candidate or candidate["status"] not in valid_statuses:
                raise LoopError("承認待ちのスキル設計を指定してください")
            if any(
                j["kind"] == "skill_build"
                and j["payload"]["candidate_id"] == candidate_id
                and j["status"] in ("pending", "running")
                for j in self.store.jobs(db)
            ):
                raise LoopError("実装作業が未完了です。停止・失敗を確認してから設計を変更してください")
            if design_hash != candidate["design_hash"]:
                raise LoopError("提示済みの最新スキル設計ハッシュが必要です")
            if decision == "accept":
                self.store.job(
                    db,
                    0,
                    "skill_build",
                    {"candidate_id": candidate_id, "design": candidate["design"], "design_hash": design_hash},
                )
                candidate["status"] = "building"
            elif decision == "reject":
                candidate.update(status="rejected", feedback=feedback)
            elif decision == "revise":
                nonempty(feedback, "feedback")
                candidate.update(status="designing", feedback=feedback)
                self.store.job(db, 0, "skill_design", {"candidate": candidate, "feedback": feedback})
            else:
                raise LoopError("不明なスキル判断です")
            self.store.event(db, "skill_" + decision, {"candidate": candidate_id, "hash": design_hash})
            self.store.save(db, state)
        self.export()

    def disable_skill(self, name):
        with self.store.transaction() as db:
            state = self.store.state(db)
            if name not in state.get("active_skills", {}):
                raise LoopError("有効なスキル名を指定してください")
            previous = state["active_skills"].pop(name)
            for candidate in state.get("skill_candidates", []):
                if candidate.get("activation") == previous and candidate["status"] == "active":
                    candidate["status"] = "disabled"
            self.store.event(db, "skill_disabled", previous)
            self.store.save(db, state)
        self.export()

    def claim(self, allowed=None):
        """条件を満たす待ちジョブを1件だけ実行中にする。予算で止まった場合は理由を返す例外にする。"""
        with self.store.transaction() as db:
            state = self.store.state(db)
            jobs = self.store.jobs(db, statuses=("pending", "running"))
            running_agents = sum(j["status"] == "running" and j["kind"] != "execute" for j in jobs)
            running_runs = sum(j["status"] == "running" and j["kind"] == "execute" for j in jobs)
            blocked = None
            for job in jobs:
                if job["status"] != "pending" or (allowed and job["kind"] not in allowed):
                    continue
                reason = self._claim_blocker(state, job, running_agents, running_runs)
                if reason == "wait":
                    continue
                if reason:
                    blocked = blocked or reason
                    continue
                return self._start(db, state, job)
        if blocked:
            raise LoopError(blocked)
        return None

    @staticmethod
    def _budget_exhausted(state):
        cfg = state["config"]
        if state["started"] and time.time() - state["started"] >= cfg["max_wall_seconds"]:
            return "研究セッションの実時間上限です。新しい研究フォルダで継続してください"
        if state["agent_calls"] >= cfg["max_agent_calls"]:
            return "AI作業回数の上限です"
        return None

    def _claim_blocker(self, state, job, running_agents, running_runs):
        """None=取得可、"wait"=並列上限で後回し、それ以外=予算などで取得不可の理由。"""
        cfg = state["config"]
        kind = job["kind"]
        is_skill = kind in evolution.KINDS
        if state.get("skills_paused", state["paused"]) if is_skill else state["paused"]:
            return "wait"
        if kind == "execute":
            if running_runs >= cfg["max_parallel_experiments"]:
                return "wait"
        elif running_agents >= cfg["max_parallel_agents"]:
            return "wait"
        if job["attempt"] >= cfg["max_attempts"]:
            return "試行回数上限です"
        if is_skill:
            if state.get("skill_calls", 0) >= cfg["max_skill_calls"]:
                return "スキル作業回数の上限です"
        elif kind == "review":
            # 実測済みの結果を報告できないまま止めないため、レビューは実時間・作業回数の上限を免除する。
            pass
        else:
            reason = self._budget_exhausted(state)
            if reason and (kind != "execute" or reason.startswith("研究セッション")):
                return reason
        return None

    def _start(self, db, state, job):
        token = uuid.uuid4().hex
        job.update(status="running", attempt=job["attempt"] + 1, token=token, started=time.time())
        if job["kind"] != "execute":
            counter = "skill_calls" if job["kind"] in evolution.KINDS else "agent_calls"
            state[counter] = state.get(counter, 0) + 1
        db.execute(
            "UPDATE jobs SET status='running',attempt=?,token=?,started=?,error=NULL WHERE id=?",
            (job["attempt"], token, job["started"], job["id"]),
        )
        db.execute("INSERT INTO attempts VALUES (?,?,?,'running',NULL)", (job["id"], job["attempt"], token))
        self.store.save(db, state)
        self.store.event(db, "claimed", {"id": job["id"], "token": token})
        return job

    def ticket_dir(self, job):
        return self.root / ".rlk" / "jobs" / str(job["id"]) / f"attempt-{job['attempt']}"

    def ticket(self, job):
        directory = self.ticket_dir(job)
        directory.mkdir(parents=True, exist_ok=True)
        if job["kind"] != "execute":
            prompt = directory / "prompt.md"
            if not prompt.exists():
                write_new(prompt, render(job, self.status(), directory / "response.json", root=self.root))
        return {
            "id": job["id"],
            "token": job["token"],
            "kind": job["kind"],
            "directory": str(directory),
            "prompt": str(directory / "prompt.md"),
            "response": str(directory / "response.json"),
        }

    def validate_result(self, job, result, state):
        if not isinstance(result, dict):
            raise LoopError("応答はJSONオブジェクトが必要です")
        validator = {
            "skill_design": self._check_skill_design,
            "skill_build": self._check_skill_build,
            "deepen": self._check_deepen,
            "ideas": self._check_ideas,
            "plan": self._check_plan,
            "implement": self._check_implement,
            "review": self._check_review,
        }.get(job["kind"])
        if validator is None:
            raise LoopError("execute結果は実測経路からのみ登録できます")
        validator(job, result, state)

    @staticmethod
    def _check_skill_design(job, result, state):
        evolution.validate_design(result)
        if job["payload"]["candidate"]["evidence"] not in {r["source"] for r in result["references"]}:
            raise LoopError("検出候補の根拠をreferencesへ含めてください")

    @staticmethod
    def _check_skill_build(job, result, state):
        candidate = next(
            (c for c in state.get("skill_candidates", []) if c["id"] == job["payload"]["candidate_id"]), None
        )
        if (
            not candidate
            or candidate["status"] != "building"
            or candidate["design_hash"] != job["payload"]["design_hash"]
        ):
            raise LoopError("この実装に対する設計承認が失効しています")
        evolution.validate_build(result, job["payload"]["design"])

    @staticmethod
    def _check_deepen(job, result, state):
        required(result, ["understanding"])
        questions = result.get("questions")
        if not isinstance(questions, list) or len(questions) != state["config"]["deep_questions"]:
            raise LoopError("深掘り質問数が設定と一致しません")
        for question in questions:
            required(question, ["id", "question"])
            if not re.fullmatch(r"q[1-9][0-9]*", question["id"]):
                raise LoopError("質問IDはq1、q2の形式です")
        if len({q["id"] for q in questions}) != len(questions):
            raise LoopError("質問IDが重複しています")

    @staticmethod
    def _check_ideas(job, result, state):
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != job["payload"]["count"]:
            raise LoopError("候補数が指定数と一致しません")
        for candidate in candidates:
            required(candidate, ["title", "hypothesis", "rationale", "method", "risk"])

    @staticmethod
    def _check_plan(job, result, state):
        required(result, ["direction"])
        strings(result.get("open_questions"), "open_questions")
        plans = result.get("experiments")
        if not isinstance(plans, list) or len(plans) != state["config"]["experiments_per_cycle"]:
            raise LoopError("採用実験数が設定と一致しません")
        known = {c["id"] for c in state["candidates"]}
        seen = set()
        for i, plan in enumerate(plans):
            required(
                plan,
                [
                    "candidate_id",
                    "title",
                    "hypothesis",
                    "method",
                    "baseline",
                    "treatment",
                    "metric",
                    "direction",
                    "success_rule",
                    "stop_rule",
                    "limitations",
                ],
            )
            if plan["candidate_id"] not in known or plan["candidate_id"] in seen:
                raise LoopError("未提案または重複した候補です")
            seen.add(plan["candidate_id"])
            if plan["direction"] not in ("minimize", "maximize") or number(plan.get("min_effect"), "min_effect") < 0:
                raise LoopError("主指標の方向または効果量が不正です")
            plan["id"] = f"e{i + 1}"

    def _check_implement(self, job, result, state):
        required(result, ["notes"])
        files = result.get("files")
        if not isinstance(files, dict) or "experiment.py" not in files or len(files) > 30:
            raise LoopError("experiment.pyを含むfilesが必要です")
        for name, content in files.items():
            if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*\.py", name):
                raise LoopError("実装は同一フォルダ内の.pyファイルだけを受け付けます")
            nonempty(content, name)
            try:
                ast.parse(content, filename=name)
            except SyntaxError as exc:
                raise LoopError(f"実装の構文エラー: {exc}") from exc
        result["code_audit"] = inspect_code(files)
        shared_source.prepare(self.root, job, result)

    @staticmethod
    def _check_review(job, result, state):
        reviews = result.get("experiments")
        measured = {x["id"]: x for x in job["payload"]["results"]}
        if not isinstance(reviews, list) or len(reviews) != len(measured):
            raise LoopError("全実験のレビューが必要です")
        seen = set()
        for review in reviews:
            required(review, ["id", "assessment", "interpretation", "limitations"])
            eid = review["id"]
            if eid in seen or eid not in measured:
                raise LoopError("レビューの実験IDが不正です")
            seen.add(eid)
            if review["assessment"] not in ("supported", "inconclusive", "invalid"):
                raise LoopError("不明なレビュー判定です")
            if review["assessment"] == "supported" and not measured[eid].get("threshold_met"):
                raise LoopError("失敗または閾値未達の実験を支持と判定できません")
        strings(result.get("next_questions"), "next_questions")
        strings(result.get("reusable_lessons"), "reusable_lessons")

    def submit(self, job_id, token, result):
        with ExitStack() as rollback, self.store.transaction(rollback=rollback) as db:
            state = self.store.state(db)
            job = next((j for j in self.store.jobs(db) if j["id"] == job_id), None)
            if not job or job["status"] != "running" or job["token"] != token:
                raise LoopError("作業ID・token・実行状態が一致しません（再送も拒否します）")
            self.validate_result(job, result, state)
            if job["kind"] != "skill_build":
                self._finish(db, state, job, result)
                # ファイル反映はDB更新がすべて成功した後、commitの直前に行う。
                if job["kind"] == "implement":
                    shared_source.publish(self.root, job, result, rollback)
                self._flush_pending_documents()
                return
        # 承認済みスキルのテストはDBロックの外で実行する。
        try:
            remaining = state["config"]["agent_timeout_seconds"] - (time.time() - job["started"])
            if remaining <= 0 or state.get("skills_paused", state["paused"]):
                raise LoopError("停止中または時間上限のためスキルを検証できません")
            result["activation"] = evolution.build(self.root, job, result, remaining)
        except Exception as exc:
            self.fail(job_id, token, f"スキル検証失敗: {exc}")
            self.export()
            raise
        with self.store.transaction() as db:
            state = self.store.state(db)
            live = db.execute("SELECT status,token FROM jobs WHERE id=?", (job_id,)).fetchone()
            if live["status"] != "running" or live["token"] != token or state.get("skills_paused", state["paused"]):
                raise LoopError("実行権失効または停止のためスキルを反映しません")
            self._finish(db, state, job, result)

    def _finish(self, db, state, job, result):
        db.execute("UPDATE jobs SET status='done',result=? WHERE id=?", (dump(result), job["id"]))
        db.execute(
            "UPDATE attempts SET status='done',body=? WHERE job=? AND attempt=? AND status='running'",
            (dump(result), job["id"], job["attempt"]),
        )
        self.store.event(db, "completed", {"id": job["id"], "attempt": job["attempt"], "result_hash": digest(result)})
        self._advance(db, state, job, result)
        self.store.save(db, state)

    def fail(self, job_id, token, reason):
        with self.store.transaction() as db:
            job = next((j for j in self.store.jobs(db) if j["id"] == job_id), None)
            if not job or job["status"] != "running" or job["token"] != token:
                raise LoopError("実行中の正しいtokenが必要です")
            db.execute("UPDATE jobs SET status='failed',error=? WHERE id=?", (reason, job_id))
            db.execute(
                "UPDATE attempts SET status='failed',body=? WHERE job=? AND attempt=?",
                (dump({"error": reason}), job_id, job["attempt"]),
            )
            self.store.event(db, "failed", {"id": job_id, "error": reason})

    def retry(self, job_id):
        with self.store.transaction() as db:
            state = self.store.state(db)
            job = next((j for j in self.store.jobs(db) if j["id"] == job_id), None)
            if not job or job["status"] != "failed" or job["attempt"] >= state["config"]["max_attempts"]:
                raise LoopError("再試行できる失敗ジョブではありません")
            if job["kind"] == "skill_build":
                candidate = next(c for c in state["skill_candidates"] if c["id"] == job["payload"]["candidate_id"])
                if candidate["status"] != "building" or candidate["design_hash"] != job["payload"]["design_hash"]:
                    raise LoopError("失効したスキル設計の実装は再試行できません")
            db.execute("UPDATE jobs SET status='pending',token=NULL WHERE id=?", (job_id,))
            self.store.event(db, "retry", {"id": job_id})

    def skip_failed(self, job_id):
        with self.store.transaction() as db:
            state = self.store.state(db)
            job = next((j for j in self.store.jobs(db) if j["id"] == job_id), None)
            if not job or job["status"] != "failed" or job["kind"] not in ("implement", "execute"):
                raise LoopError("実装・実行の失敗だけを未支持として分析へ送れます")
            result = {
                "id": job["payload"]["experiment"]["id"],
                "status": "failed",
                "threshold_met": False,
                "error": job["error"],
            }
            self.store.event(db, "failed_experiment_included", {"id": job_id, "error": job["error"]})
            self._finish(db, state, job, result)

    def _advance(self, db, state, job, result):
        kind = job["kind"]
        jobs = self.store.jobs(db, job["cycle"])
        if kind in evolution.KINDS:
            cid = job["payload"]["candidate"]["id"] if kind == "skill_design" else job["payload"]["candidate_id"]
            candidate = next(c for c in state["skill_candidates"] if c["id"] == cid)
            if kind == "skill_design":
                candidate.update(status="approval", design=result, design_hash=digest(result))
            else:
                candidate.update(status="active", activation=result["activation"])
                state.setdefault("active_skills", {})[result["activation"]["name"]] = result["activation"]
                self.store.event(db, "skill_activated", result["activation"])
        elif kind == "deepen":
            state.update(phase="questions", deepening=result)
        elif kind == "ideas" and all(j["status"] == "done" for j in jobs if j["kind"] == "ideas"):
            candidates = []
            for j in jobs:
                if j["kind"] == "ideas":
                    candidates += j["result"]["candidates"]
            state["candidates"] = [dict(c, id=f"c{i + 1}") for i, c in enumerate(candidates)]
            self.store.job(db, state["cycle"], "plan", {"candidates": state["candidates"]})
            state["phase"] = "planning"
        elif kind == "plan":
            state.update(phase="approval", proposal=result, proposal_hash=digest(result))
            if state["authorized"] and state["config"]["autonomy"] == "bounded" and not result["open_questions"]:
                self.store.event(db, "bounded_plan_accepted", {"hash": state["proposal_hash"]})
                self._implement(db, state)
        elif kind == "implement":
            if result.get("status") != "failed":
                self.store.job(
                    db,
                    state["cycle"],
                    "execute",
                    {
                        "experiment": job["payload"]["experiment"],
                        "implementation": result,
                        "implementation_job": job["id"],
                        "proposal_hash": job["payload"]["proposal_hash"],
                    },
                )
            self._maybe_review(db, state)
        elif kind == "execute":
            self._maybe_review(db, state)
        elif kind == "review":
            self._complete_cycle(db, state, result, job["payload"]["results"])

    def _complete_cycle(self, db, state, review, results):
        """レビュー受理と次サイクル作成の間で、実測照合と成果物の本文確定を必須にする。

        照合に失敗した場合はDBトランザクションごと巻き戻り、同じレビューを修正・再送できる。
        報告書の本文とハッシュはここで確定し、ファイルへの書き込みはcommit直前に行う。
        """
        entry = {
            "cycle": state["cycle"],
            "proposal_hash": state["proposal_hash"],
            "proposal": state["proposal"],
            "direction": state["proposal"]["direction"],
            "results": results,
            "review": review,
        }
        checks = verify_evidence(self.root, entry)
        view = dict(
            state,
            history=self.store.history(db) + [entry],
            jobs=self.store.jobs(db),
            failed_attempts=self._failed_attempts(db),
        )
        documents = self.render_documents(view)
        gate = {"cycle": state["cycle"], "evidence": checks, "documents": document_hashes(documents)}
        entry["completion_gate"] = gate
        self.store.add_history(db, entry)
        self.store.event(db, "completion_gate_passed", gate)
        self.store.event(db, "cycle_completed", {"cycle": state["cycle"]})
        evolution.detect(state, self.store, db, entry)
        stop = self._budget_exhausted(state)
        if state["cycle"] >= state["config"]["max_cycles"]:
            state["phase"] = "complete"
        elif stop:
            # 予算切れのまま次の候補作成を積まず、完了として分岐を案内する。
            state.update(phase="complete", stop_reason=stop)
            self.store.event(db, "stopped_by_budget", {"cycle": state["cycle"], "reason": stop})
        else:
            self._ideas(db, state)
        self._pending_documents = documents

    def _flush_pending_documents(self):
        documents, self._pending_documents = getattr(self, "_pending_documents", None), None
        if documents:
            self.write_documents(documents)

    def _maybe_review(self, db, state):
        jobs = self.store.jobs(db, state["cycle"])
        work = [j for j in jobs if j["kind"] in ("implement", "execute")]
        if all(j["status"] == "done" for j in work if j["kind"] == "implement"):
            state["phase"] = "executing"
        if any(j["status"] != "done" for j in work):
            return
        if any(j["kind"] == "review" for j in jobs):
            return
        results = []
        for j in work:
            if j["kind"] == "execute" or j["result"].get("status") == "failed":
                results.append(j["result"])
        self.store.job(
            db,
            state["cycle"],
            "review",
            {
                "results": results,
                "proposal": state["proposal"],
                "implementations": [j["result"] for j in work if j["kind"] == "implement"],
            },
        )
        state["phase"] = "reviewing"

    def execute(self, job):
        state = self.status()
        cfg = state["config"]
        directory = self.ticket_dir(job)
        directory.mkdir(parents=True, exist_ok=True)
        experiment = job["payload"]["experiment"]
        implementation = job["payload"]["implementation"]
        code_dir = directory / "code"
        sources = shared_source.code_files(self.root, implementation)
        for name, code in sources.items():
            write_new(code_dir / name, code)
        manifest = {
            "experiment": experiment,
            "proposal_hash": job["payload"]["proposal_hash"],
            "code_hash": digest(sources),
            "seeds": cfg["seeds"],
            "python": sys.version,
            "platform": platform.platform(),
            "started": time.time(),
            "job_id": job["id"],
            "attempt": job["attempt"],
        }
        manifest["code_audit"] = inspect_code(sources)
        if "shared_source_hash" in implementation:
            manifest["shared_source_hash"] = implementation["shared_source_hash"]
            manifest["experiment_path"] = implementation["experiment_path"]
        write_new(directory / "preregistration.json", dump(manifest))
        values = []
        for seed in cfg["seeds"]:
            with self.store.transaction() as db:
                current = self.store.state(db)
                live = db.execute("SELECT status,token FROM jobs WHERE id=?", (job["id"],)).fetchone()
                if live["status"] != "running" or live["token"] != job["token"]:
                    raise LoopError("実行権が失効しました")
                if current["paused"]:
                    raise LoopError("一時停止により次のseedを起動しません")
                remaining = cfg["max_wall_seconds"] - (time.time() - current["started"])
                if remaining <= 0 or current["runs"] >= cfg["max_runs"]:
                    raise LoopError("実験予算を使い切りました")
                current["runs"] += 1
                self.store.save(db, current)
                self.store.event(db, "run_reserved", {"id": job["id"], "seed": seed, "attempt": job["attempt"]})
            run_dir = directory / f"seed-{seed}"
            run_dir.mkdir()
            output = run_dir / "metrics.json"
            start = time.monotonic()
            process_run(
                [sys.executable, str(code_dir / "experiment.py"), "--seed", str(seed), "--output", str(output)],
                run_dir,
                run_dir / "stdout.log",
                run_dir / "stderr.log",
                min(cfg["run_timeout_seconds"], remaining),
                env_overrides={"PYTHONPATH": str(code_dir / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
            )
            metrics = read_json(output)
            if not isinstance(metrics, dict) or set(metrics) != {"seed", "baseline", "treatment"}:
                raise LoopError("測定値の形式はseed/baseline/treatmentだけのオブジェクトです")
            if type(metrics["seed"]) is not int or metrics["seed"] != seed:
                raise LoopError("測定値のseedが実行seedと一致しません")
            number(metrics["baseline"], "baseline")
            number(metrics["treatment"], "treatment")
            metrics["wall_seconds"] = time.monotonic() - start
            values.append(metrics)
            elapsed = time.time() - manifest["started"]
            progress = {
                "completed_seeds": [v["seed"] for v in values],
                "remaining_seeds": cfg["seeds"][len(values) :],
                "elapsed_seconds": elapsed,
                "eta_seconds_estimate": elapsed / len(values) * (len(cfg["seeds"]) - len(values)),
            }
            write_atomic(directory / "progress.json", dump(progress) + "\n")
            with self.store.transaction() as db:
                self.store.event(db, "seed_completed", {"id": job["id"], "attempt": job["attempt"], **progress})
        after_code = shared_source.read_code(code_dir)
        if digest(after_code) != manifest["code_hash"]:
            raise LoopError("実行中に事前登録したコードが変更されました")
        result = {
            "id": experiment["id"],
            "status": "measured",
            "n": len(values),
            **summarize_effects(values, experiment),
            "statistical_test": "未実施（記述統計。effect_ci95はpaired bootstrapの参考区間）",
            "values": values,
            "evidence": directory.relative_to(self.root).as_posix(),
            "manifest": manifest,
        }
        write_new(directory / "analysis.json", dump(result))
        with self.store.transaction() as db:
            state = self.store.state(db)
            live = db.execute("SELECT status,token FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if live["status"] != "running" or live["token"] != job["token"]:
                raise LoopError("実行権が失効しました。実測ファイルは保存済みです")
            self._finish(db, state, job, result)

    def work(self, job):
        try:
            self.ticket(job)
            if job["kind"] == "execute":
                self.execute(job)
            else:
                state = self.status()
                timeout = state["config"]["agent_timeout_seconds"]
                if state["started"] and job["kind"] not in (*evolution.KINDS, "review"):
                    timeout = min(timeout, state["config"]["max_wall_seconds"] - (time.time() - state["started"]))
                if timeout <= 0:
                    raise LoopError("セッション時間の上限です")
                result = invoke(job, state, self.ticket_dir(job), timeout)
                self.submit(job["id"], job["token"], result)
        except Exception as exc:
            try:
                self.fail(job["id"], job["token"], f"{type(exc).__name__}: {exc}")
            except LoopError:
                pass
            return {"id": job["id"], "error": str(exc)}
        return {"id": job["id"], "status": "done"}

    def run(self, experiments_only=False, skills_only=False):
        cfg = self.status()["config"]
        completed = []
        allowed = set() if skills_only else {"execute"}
        if not experiments_only:
            kinds = (
                evolution.KINDS if skills_only else ("deepen", "ideas", "plan", "implement", "review", *evolution.KINDS)
            )
            allowed.update(kind for kind in kinds if dict(cfg, **cfg["roles"].get(kind, {}))["backend"] != "active")
        if not allowed:
            return []
        try:
            with ThreadPoolExecutor(max_workers=cfg["max_parallel_agents"] + cfg["max_parallel_experiments"]) as pool:
                while True:
                    batch = []
                    blocked = None
                    while True:
                        try:
                            job = self.claim(allowed)
                        except LoopError as exc:
                            blocked = exc
                            break
                        if not job:
                            break
                        batch.append(pool.submit(self.work, job))
                    if not batch:
                        if blocked:
                            raise blocked
                        break
                    # 取得中に予算へ到達しても、実行中の仕事を待ってから再度取得する。
                    # implementが完了すれば、AI予算を消費しないexecuteを取得できる。
                    completed += [f.result() for f in batch]
        finally:
            self.export()
        return completed

    def export(self):
        """DBが正本。表示用文書はいつでも再生成できる。"""
        state = self.status()
        reports = self.write_documents(self.render_documents(state))
        write_atomic(reports / "knowledge.json", dump(state["history"]) + "\n")
        write_atomic(reports / "status.json", dump(state) + "\n")
        return str(reports)

    def write_documents(self, documents):
        reports = self.root / "reports"
        for name, content in documents.items():
            write_atomic(reports / name, content)
        verify_reports(reports, documents)
        return reports

    def render_documents(self, state):
        documents = supporting_documents(state)
        documents.update(evolution.documents(state))
        if "proposal" in state:
            documents["PROPOSAL.md"] = proposal_document(state)
        for entry in state["history"]:
            documents[f"cycle-{entry['cycle']:03d}.md"] = cycle_document(state, entry)
            documents[f"cycle-{entry['cycle']:03d}-CHECKS.md"] = checks_document(entry)
        return documents


def document_hashes(documents):
    return {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in documents.items()}


def proposal_document(state):
    proposal, cfg = state["proposal"], state["config"]
    lines = [
        f"# 研究方針: {cfg['name']}",
        "",
        proposal["direction"],
        "",
        f"提案ハッシュ: `{state['proposal_hash']}`",
        "",
        f"運転設定: {cfg['autonomy']} / 最大{cfg['max_cycles']}サイクル",
        "",
    ]
    for p in proposal["experiments"]:
        lines += [
            f"## {p['id']}: {p['title']}",
            "",
            f"仮説: {p['hypothesis']}",
            "",
            f"方法: {p['method']}",
            "",
            f"比較: {p['baseline']} / {p['treatment']}",
            "",
            f"指標: {p['metric']} / {p['direction']} / 改善幅 {p['min_effect']}",
            "",
            f"判定根拠: {p['success_rule']}",
            "",
            f"停止条件: {p['stop_rule']}",
            "",
            f"限界: {p['limitations']}",
            "",
        ]
    lines += ["## 未解決事項", "", *(proposal["open_questions"] or ["申告なし"])]
    return "\n".join(lines) + "\n"


def _ci_text(result):
    ci = result.get("effect_ci95")
    return f"[{ci[0]:.6g}, {ci[1]:.6g}]" if ci else "—"


def cycle_document(state, entry):
    lines = [
        f"# サイクル {entry['cycle']} — {state['config']['name']}",
        "",
        entry["direction"],
        "",
        "測定の差は記述統計です。95%区間は同一seedの差分に対するpaired bootstrapの参考値で、"
        "seed数が少ないと過小になります。統計的有意差や一般化を自動的に意味しません。",
        "",
        "| 実験 | 状態 | 対照平均 | 介入平均 | 改善幅平均 | 改善幅95%区間 | seed数 | 閾値到達 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in entry["results"]:
        lines.append(
            f"| {r['id']} | {r['status']} | {r.get('baseline_mean', '—')} | {r.get('treatment_mean', '—')}"
            f" | {r.get('effect_mean', '—')} | {_ci_text(r)} | {r.get('n', 0)} | {r['threshold_met']} |"
        )
    for review in entry["review"]["experiments"]:
        r = next(x for x in entry["results"] if x["id"] == review["id"])
        lines += [
            "",
            f"## {review['id']}: {review['assessment']}",
            "",
            review["interpretation"],
            "",
            f"限界: {review['limitations']}",
            "",
            f"証跡: `{r.get('evidence', '実行前失敗')}`",
            "",
            f"エラー: {r.get('error', 'なし')}",
        ]
    lines += [
        "",
        "## 次の問い",
        "",
        *[f"- {q}" for q in entry["review"]["next_questions"]],
        "",
        "## 再利用する知見",
        "",
        *[f"- {q}" for q in entry["review"]["reusable_lessons"]],
    ]
    return "\n".join(lines) + "\n"


def checks_document(entry):
    lines = [
        f"# サイクル {entry['cycle']} 検証記録",
        "",
        "完了確定前に、事前登録・コード・seed別数値・再集計・ログ存在・本文保存を照合する。",
        "これは研究上の妥当性・検出力・動的配線を保証するものではない。",
        "",
    ]
    for r in entry["results"]:
        audit = r.get("manifest", {}).get("code_audit", {})
        lines += [
            f"## {r['id']}: {r['status']}",
            "",
            f"静的検査: {audit.get('status', '未実施')}",
            "",
            *audit.get("findings", []),
            "",
        ]
    return "\n".join(lines) + "\n"
