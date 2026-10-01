"""認証済み外部CLI用の隔離した受入試験。固定回答の再生とは別に記録する。"""

import argparse
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit.config import LoopError, dump, make_config, read_json, strings
from research_loop_kit.engine import Engine
from research_loop_kit.providers import command, process_run
from research_loop_kit.sessions import Sessions


def probe_versions(root, cfg, overrides=None):
    overrides = overrides or {}
    kinds = ("deepen", "ideas", "plan", "implement", "implementation_review", "review")
    if not isinstance(overrides, dict) or set(overrides) - set(kinds):
        raise LoopError("version-commandsは研究役割ごとのコマンド配列です")
    versions = {}
    for kind in kinds:
        role = dict(cfg, **cfg["roles"].get(kind, {}))
        if role["backend"] in ("active", "demo"):
            raise LoopError("live試験は全研究役割に認証済みの外部CLIが必要です")
        executable = command(cfg, kind)[0]
        if not shutil.which(executable):
            raise FileNotFoundError(f"外部CLI未導入: {executable}")
        # interpreter+scriptも保持する。run等のサブコマンドがある場合は明示probeを指定。
        argv = overrides.get(
            kind, [*(role["custom_command"] if role["backend"] == "custom" else [executable]), "--version"]
        )
        strings(argv, "version command")
        if not argv:
            raise LoopError("version commandは空にできません")
        out, err = root / f"version-{kind}.stdout.log", root / f"version-{kind}.stderr.log"
        process_run(argv, root, out, err, 15)
        versions[kind] = {"invocation": command(cfg, kind), "version_command": argv, "version_log": out.name}
    return versions


def run(root, settings, answers, *, cycles=3, recovery=False, version_commands=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    cfg = make_config(dict(settings, max_cycles=cycles, autonomy="review_each_cycle"))
    report = {
        "mode": "authenticated_external_cli",
        "status": "running",
        "cycles_requested": cycles,
        "versions": {},
        "phases": [],
        "recovery": "not_requested",
        "started_at": time.time(),
    }

    def save():
        (root / "live-acceptance.json").write_text(dump(report), encoding="utf-8")

    engine = None
    try:
        try:
            report["versions"] = probe_versions(root, cfg, version_commands)
        except FileNotFoundError:
            report["status"] = "blocked"
            raise
        hub = Sessions(root)
        menu = hub.open()
        choice = hub.select(menu["session_id"], "new", name="外部CLI受入試験", settings=cfg)
        engine = Engine(root / choice["path"])
        report["project"] = choice["path"]
        engine.answer(answers)
        engine.deepen()
        if recovery:
            # CLIを起動する前の作業引継ぎ中断。稼働プロセスは存在しない。
            job = engine.claim({"deepen"})
            engine.ticket(job)
            engine.fail(job["id"], job["token"], "受入試験: CLI起動前の引継ぎ中断")
            engine.retry(job["id"])
            report["recovery"] = "injected_prelaunch_failure_retried"
        while True:
            results = engine.run()
            state = engine.status()
            report["phases"].append({"cycle": state["cycle"], "phase": state["phase"], "completed": results})
            report["runs"], report["agent_calls"] = state["runs"], state["agent_calls"]
            save()
            if any(j["status"] == "failed" for j in state["jobs"] if j["kind"] not in ("skill_design", "skill_build")):
                raise LoopError("外部CLIまたは実装検証が失敗。保存したログとdoctorで確認してください")
            if state["phase"] == "questions":
                engine.answer(
                    {q: "合成データだけ。固定条件・比較予算・限界を明記して検証する" for q in engine.questions()}
                )
                engine.propose()
            elif state["phase"] == "approval":
                # --allow-executionで明示された使い捨て試験の方針だけを承認する。
                engine.accept(state["proposal_hash"])
            elif state["phase"] == "complete":
                if len(state["history"]) != cycles or not state["runs"]:
                    raise LoopError("予算停止または実験欠落で予定サイクルが完了していません")
                if recovery and not state["failed_attempts"]:
                    raise LoopError("中断履歴が保存されていません")
                report["status"] = "passed"
                break
            else:
                raise LoopError("進行が停止。状態と残り予算を確認してください")
    except Exception as exc:
        if report["status"] != "blocked":
            report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if engine:
            engine.export()
        report["finished_at"] = time.time()
        report["authentication"] = "role_responses_observed" if report["status"] == "passed" else "not_verified"
        report["limits"] = (
            "登録済みCLI設定での観測。認証方式の独立監査ではない。復旧注入はCLI起動前の中断であり実プロセスクラッシュ試験ではない。"
        )
        save()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="未作成の隔離試験フォルダ")
    parser.add_argument("--settings", required=True)
    parser.add_argument("--answers", required=True)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--recovery", action="store_true")
    parser.add_argument("--version-commands", help="役割ごとのCLI版確認コマンド配列を指定するJSON")
    parser.add_argument(
        "--allow-execution", action="store_true", help="隔離試験でCLI・生成コードを実行し方針を承認する"
    )
    args = parser.parse_args()
    if not args.allow_execution or not 2 <= args.cycles <= 100:
        parser.error("--allow-executionと2..100の--cyclesが必要です")
    result = run(
        args.output,
        read_json(args.settings),
        read_json(args.answers),
        cycles=args.cycles,
        recovery=args.recovery,
        version_commands=read_json(args.version_commands) if args.version_commands else None,
    )
    print(dump(result))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
