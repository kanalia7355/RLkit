"""研究の任意時間予算。無期限と作業稼働時間・旧経過時間を区別する。"""

import json
import math
import time


def active_seconds(db, started, now=None):
    if started is None:
        return 0.0
    now = time.time() if now is None else now
    skills = {r["id"] for r in db.execute("SELECT id FROM jobs WHERE kind IN ('skill_design','skill_build')")}
    pending, intervals = {}, []
    for row in db.execute(
        "SELECT time,kind,body FROM events WHERE kind IN ('claimed','completed','failed') ORDER BY id"
    ):
        body = json.loads(row["body"])
        identifier = body.get("id")
        if identifier in skills:
            continue
        if row["kind"] == "claimed":
            pending[identifier] = row["time"]
        elif identifier in pending:
            intervals.append((max(started, pending.pop(identifier)), row["time"]))
    intervals.extend((max(started, begin), now) for begin in pending.values())
    total, end = 0.0, started
    for begin, finish in sorted(intervals):
        if finish > max(begin, end):
            total += finish - max(begin, end)
            end = finish
    return total


def remaining_seconds(state, now=None):
    cap = state["config"]["max_wall_seconds"]
    if cap is None:
        return math.inf
    if state["config"]["wall_time_basis"] == "active_jobs":
        used = state.get("active_seconds", 0.0)
    else:
        now = time.time() if now is None else now
        used = max(0, now - state["started"]) if state["started"] is not None else 0
    return max(0, cap - used)
