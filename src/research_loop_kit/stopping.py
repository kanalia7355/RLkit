"""固定した停止方針を適用し、観測列から停止理由を再検算する。

このファイルは実験コードへrlk_stop.pyとして版固定されるためstdlibだけを使う。
観測列は実装の申告であり、隠れた計算や虚偽の観測を検出するsandboxではない。
"""

import json
import math
import os
from pathlib import Path


def validate_policy(policy):
    if not isinstance(policy, dict) or policy.get("kind") not in ("fixed_iterations", "convergence", "no_improvement"):
        raise ValueError("停止方針のkindはfixed_iterations / convergence / no_improvementです")
    keys = {"kind", "max_iterations"}
    if policy["kind"] != "fixed_iterations":
        keys |= {"min_iterations", "patience", "tolerance"}
        if policy["kind"] == "no_improvement":
            keys.add("direction")
    if set(policy) != keys:
        raise ValueError("停止方針の項目がkindと一致しません")
    cap = policy["max_iterations"]
    if type(cap) is not int or not 1 <= cap <= 100000:
        raise ValueError("max_iterationsは1..100000の整数です")
    if policy["kind"] != "fixed_iterations":
        for key in ("min_iterations", "patience"):
            if type(policy[key]) is not int or not 1 <= policy[key] <= cap:
                raise ValueError(f"{key}は1..max_iterationsの整数です")
        tol = policy["tolerance"]
        if type(tol) not in (float, int) or not math.isfinite(tol) or tol < 0:
            raise ValueError("toleranceは有限の非負数です")
        if policy["kind"] == "no_improvement" and policy["direction"] not in ("minimize", "maximize"):
            raise ValueError("停止判定のdirectionはminimize / maximizeです")
    return dict(policy)


class StopController:
    def __init__(self, policy, record_path=None):
        self.policy = validate_policy(policy)
        self.record_path = Path(record_path) if record_path else None
        self.observations = []
        self.reason = None
        self.streak = 0
        self.best = None

    @classmethod
    def from_environment(cls):
        return cls(json.loads(os.environ["RLK_STOP_POLICY"]), os.environ.get("RLK_STOP_RECORD"))

    def step(self, value):
        if self.reason:
            raise ValueError("停止済みの反復を継続できません")
        if type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError("停止判定の観測値は有限数です")
        p = self.policy
        if self.observations and p["kind"] == "convergence":
            self.streak = self.streak + 1 if abs(value - self.observations[-1]) <= p["tolerance"] else 0
        elif p["kind"] == "no_improvement":
            sign = 1 if p["direction"] == "maximize" else -1
            if self.best is None or sign * (value - self.best) > p["tolerance"]:
                self.best, self.streak = value, 0
            else:
                self.streak += 1
        self.observations.append(value)
        n = len(self.observations)
        if p["kind"] != "fixed_iterations" and n >= p["min_iterations"] and self.streak >= p["patience"]:
            self.reason = p["kind"]
        elif n == p["max_iterations"]:
            self.reason = "fixed_iterations" if p["kind"] == "fixed_iterations" else "max_iterations"
        if self.reason and self.record_path:
            self.record_path.write_text(
                json.dumps(self.record(), ensure_ascii=False, allow_nan=False), encoding="utf-8"
            )
        return self.reason is not None

    def record(self):
        if not self.reason:
            raise ValueError("停止条件に未到達です")
        return {
            "policy": self.policy,
            "iterations": len(self.observations),
            "reason": self.reason,
            "observations": self.observations,
        }


def verify_record(record, policy):
    if not isinstance(record, dict) or set(record) != {"policy", "iterations", "reason", "observations"}:
        raise ValueError("停止記録の形式が不正です")
    if record["policy"] != policy or type(record["iterations"]) is not int:
        raise ValueError("停止記録と事前登録の方針が一致しません")
    values = record["observations"]
    if not isinstance(values, list) or not 1 <= len(values) <= policy["max_iterations"]:
        raise ValueError("停止記録の観測件数が不正です")
    replay = StopController(policy)
    for value in values:
        replay.step(value)
    if replay.record() != record:
        raise ValueError("停止理由・反復回数が観測列と一致しません")
    return record
