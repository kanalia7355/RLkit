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


def validate_comparison(policy):
    keys = {"basis", "unit", "rationale", "baseline", "treatment"}
    if not isinstance(policy, dict) or set(policy) != keys:
        raise ValueError("比較方針にはbasis/unit/rationale/baseline/treatmentが必要です")
    if policy["basis"] not in ("iterations", "evaluations", "wall_seconds", "independent"):
        raise ValueError("比較予算のbasisが不正です")
    if any(not isinstance(policy[k], str) or not policy[k].strip() for k in ("unit", "rationale")):
        raise ValueError("比較の単位と根拠を指定してください")
    for name in ("baseline", "treatment"):
        item = policy[name]
        if not isinstance(item, dict) or set(item) != {"stop_policy", "max_evaluations", "max_wall_seconds"}:
            raise ValueError("各条件に停止方針・評価回数・実行時間の上限が必要です")
        validate_policy(item["stop_policy"])
        if type(item["max_evaluations"]) is not int or not 1 <= item["max_evaluations"] <= 100000000:
            raise ValueError("評価回数上限が不正です")
        cap = item["max_wall_seconds"]
        if type(cap) not in (int, float) or not math.isfinite(cap) or not 0 < cap <= 86400:
            raise ValueError("実行時間上限が不正です")
    basis = policy["basis"]
    if basis != "independent":
        a, b = policy["baseline"], policy["treatment"]
        key = "max_" + basis
        if basis == "iterations":
            a, b, key = a["stop_policy"], b["stop_policy"], "max_iterations"
        if a[key] != b[key]:
            raise ValueError("比較対象の割り当て予算が一致しません")
    return policy


class ComparisonRecorder:
    """計画で指定した計測範囲のコストを条件別に記録する（Python sandboxではない）。"""

    def __init__(self, policy, record_path=None, treatment_record_path=None):
        self.treatment_record_path = treatment_record_path
        self.policy = validate_comparison(policy)
        self.record_path = Path(record_path) if record_path else None
        self.conditions = {}
        self.active = None

    @classmethod
    def from_environment(cls):
        return cls(
            json.loads(os.environ["RLK_COMPARISON_POLICY"]),
            os.environ.get("RLK_COMPARISON_RECORD"),
            os.environ.get("RLK_STOP_RECORD"),
        )

    def condition(self, name):
        if name not in ("baseline", "treatment") or name in self.conditions or self.active:
            raise ValueError("比較条件は重複・重ね合わせずに計測してください")
        return _Condition(self, name)

    def record(self):
        if set(self.conditions) != {"baseline", "treatment"}:
            raise ValueError("両条件の計測が必要です")
        return {"policy": self.policy, "conditions": self.conditions}


class _Condition:
    def __init__(self, owner, name):
        self.owner, self.name = owner, name
        self.stop = StopController(
            owner.policy[name]["stop_policy"], owner.treatment_record_path if name == "treatment" else None
        )
        self.evaluations = 0
        self.started = None

    def __enter__(self):
        import time

        if self.owner.active or self.name in self.owner.conditions:
            raise ValueError("比較条件の計測が重複しています")
        self.owner.active = self.name
        self.started = time.monotonic()
        return self

    def step(self, value, evaluations=1):
        if self.owner.active != self.name or self.started is None:
            raise ValueError("conditionのwithブロック内で計測してください")
        if type(evaluations) is not int or evaluations < 0:
            raise ValueError("評価回数は非負整数です")
        self.evaluations += evaluations
        if self.evaluations > self.owner.policy[self.name]["max_evaluations"]:
            raise ValueError("評価回数の割り当て予算を超過しました")
        return self.stop.step(value)

    def __exit__(self, kind, exc, tb):
        import time

        self.owner.active = None
        if kind:
            return False
        elapsed = time.monotonic() - self.started
        if elapsed > self.owner.policy[self.name]["max_wall_seconds"]:
            raise ValueError("条件別の実行時間予算を超過しました")
        self.owner.conditions[self.name] = {
            "stop": self.stop.record(),
            "evaluations": self.evaluations,
            "wall_seconds": elapsed,
        }
        if len(self.owner.conditions) == 2 and self.owner.record_path:
            self.owner.record_path.write_text(json.dumps(self.owner.record(), allow_nan=False), encoding="utf-8")


def verify_comparison(record, policy, metrics=None):
    validate_comparison(policy)
    if not isinstance(record, dict) or set(record) != {"policy", "conditions"} or record["policy"] != policy:
        raise ValueError("比較記録の方針が事前登録と一致しません")
    if not isinstance(record["conditions"], dict) or set(record["conditions"]) != {"baseline", "treatment"}:
        raise ValueError("両条件の比較記録が必要です")
    for name, item in record["conditions"].items():
        if not isinstance(item, dict) or set(item) != {"stop", "evaluations", "wall_seconds"}:
            raise ValueError("条件別コストの形式が不正です")
        verify_record(item["stop"], policy[name]["stop_policy"])
        if type(item["evaluations"]) is not int or not 0 <= item["evaluations"] <= policy[name]["max_evaluations"]:
            raise ValueError("条件別評価回数の予算超過です")
        wall = item["wall_seconds"]
        if (
            type(wall) not in (int, float)
            or not math.isfinite(wall)
            or not 0 <= wall <= policy[name]["max_wall_seconds"]
        ):
            raise ValueError("条件別時間の予算超過です")
        if metrics is not None and item["stop"]["observations"][-1] != metrics[name]:
            raise ValueError("停止観測の最終値と主指標が一致しません")
    return record
