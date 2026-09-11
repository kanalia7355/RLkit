"""Agentが内部で使うセッション入口。ユーザーには会話を提示する。"""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .cli import main as loop_main
from .config import LoopError, dump, read_json
from .sessions import Sessions
from .importing import preview


def hook(root, provider, payload):
    cwd = Path(payload.get("cwd", str(root))).resolve()
    if ".rlk" in cwd.parts and "jobs" in cwd.parts:
        return {}
    if payload.get("source") == "compact":
        context = "会話の圧縮です。直前に選んだ研究とsession_idを維持し、進め方の選択を繰り返さず状態を再確認してください。"
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    menu = Sessions(root).menu()
    context = ("新しく起動・再開された対話セッションです。RESEARCH_START.mdを読み、入口を新規に開いてください。"
               "以前のsession_idをこの起動の選択済みIDとして流用しないでください。"
               "ただし具体的なJobとtokenを指定された実働Agentは、その作業票を優先し研究の質問を開始しないでください。\n"
               + dump(menu))
    return {"systemMessage": menu["opening"],
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}


def main(root, argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="現在のAI Agentが扱う研究セッションの入口")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("open")
    inspect = sub.add_parser("import-preview")
    inspect.add_argument("--source", required=True)
    inspect.add_argument("--files", nargs="+", required=True)
    importing = sub.add_parser("import-study")
    importing.add_argument("session")
    importing.add_argument("--source", required=True)
    importing.add_argument("--files", nargs="+", required=True)
    importing.add_argument("--hash", required=True)
    importing.add_argument("--name", required=True)
    importing.add_argument("--context", required=True)
    importing.add_argument("--settings")
    h = sub.add_parser("hook")
    h.add_argument("--provider", choices=("claude", "gemini"), required=True)
    choose = sub.add_parser("select")
    choose.add_argument("session")
    choose.add_argument("--action", dest="choice", required=True)
    choose.add_argument("--project")
    choose.add_argument("--name")
    choose.add_argument("--settings")
    choose.add_argument("--feedback", default="")
    choose.add_argument("--candidates", nargs="+")
    choose.add_argument("--plan-job", type=int)
    work = sub.add_parser("work")
    work.add_argument("session")
    work.add_argument("command")
    work.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    hub = Sessions(root)
    try:
        if args.action == "import-preview":
            result = preview(args.source, args.files)
        elif args.action == "import-study":
            result = hub.import_study(args.session, args.source, args.files, args.hash, args.name,
                                      read_json(args.context), read_json(args.settings) if args.settings else None)
        elif args.action == "hook":
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise LoopError("hook入力はJSONオブジェクトです")
            result = hook(root, args.provider, payload)
        elif args.action == "open":
            result = hub.open()
        elif args.action == "select":
            result = hub.select(args.session, args.choice, project_id=args.project, name=args.name,
                                settings=read_json(args.settings) if args.settings else None,
                                feedback=args.feedback, candidate_ids=args.candidates, plan_job=args.plan_job)
        else:
            allowed = {"status", "questions", "answer", "configure", "deepen", "propose", "next", "submit", "fail",
                       "recover", "retry", "skip-failed", "accept", "revise", "pause", "resume", "run", "export", "doctor",
                       "skill-next", "skill-submit", "skill-run", "skill-accept", "skill-reject", "skill-revise", "skill-disable",
                       "skill-fail", "skill-recover", "skill-retry", "skill-resume"}
            if args.command not in allowed:
                raise LoopError("この入口では指定された内部操作を使えません")
            path = hub.target(args.session, args.command)
            return loop_main([args.command, str(path), *args.args])
        print(dump(result))
        return 0
    except (LoopError, OSError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"停止: {exc}", file=sys.stderr)
        return 2
