"""確認の標本数と比較ファミリーを固定し、保守的な片側二項検定を再計算する。"""

import math

from .config import LoopError, nonempty, number
from .store import digest


def validate(protocol):
    keys = {"family_id", "members", "seed_count", "method", "alpha", "multiplicity", "missing_policy", "rationale"}
    if not isinstance(protocol, dict) or set(protocol) != keys:
        raise LoopError("確認方針の必須項目が不正です")
    nonempty(protocol["family_id"], "family_id")
    nonempty(protocol["rationale"], "確認方針の根拠・独立なseed標本の仮定")
    members = protocol["members"]
    if not isinstance(members, list) or not 1 <= len(members) <= 100:
        raise LoopError("比較ファミリーは1..100件の探索結果です")
    ids = set()
    for member in members:
        if not isinstance(member, dict) or set(member) != {"cycle", "experiment", "result_hash"}:
            raise LoopError("各比較にはcycle/experiment/result_hashが必要です")
        if type(member["cycle"]) is not int or member["cycle"] < 1:
            raise LoopError("cycleが不正です")
        nonempty(member["experiment"], "実験ID")
        nonempty(member["result_hash"], "結果ハッシュ")
        if member["result_hash"] in ids:
            raise LoopError("比較ファミリーの結果が重複しています")
        ids.add(member["result_hash"])
    if type(protocol["seed_count"]) is not int or not 2 <= protocol["seed_count"] <= 1000:
        raise LoopError("確認seed数は2..1000です")
    if protocol["method"] not in ("descriptive_mean", "paired_exceedance_test"):
        raise LoopError("確認方法が不正です")
    alpha = number(protocol["alpha"], "alpha")
    if not 0 < alpha <= 0.1 or protocol["multiplicity"] != "bonferroni" or protocol["missing_policy"] != "inconclusive":
        raise LoopError("alpha・多重比較・欠測方針が不正です")
    return protocol


def registered(state, result_hash):
    return next(
        (
            p
            for p in state.get("confirmation_protocols", [])
            if any(m["result_hash"] == result_hash for m in p["protocol"]["members"])
        ),
        None,
    )


def analyze(values, spec, registration, *, complete=True):
    if not registration:
        return None
    protocol = registration["protocol"]
    validate(protocol)
    if registration["hash"] != digest(protocol):
        raise LoopError("確認事前登録のハッシュが不正です")
    sign = 1 if spec["direction"] == "maximize" else -1
    effects = [sign * (v["treatment"] - v["baseline"]) for v in values]
    n = len(effects)
    valid = complete and n == protocol["seed_count"]
    threshold = spec["min_effect"]
    wins = sum(e > threshold for e in effects)
    # 同値は成功に数えず、全seedを分母にする。帰無仮説P(effect>threshold)<=0.5の保守的検定。
    p = sum(math.comb(n, k) for k in range(wins, n + 1)) / (1 << n) if n else 1.0
    limit = protocol["alpha"] / len(protocol["members"])
    mean = sum(effects) / n if n else None
    mean_met = valid and mean >= threshold
    statistical = valid and protocol["method"] == "paired_exceedance_test" and p <= limit
    return {
        "protocol_hash": registration["hash"],
        "family_id": protocol["family_id"],
        "family_size": len(protocol["members"]),
        "planned_n": protocol["seed_count"],
        "n": n,
        "method": protocol["method"],
        "alpha_per_comparison": limit,
        "wins_over_min_effect": wins,
        "p_value": p if protocol["method"] == "paired_exceedance_test" else None,
        "threshold_replicated": mean_met,
        "statistical_criterion_met": statistical,
        "status": "inconclusive"
        if not valid
        else "registered_statistical_support"
        if statistical
        else "threshold_replicated"
        if mean_met
        else "not_supported",
        "hypothesis": "P(paired effect > preregistered min_effect) <= 0.5",
        "limits": "独立なseed標本が必要。平均効果の有意差検定ではなく、外部条件への一般化を保証しない",
    }
