"""状態の説明と復旧案内。判定は実際のジョブ取得条件を共有する。"""

from .store import digest


def diagnose(state, blocker, exhausted):
    cfg = state["config"]
    jobs = state["jobs"]
    agents = sum(j["status"] == "running" and j["kind"] != "execute" for j in jobs)
    runs = sum(j["status"] == "running" and j["kind"] == "execute" for j in jobs)
    remaining = {
        key: max(0, cfg[limit] - state.get(counter, 0))
        for key, limit, counter in (
            ("agent_calls", "max_agent_calls", "agent_calls"),
            ("validation_calls", "max_validation_calls", "validation_calls"),
            ("skill_calls", "max_skill_calls", "skill_calls"),
            ("runs", "max_runs", "runs"),
        )
    }
    items, actions = [], []
    for j in jobs:
        if j["status"] == "pending":
            reason = blocker(state, j, agents, runs)
            items.append({"id": j["id"], "kind": j["kind"], "status": "pending", "blocker": reason})
            if reason is None and j["kind"] == "execute" and not remaining["runs"]:
                actions.append(
                    {"command": "branch", "job": j["id"], "reason": "取得は可能ですがseed起動予算がありません"}
                )
            elif reason is None:
                actions.append(
                    {
                        "command": "run --experiments-only" if j["kind"] == "execute" else "next",
                        "job": j["id"],
                        "reason": "取得可能な作業があります",
                    }
                )
            elif reason != "wait":
                actions.append({"command": "branch", "job": j["id"], "reason": reason})
        elif j["status"] in ("running", "failed"):
            items.append({"id": j["id"], "kind": j["kind"], "status": j["status"], "error": j["error"]})
            if j["status"] == "running":
                actions.append(
                    {
                        "command": "wait_or_recover",
                        "job": j["id"],
                        "reason": "稼働中。応答待ちか、プロセス停止確認後にrecover（tokenが必要）",
                    }
                )
            else:
                command = (
                    "retry"
                    if j["attempt"] < cfg["max_attempts"]
                    else (
                        "skip-failed_or_branch"
                        if j["kind"] in ("implement", "implementation_review", "execute")
                        else "branch"
                    )
                )
                actions.append({"command": command, "job": j["id"], "reason": "失敗原因と保存済み成果物を確認"})
    if state["paused"]:
        actions.insert(0, {"command": "resume", "reason": "研究は一時停止中です"})
    if state["phase"] == "approval":
        actions.insert(
            0,
            {
                "command": "accept_or_revise",
                "hash": state.get("proposal_hash"),
                "reason": "方針の承認待ちです。未解決事項を確認してください",
            },
        )
    if state["phase"] in ("interview", "questions"):
        actions.insert(0, {"command": "questions", "reason": "未回答の質問を確認してください"})
    origins = {
        digest(j["result"])
        for j in jobs
        if j["kind"] == "execute" and j["status"] == "done" and j["payload"].get("validation")
    }
    candidates = []
    if state["phase"] == "complete" and not state["paused"] and not exhausted(state) and remaining["runs"]:
        for h in state["history"]:
            for r in h["results"]:
                if (
                    r["status"] == "measured"
                    and r.get("threshold_met")
                    and r.get("manifest", {}).get("stage", "exploration") == "exploration"
                    and digest(r) in origins
                ):
                    candidates.append({"cycle": h["cycle"], "experiment": r["id"], "hash": digest(r)})
    if candidates:
        actions.append({"command": "confirm", "reason": "未使用seedを選び、固定条件の探索結果を確認できます"})
    if not actions:
        actions.append(
            {"command": "review_or_branch", "reason": "取得可能な作業はありません。結果確認または分岐を選択"}
        )
    return {
        "phase": state["phase"],
        "paused": state["paused"],
        "remaining": remaining,
        "deadline": state["started"] + cfg["max_wall_seconds"] if state["started"] else None,
        "jobs": items,
        "next_actions": actions,
        "confirmation_candidates": candidates,
        "confirmation_note": "候補一覧は予備判定。実行時に証跡・環境・seed・予算を再検査します",
    }
