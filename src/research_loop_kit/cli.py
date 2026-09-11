"""日本語の対話と、Agentから呼べるJSONインタフェース。"""

import argparse
import json
from pathlib import Path
import shutil
import sys

from .config import BACKENDS, LoopError, dump, read_json
from .engine import Engine
from .setup import initialize
from .evolution import KINDS


def parser():
    p = argparse.ArgumentParser(description="研究テーマの深掘りから実験・分析まで")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="空の研究フォルダを作成")
    init.add_argument("root")
    init.add_argument("--config", help="初期設定のJSONファイル（部分指定可）")
    init.add_argument("--backend", choices=BACKENDS)
    init.add_argument("--name")
    init.add_argument("--wizard", action="store_true")
    for name in ("interview", "questions", "deepen", "propose", "status", "pause", "resume", "export", "doctor", "skill-next", "skill-run", "skill-resume"):
        sub.add_parser(name).add_argument("root")
    for name in ("answer", "configure"):
        cmd = sub.add_parser(name)
        cmd.add_argument("root")
        cmd.add_argument("--file", required=True)
    next_p = sub.add_parser("next", help="現在のAgent向けに1件の作業票を取得")
    next_p.add_argument("root")
    submit = sub.add_parser("submit")
    submit.add_argument("root")
    submit.add_argument("job", type=int)
    submit.add_argument("--token", required=True)
    submit.add_argument("--file", required=True)
    skill_submit = sub.add_parser("skill-submit")
    skill_submit.add_argument("root")
    skill_submit.add_argument("job", type=int)
    skill_submit.add_argument("--token", required=True)
    skill_submit.add_argument("--file", required=True)
    for decision in ("accept", "reject", "revise"):
        cmd = sub.add_parser("skill-" + decision)
        cmd.add_argument("root")
        cmd.add_argument("candidate")
        cmd.add_argument("--hash", required=True)
        cmd.add_argument("--feedback", default="")
    disable = sub.add_parser("skill-disable")
    disable.add_argument("root")
    disable.add_argument("name")
    for name in ("fail", "recover", "skill-fail", "skill-recover"):
        cmd = sub.add_parser(name)
        cmd.add_argument("root")
        cmd.add_argument("job", type=int)
        cmd.add_argument("--token", required=True)
        cmd.add_argument("--reason", required=True)
        if name in ("recover", "skill-recover"):
            cmd.add_argument("--process-stopped", action="store_true", required=True)
    for name in ("retry", "skip-failed", "skill-retry"):
        cmd = sub.add_parser(name)
        cmd.add_argument("root")
        cmd.add_argument("job", type=int)
    accept = sub.add_parser("accept")
    accept.add_argument("root")
    accept.add_argument("--hash", required=True)
    revise = sub.add_parser("revise")
    revise.add_argument("root")
    revise.add_argument("--feedback", required=True)
    run = sub.add_parser("run", help="接続したCLIで待ちジョブを処理")
    run.add_argument("root")
    run.add_argument("--experiments-only", action="store_true")
    demo = sub.add_parser("demo", help="認証不要の計算実験による動作実証")
    demo.add_argument("root")
    demo.add_argument("--cycles", type=int, default=2)
    return p


def interview(engine):
    if not sys.stdin.isatty():
        raise LoopError("対話端末がありません。questions と answer --file を使ってください")
    for key, question in engine.questions().items():
        while True:
            answer = input(f"\n{question}\n> ").strip()
            if answer:
                engine.answer({key: answer})
                break
            print("分からない場合は「未確定」と入力できます。")
    print("回答を保存しました。rlk deepen / rlk propose で次の段階へ進めます。")


