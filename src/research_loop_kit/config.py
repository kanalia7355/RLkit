"""研究分野から独立した設定と入力検証。"""

import copy
import json
import math
from pathlib import Path


class LoopError(ValueError):
    pass


BACKENDS = ("active", "codex", "claude", "gemini", "opencode", "custom", "demo")
DEFAULTS = {
    "schema_version": 1,
    "name": "新しい研究",
    "backend": "active",
    "model": "",
    "agent_args": [],
    "custom_command": [],
    "roles": {},
    "candidate_count": 6,
    "proposal_workers": 3,
    "experiments_per_cycle": 2,
    "max_parallel_agents": 2,
    "max_parallel_experiments": 1,
    "deep_questions": 4,
    "seeds": [11, 22, 33, 44, 55],
    "max_cycles": 1,
    "max_agent_calls": 40,
    "max_runs": 30,
    "max_attempts": 2,
    "agent_timeout_seconds": 900,
    "run_timeout_seconds": 300,
    "max_wall_seconds": 7200,
    "autonomy": "review_each_cycle",
}

QUESTIONS = {
    "topic": "どの分野・テーマを研究したいですか？",
    "interest": "特に気になる現象・疑問、面白いと感じることは何ですか？",
    "motivation": "何が分かると、誰にとってどのように役立ちますか？",
    "prior_work": "既に試したこと・分かっていること・参考資料はありますか？（なければ未調査）",
    "data": "使えるデータ・実験対象・利用条件は何ですか？（なければ未確保）",
    "method": "想定する実験方法は？（計算実験・データ分析・実機・観察など）",
    "evaluation": "何を測り、何と比較すると疑問に答えられそうですか？",
    "resources": "使える計算機・時間・費用・外部サービスの制約は？",
    "constraints": "変更してはいけない条件、対象外にすることは？",
    "deliverable": "最後に何を得たいですか？（論文・検証結果・実装・発表資料など）",
}


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                          parse_constant=lambda x: (_ for _ in ()).throw(LoopError(f"非有限値: {x}")))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoopError(f"JSONを読めません: {path}: {exc}") from exc


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise LoopError(f"{label} は空でない文字列が必要です")
    return value


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LoopError(f"{label} は有限の数値が必要です")
    return value


def strings(value, label):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise LoopError(f"{label} は文字列の配列が必要です")


def validate(config):
    if set(config) != set(DEFAULTS):
        raise LoopError(f"設定キーが一致しません: {set(config) ^ set(DEFAULTS)}")
    nonempty(config["name"], "name")
    if config["schema_version"] != 1 or type(config["schema_version"]) is not int:
        raise LoopError("未対応の設定バージョンです")
    for key in DEFAULTS:
        if type(DEFAULTS[key]) is int and key != "schema_version":
            if type(config[key]) is not int or not 1 <= config[key] <= 10_000_000:
                raise LoopError(f"{key} は正の整数が必要です")
    if config["backend"] not in BACKENDS:
        raise LoopError("未対応の backend です")
    if not isinstance(config["model"], str):
        raise LoopError("model は文字列が必要です")
    for key in ("agent_args", "custom_command"):
        strings(config[key], key)
    if config["backend"] == "custom" and not config["custom_command"]:
        raise LoopError("custom_command が必要です")
    if config["autonomy"] not in ("review_each_cycle", "bounded"):
        raise LoopError("autonomy は review_each_cycle / bounded です")
    if not isinstance(config["roles"], dict):
        raise LoopError("roles はオブジェクトが必要です")
    for role, override in config["roles"].items():
        if role not in ("deepen", "ideas", "plan", "implement", "review", "skill_design", "skill_build"):
            raise LoopError(f"不明な役割: {role}")
        if not isinstance(override, dict) or set(override) - {"backend", "model", "agent_args", "custom_command"}:
            raise LoopError(f"不正な役割設定: {role}")
        merged = dict(config, **override, roles={})
        validate(merged)
    if not isinstance(config["seeds"], list) or not config["seeds"]:
        raise LoopError("seeds は空でない整数配列です")
    if any(type(x) is not int or not 0 <= x < 2**32 for x in config["seeds"]):
        raise LoopError("seed は 0 以上 2^32 未満の整数です")
    if len(set(config["seeds"])) != len(config["seeds"]):
        raise LoopError("seed が重複しています")
    if config["experiments_per_cycle"] > config["candidate_count"]:
        raise LoopError("採用実験数は候補数以下にしてください")
    if config["proposal_workers"] > config["candidate_count"]:
        raise LoopError("提案ワーカー数は候補数以下にしてください")
    return config


def make_config(overrides=None):
    config = copy.deepcopy(DEFAULTS)
    config.update(overrides or {})
    return validate(config)
