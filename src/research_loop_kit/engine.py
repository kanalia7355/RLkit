"""対話、事前登録、実験、分析を永続ジョブで接続する。"""

import ast
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import platform
import re
import statistics
import sys
import time
import uuid

from .config import LoopError, QUESTIONS, dump, nonempty, number, read_json, strings, validate
from .prompts import render
from .providers import invoke, process_run
from .store import Store, digest, write_new
from .guards import inspect_code, verify_evidence, verify_reports
from .reporting import supporting_documents
from . import evolution
from . import shared_source


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
            state["jobs"] = self.store.jobs(db)
            state["failed_attempts"] = self._failed_attempts(db)
            return state

    @staticmethod
    def _failed_attempts(db):
        return [dict(row, body=json.loads(row["body"])) for row in db.execute(
            "SELECT job,attempt,body FROM attempts WHERE status='failed' ORDER BY job,attempt")]

    def questions(self):
        state = self.status()
        questions = QUESTIONS if state["phase"] == "interview" else {
            x["id"]: x["question"] for x in state.get("deepening", {}).get("questions", [])}
        return {k: v for k, v in questions.items() if k not in state["answers"]}

    def answer(self, answers):
        if not isinstance(answers, dict):
            raise LoopError("回答は質問IDと回答のJSONオブジェクトです")
        with self.store.transaction() as db:
            state = self.store.state(db)
            if state["phase"] not in ("interview", "questions"):
                raise LoopError("回答を受け付ける段階ではありません")
            allowed = set(QUESTIONS) if state["phase"] == "interview" else {
                x["id"] for x in state["deepening"]["questions"]}
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
            count = cfg["candidate_count"] // cfg["proposal_workers"] + (i < cfg["candidate_count"] % cfg["proposal_workers"])
            self.store.job(db, state["cycle"], "ideas", {"count": count, "offset": offset,
                                                       "lens": lenses[i % len(lenses)]})
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
            self.store.job(db, state["cycle"], "plan", {"candidates": state["candidates"],
                                                       "previous_proposal": state["proposal"], "feedback": feedback})
            state["phase"] = "planning"
            self.store.event(db, "revision_requested", {"feedback": feedback})
            self.store.save(db, state)

    def _implement(self, db, state):
        state["phase"] = "implementing"
        shared = shared_source.read_sources(self.root)
        for experiment in state["proposal"]["experiments"]:
            self.store.job(db, state["cycle"], "implement", {"experiment": experiment,
                                                            "proposal_hash": state["proposal_hash"], "shared_sources": shared})

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
            if any(j["kind"] == "skill_build" and j["payload"]["candidate_id"] == candidate_id
                   and j["status"] in ("pending", "running") for j in self.store.jobs(db)):
                raise LoopError("実装作業が未完了です。停止・失敗を確認してから設計を変更してください")
            if design_hash != candidate["design_hash"]:
                raise LoopError("提示済みの最新スキル設計ハッシュが必要です")
            if decision == "accept":
                self.store.job(db, 0, "skill_build", {"candidate_id": candidate_id,
                    "design": candidate["design"], "design_hash": design_hash})
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
        with self.store.transaction() as db:
            state = self.store.state(db)
            cfg = state["config"]
            jobs = self.store.jobs(db)
            running_agents = sum(j["status"] == "running" and j["kind"] != "execute" for j in jobs)
            running_runs = sum(j["status"] == "running" and j["kind"] == "execute" for j in jobs)
            for job in jobs:
                if job["status"] != "pending" or (allowed and job["kind"] not in allowed):
                    continue
                is_skill = job["kind"] in evolution.KINDS
                if (state.get("skills_paused", state["paused"]) if is_skill else state["paused"]):
                    continue
                if not is_skill and state["started"] and time.time() - state["started"] >= cfg["max_wall_seconds"]:
                    raise LoopError("研究セッションの実時間上限です。新しい研究フォルダで継続してください")
                is_run = job["kind"] == "execute"
                if is_run and running_runs >= cfg["max_parallel_experiments"]:
                    continue
                if not is_run and running_agents >= cfg["max_parallel_agents"]:
                    continue
                if not is_run and not is_skill and state["agent_calls"] >= cfg["max_agent_calls"]:
                    raise LoopError("AI作業回数の上限です")
                if job["attempt"] >= cfg["max_attempts"]:
                    raise LoopError("試行回数上限です")
                token = uuid.uuid4().hex
                job.update(status="running", attempt=job["attempt"]+1, token=token, started=time.time())
                if not is_run:
                    counter = "skill_calls" if is_skill else "agent_calls"
                    state[counter] = state.get(counter, 0) + 1
                db.execute("UPDATE jobs SET status='running',attempt=?,token=?,started=?,error=NULL WHERE id=?",
                           (job["attempt"], token, job["started"], job["id"]))
                db.execute("INSERT INTO attempts VALUES (?,?,?,'running',NULL)", (job["id"], job["attempt"], token))
                self.store.save(db, state)
                self.store.event(db, "claimed", {"id": job["id"], "token": token})
                return job
        return None

    def ticket_dir(self, job):
        return self.root / ".rlk" / "jobs" / str(job["id"]) / f"attempt-{job['attempt']}"

    def ticket(self, job):
        directory = self.ticket_dir(job)
        directory.mkdir(parents=True, exist_ok=True)
        if job["kind"] != "execute":
            prompt = directory / "prompt.md"
            if not prompt.exists():
                write_new(prompt, render(job, self.status(), directory / "response.json", root=self.root))
        return {"id": job["id"], "token": job["token"], "kind": job["kind"],
                "directory": str(directory), "prompt": str(directory / "prompt.md"),
                "response": str(directory / "response.json")}

    def validate_result(self, job, result, state):
        if not isinstance(result, dict):
            raise LoopError("応答はJSONオブジェクトが必要です")
        cfg, kind = state["config"], job["kind"]
        if kind == "skill_design":
            evolution.validate_design(result)
            if job["payload"]["candidate"]["evidence"] not in {r["source"] for r in result["references"]}:
                raise LoopError("検出候補の根拠をreferencesへ含めてください")
        elif kind == "skill_build":
            candidate = next((c for c in state.get("skill_candidates", []) if c["id"] == job["payload"]["candidate_id"]), None)
            if not candidate or candidate["status"] != "building" or candidate["design_hash"] != job["payload"]["design_hash"]:
                raise LoopError("この実装に対する設計承認が失効しています")
            evolution.validate_build(result, job["payload"]["design"])
        elif kind == "deepen":
            required(result, ["understanding"])
            qs = result.get("questions")
            if not isinstance(qs, list) or len(qs) != cfg["deep_questions"]:
                raise LoopError("深掘り質問数が設定と一致しません")
            for q in qs:
                required(q, ["id", "question"])
                if not re.fullmatch(r"q[1-9][0-9]*", q["id"]):
                    raise LoopError("質問IDはq1、q2の形式です")
            if len({q["id"] for q in qs}) != len(qs):
                raise LoopError("質問IDが重複しています")
        elif kind == "ideas":
            cs = result.get("candidates")
            if not isinstance(cs, list) or len(cs) != job["payload"]["count"]:
                raise LoopError("候補数が指定数と一致しません")
            for c in cs:
                required(c, ["title", "hypothesis", "rationale", "method", "risk"])
        elif kind == "plan":
            required(result, ["direction"])
            strings(result.get("open_questions"), "open_questions")
            plans = result.get("experiments")
            if not isinstance(plans, list) or len(plans) != cfg["experiments_per_cycle"]:
                raise LoopError("採用実験数が設定と一致しません")
            seen = set()
            for i, p in enumerate(plans):
                required(p, ["candidate_id", "title", "hypothesis", "method", "baseline", "treatment",
                             "metric", "direction", "success_rule", "stop_rule", "limitations"])
                if p["candidate_id"] not in {c["id"] for c in state["candidates"]} or p["candidate_id"] in seen:
                    raise LoopError("未提案または重複した候補です")
                seen.add(p["candidate_id"])
                if p["direction"] not in ("minimize", "maximize") or number(p.get("min_effect"), "min_effect") < 0:
                    raise LoopError("主指標の方向または効果量が不正です")
                p["id"] = f"e{i+1}"
        elif kind == "implement":
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
        elif kind == "review":
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
        else:
            raise LoopError("execute結果は実測経路からのみ登録できます")

    def submit(self, job_id, token, result):
        with self.store.transaction() as db:
            state = self.store.state(db)
            job = next((j for j in self.store.jobs(db) if j["id"] == job_id), None)
            if not job or job["status"] != "running" or job["token"] != token:
                raise LoopError("作業ID・token・実行状態が一致しません（再送も拒否します）")
            self.validate_result(job, result, state)
            if job["kind"] != "skill_build":
                if job["kind"] == "implement":
                    shared_source.publish(self.root, job, result)
                self._finish(db, state, job, result)
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
        db.execute("UPDATE attempts SET status='done',body=? WHERE job=? AND attempt=? AND status='running'",
                   (dump(result), job["id"], job["attempt"]))
        self.store.event(db, "completed", {"id": job["id"], "attempt": job["attempt"], "result_hash": digest(result)})
        self._advance(db, state, job, result)
        self.store.save(db, state)

    def fail(self, job_id, token, reason):
        with self.store.transaction() as db:
            job = next((j for j in self.store.jobs(db) if j["id"] == job_id), None)
            if not job or job["status"] != "running" or job["token"] != token:
                raise LoopError("実行中の正しいtokenが必要です")
            db.execute("UPDATE jobs SET status='failed',error=? WHERE id=?", (reason, job_id))
            db.execute("UPDATE attempts SET status='failed',body=? WHERE job=? AND attempt=?",
                       (dump({"error": reason}), job_id, job["attempt"]))
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
            result = {"id": job["payload"]["experiment"]["id"], "status": "failed",
                      "threshold_met": False, "error": job["error"]}
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
            state["candidates"] = [dict(c, id=f"c{i+1}") for i, c in enumerate(candidates)]
            self.store.job(db, state["cycle"], "plan", {"candidates": state["candidates"]})
            state["phase"] = "planning"
        elif kind == "plan":
            state.update(phase="approval", proposal=result, proposal_hash=digest(result))
            if state["authorized"] and state["config"]["autonomy"] == "bounded" and not result["open_questions"]:
                self.store.event(db, "bounded_plan_accepted", {"hash": state["proposal_hash"]})
                self._implement(db, state)
        elif kind == "implement":
            if result.get("status") != "failed":
                self.store.job(db, state["cycle"], "execute", {"experiment": job["payload"]["experiment"],
                                                              "implementation": result, "implementation_job": job["id"],
                                                              "proposal_hash": job["payload"]["proposal_hash"]})
            self._maybe_review(db, state)
        elif kind == "execute":
            self._maybe_review(db, state)
        elif kind == "review":
            state["history"].append({"cycle": state["cycle"], "proposal_hash": state["proposal_hash"],
                                      "proposal": state["proposal"],
                                      "direction": state["proposal"]["direction"],
                                      "results": job["payload"]["results"], "review": result})
            # レビュー受理と次サイクル作成の間で実測照合・成果物保存を必須にする。
            # 失敗時はDBトランザクションを巻き戻し、同じレビューを修正・再送できる。
            entry = state["history"][-1]
            checks = verify_evidence(self.root, entry)
            state["jobs"] = self.store.jobs(db)
            state["failed_attempts"] = self._failed_attempts(db)
            self.export(state)
            gate = {"cycle": state["cycle"], "evidence": checks,
                    "documents": self._last_report_hashes}
            entry["completion_gate"] = gate
            state.pop("jobs", None)
            state.pop("failed_attempts", None)
            self.store.event(db, "completion_gate_passed", gate)
            self.store.event(db, "cycle_completed", {"cycle": state["cycle"]})
            evolution.detect(state, self.store, db, entry)
            if state["cycle"] < state["config"]["max_cycles"]:
                self._ideas(db, state)
            else:
                state["phase"] = "complete"

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
        self.store.job(db, state["cycle"], "review", {"results": results, "proposal": state["proposal"],
                                                       "implementations": [j["result"] for j in work if j["kind"] == "implement"]})
        state["phase"] = "reviewing"

    def execute(self, job):
        state = self.status()
        cfg = state["config"]
        directory = self.ticket_dir(job)
        directory.mkdir(parents=True, exist_ok=True)
        experiment = job["payload"]["experiment"]
        implementation = job["payload"]["implementation"]
        code_dir = directory / "code"
        sources = shared_source.code_files(implementation)
        for name, code in sources.items():
            write_new(code_dir / name, code)
        manifest = {"experiment": experiment, "proposal_hash": job["payload"]["proposal_hash"],
                    "code_hash": digest(sources), "seeds": cfg["seeds"],
                    "python": sys.version, "platform": platform.platform(), "started": time.time(),
                    "job_id": job["id"], "attempt": job["attempt"]}
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
            process_run([sys.executable, str(code_dir / "experiment.py"), "--seed", str(seed), "--output", str(output)],
                        run_dir, run_dir / "stdout.log", run_dir / "stderr.log",
                        min(cfg["run_timeout_seconds"], remaining),
                        env_overrides={"PYTHONPATH": str(code_dir / "src"), "PYTHONDONTWRITEBYTECODE": "1"})
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
            progress = {"completed_seeds": [v["seed"] for v in values],
                        "remaining_seeds": cfg["seeds"][len(values):],
                        "elapsed_seconds": elapsed,
                        "eta_seconds_estimate": elapsed / len(values) * (len(cfg["seeds"]) - len(values))}
            (directory / "progress.json").write_text(dump(progress) + "\n", encoding="utf-8")
            with self.store.transaction() as db:
                self.store.event(db, "seed_completed", {"id": job["id"], "attempt": job["attempt"], **progress})
        after_code = shared_source.read_code(code_dir)
        if digest(after_code) != manifest["code_hash"]:
            raise LoopError("実行中に事前登録したコードが変更されました")
        sign = 1 if experiment["direction"] == "maximize" else -1
        effects = [sign * (x["treatment"] - x["baseline"]) for x in values]
        result = {"id": experiment["id"], "status": "measured", "n": len(values),
                  "baseline_mean": statistics.mean(x["baseline"] for x in values),
                  "treatment_mean": statistics.mean(x["treatment"] for x in values),
                  "effect_mean": statistics.mean(effects),
                  "effect_std": statistics.stdev(effects) if len(effects) > 1 else None,
                  "threshold_met": statistics.mean(effects) >= experiment["min_effect"],
                  "statistical_test": "未実施（記述統計）", "values": values,
                  "evidence": str(directory.relative_to(self.root)), "manifest": manifest}
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
                if state["started"] and job["kind"] not in evolution.KINDS:
                    timeout = min(timeout, state["config"]["max_wall_seconds"] - (time.time()-state["started"]))
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
            kinds = evolution.KINDS if skills_only else ("deepen", "ideas", "plan", "implement", "review", *evolution.KINDS)
            allowed.update(kind for kind in kinds
                           if dict(cfg, **cfg["roles"].get(kind, {}))["backend"] != "active")
        if not allowed:
            return []
        with ThreadPoolExecutor(max_workers=cfg["max_parallel_agents"] + cfg["max_parallel_experiments"]) as pool:
            while True:
                batch = []
                while True:
                    job = self.claim(allowed)
                    if not job:
                        break
                    batch.append(pool.submit(self.work, job))
                if not batch:
                    break
                completed += [f.result() for f in batch]
        self.export()
        return completed

    def export(self, state=None):
        """DBが正本。表示用文書はいつでも再生成可能。"""
        committed_snapshot = state is None
        state = self.status() if state is None else state
        documents = supporting_documents(state)
        documents.update(evolution.documents(state))
        reports = self.root / "reports"
        reports.mkdir(exist_ok=True)
        if "proposal" in state:
            proposal = state["proposal"]
            lines = [f"# 研究方針: {state['config']['name']}", "", proposal["direction"], "",
                     f"提案ハッシュ: `{state['proposal_hash']}`", "",
                     f"運転設定: {state['config']['autonomy']} / 最大{state['config']['max_cycles']}サイクル", ""]
            for p in proposal["experiments"]:
                lines += [f"## {p['id']}: {p['title']}", "", f"仮説: {p['hypothesis']}", "",
                          f"方法: {p['method']}", "", f"比較: {p['baseline']} / {p['treatment']}", "",
                          f"指標: {p['metric']} / {p['direction']} / 改善幅 {p['min_effect']}", "",
                          f"判定根拠: {p['success_rule']}", "", f"停止条件: {p['stop_rule']}", "",
                          f"限界: {p['limitations']}", ""]
            lines += ["## 未解決事項", "", *(proposal["open_questions"] or ["申告なし"])]
            documents["PROPOSAL.md"] = "\n".join(lines)+"\n"
        for entry in state["history"]:
            lines = [f"# サイクル {entry['cycle']} — {state['config']['name']}", "", entry["direction"], "",
                     "測定の差は記述統計です。統計的有意差や一般化を自動的に意味しません。", "",
                     "| 実験 | 状態 | 対照平均 | 介入平均 | 改善幅平均 | seed数 | 閾値到達 |",
                     "|---|---|---:|---:|---:|---:|---|"]
            for r in entry["results"]:
                lines.append(f"| {r['id']} | {r['status']} | {r.get('baseline_mean','—')} | {r.get('treatment_mean','—')} | {r.get('effect_mean','—')} | {r.get('n',0)} | {r['threshold_met']} |")
            for review in entry["review"]["experiments"]:
                r = next(x for x in entry["results"] if x["id"] == review["id"])
                lines += ["", f"## {review['id']}: {review['assessment']}", "", review["interpretation"], "",
                          f"限界: {review['limitations']}", "", f"証跡: `{r.get('evidence', '実行前失敗')}`", "",
                          f"エラー: {r.get('error', 'なし')}"]
            lines += ["", "## 次の問い", "", *[f"- {q}" for q in entry["review"]["next_questions"]],
                      "", "## 再利用する知見", "", *[f"- {q}" for q in entry["review"]["reusable_lessons"]]]
            documents[f"cycle-{entry['cycle']:03d}.md"] = "\n".join(lines)+"\n"
            audit = [f"# サイクル {entry['cycle']} 検証記録", "",
                     "完了確定前に、事前登録・コード・seed別数値・再集計・ログ存在・本文保存を照合する。",
                     "これは研究上の妥当性・検出力・動的配線を保証するものではない。", ""]
            for r in entry["results"]:
                audit += [f"## {r['id']}: {r['status']}", ""]
                ca = r.get("manifest", {}).get("code_audit", {})
                audit += [f"静的検査: {ca.get('status', '未実施')}", "", *ca.get("findings", []), ""]
            documents[f"cycle-{entry['cycle']:03d}-CHECKS.md"] = "\n".join(audit)+"\n"
        for name, content in documents.items():
            (reports / name).write_text(content, encoding="utf-8")
        self._last_report_hashes = verify_reports(reports, documents)
        if committed_snapshot:
            (reports / "knowledge.json").write_text(dump(state["history"])+"\n", encoding="utf-8")
            (reports / "status.json").write_text(dump(state)+"\n", encoding="utf-8")
        return str(reports)