def wizard(root, overrides):
    if not sys.stdin.isatty():
        raise LoopError("wizardには対話端末が必要です。init --configまたは起動中のAgentを使ってください")
    overrides.setdefault("name", input("研究プロジェクト名 [新しい研究]: ").strip() or "新しい研究")
    overrides.setdefault("backend", input("Agent [active / codex / claude / gemini / opencode / custom] (active): ").strip() or "active")
    for key, label, default in [
        ("candidate_count", "各サイクルで出す実験候補数", 6),
        ("proposal_workers", "候補を考えるワーカー数", 3),
        ("experiments_per_cycle", "採用する実験数", 2),
        ("max_parallel_agents", "AI作業の同時処理数", 2),
        ("max_parallel_experiments", "実験の同時実行数", 1),
        ("deep_questions", "追加の深掘り質問数", 4),
        ("max_cycles", "最大サイクル数", 1),
        ("max_agent_calls", "AI作業回数上限", 40),
        ("max_runs", "seed別実行回数上限", 30),
        ("max_wall_seconds", "研究セッション時間上限（秒）", 7200),
    ]:
        current = overrides.get(key, default)
        text = input(f"{label} [{current}]: ").strip()
        overrides[key] = int(text) if text else current
    text = input("seedをカンマ区切りで [11,22,33,44,55]: ").strip()
    if text:
        overrides["seeds"] = [int(x.strip()) for x in text.split(",")]
    overrides["autonomy"] = input("方針の確認 [review_each_cycle / bounded] (review_each_cycle): ").strip() or "review_each_cycle"
    initialize(root, overrides)
    interview(Engine(root))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        command = args.command
        if command == "init":
            overrides = read_json(args.config) if args.config else {}
            if args.backend:
                overrides["backend"] = args.backend
            if args.name:
                overrides["name"] = args.name
            if args.wizard:
                wizard(args.root, overrides)
            else:
                print(initialize(args.root, overrides))
            return 0
        if command == "demo":
            from .demo import ANSWERS
            initialize(args.root, {"name": "二次関数による動作実証", "backend": "demo", "max_cycles": args.cycles,
                                   "autonomy": "bounded", "max_parallel_experiments": 2,
                                   "max_agent_calls": 100 * args.cycles, "max_runs": 10 * args.cycles})
            engine = Engine(args.root)
            engine.answer(ANSWERS)
            engine.deepen()
            engine.run()
            engine.answer({key: "8更新、同じ初期点、合成データ、実研究の主張には使わない" for key in engine.questions()})
            engine.propose()
            engine.run()
            engine.accept(engine.status()["proposal_hash"])
            engine.run()
            state = engine.status()
            print(dump({"phase": state["phase"], "cycles": len(state["history"]), "runs": state["runs"],
                        "agent_calls": state["agent_calls"], "reports": engine.export()}))
            return 0 if state["phase"] == "complete" else 2
        engine = Engine(args.root)
        output = None
        if command in ("skill-fail", "skill-recover", "skill-retry"):
            if not any(j["id"] == args.job and j["kind"] in KINDS for j in engine.status()["jobs"]):
                raise LoopError("スキル作業のIDを指定してください")
            command = command.removeprefix("skill-")
        if command == "status":
            output = engine.status()
        elif command == "questions":
            output = engine.questions()
        elif command == "interview":
            interview(engine)
        elif command == "answer":
            engine.answer(read_json(args.file))
        elif command == "configure":
            engine.configure(read_json(args.file))
        elif command == "deepen":
            engine.deepen()
        elif command == "propose":
            engine.propose()
        elif command in ("next", "skill-next"):
            job = engine.claim(set(KINDS) if command == "skill-next" else {"deepen", "ideas", "plan", "implement", "review", *KINDS})
            output = engine.ticket(job) if job else {"phase": engine.status()["phase"], "message": "取得できるAI作業はありません。statusで実行中・失敗・実験待ちを確認してください"}
        elif command in ("submit", "skill-submit"):
            if command == "skill-submit" and not any(j["id"] == args.job and j["kind"] in KINDS for j in engine.status()["jobs"]):
                raise LoopError("スキル作業のIDを指定してください")
            engine.submit(args.job, args.token, read_json(args.file))
            engine.export()
        elif command in ("skill-accept", "skill-reject", "skill-revise"):
            engine.skill_decision(args.candidate, command.removeprefix("skill-"), args.hash, args.feedback)
        elif command == "skill-disable":
            engine.disable_skill(args.name)
        elif command == "skill-resume":
            engine.resume_skills()
        elif command == "skill-run":
            output = engine.run(skills_only=True)
            if any(j["status"] == "failed" and j["kind"] in KINDS for j in engine.status()["jobs"]):
                print(dump(output))
                return 2
        elif command in ("fail", "recover"):
            engine.fail(args.job, args.token, args.reason)
            engine.export()
        elif command == "retry":
            engine.retry(args.job)
        elif command == "skip-failed":
            engine.skip_failed(args.job)
        elif command == "accept":
            engine.accept(args.hash)
        elif command == "revise":
            engine.revise(args.feedback)
        elif command == "pause":
            engine.pause()
        elif command == "resume":
            engine.resume()
        elif command == "run":
            state = engine.status()
            if not args.experiments_only:
                for job in state["jobs"]:
                    cfg = dict(state["config"], **state["config"]["roles"].get(job["kind"], {}))
                    if job["status"] == "pending" and job["kind"] != "execute" and cfg["backend"] == "active":
                        raise LoopError("現在のAgentではrlk next → 作業票を処理 → rlk submitを使います。実験はrun --experiments-only")
            output = engine.run(args.experiments_only)
            if any(j["status"] == "failed" for j in engine.status()["jobs"]):
                print(dump(output))
                return 2
        elif command == "export":
            output = {"reports": engine.export()}
        elif command == "doctor":
            state = engine.status()
            output = {"python": sys.version, "backend": state["config"]["backend"],
                      "cli_paths": {name: shutil.which(name) for name in ("codex", "claude", "gemini", "opencode")},
                      "phase": state["phase"],
                      "unfinished": [{"id": j["id"], "kind": j["kind"], "status": j["status"], "token": j["token"],
                                      "error": j["error"]} for j in state["jobs"] if j["status"] in ("running", "failed")],
                      "note": "存在確認のみ。認証・ツール権限・研究の妥当性は確認しません"}
        if output is not None:
            print(dump(output))
        return 0
    except (LoopError, OSError, ValueError) as exc:
        print(f"停止: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
