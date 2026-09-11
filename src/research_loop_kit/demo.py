"""認証不要の動作実証用。AIによる推論を代替したとは扱わない。"""

CODE = '''import argparse
import json
import random
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--seed", type=int, required=True)
p.add_argument("--output", required=True)
a = p.parse_args()
rng = random.Random(a.seed)
x = rng.uniform(-5, 5)
baseline = x * x
for _ in range(8):
    x -= RATE * 2 * x
treatment = x * x
Path(a.output).write_text(json.dumps({"seed": a.seed, "baseline": baseline,
                                    "treatment": treatment}), encoding="utf-8")
'''

ANSWERS = {
    "topic": "二次関数の最小化（動作実証用）", "interest": "更新幅と収束の関係",
    "motivation": "ループの接続を確かめる", "prior_work": "解析解は0",
    "data": "seed固定の乱数による初期点", "method": "Python計算実験",
    "evaluation": "更新前と8回更新後の二乗誤差", "resources": "CPU、外部サービス不要",
    "constraints": "動作実証値を実研究の知見として使わない", "deliverable": "動作実証レポート",
}


def respond(job, state):
    kind, payload = job["kind"], job["payload"]
    if kind == "skill_design":
        return {"name": "demo-evidence-check", "description": "Check evidence fields in demo reviews.",
                "purpose": "デモの実測欠落を見落とさない", "trigger": "実測値を解釈する前", "non_goals": "研究結論の自動証明",
                "inputs": "baselineとtreatmentの辞書", "outputs": "妥当な数値かの判定", "procedure": "必須キーと有限値を確認。assetsは不要。",
                "risks": "ローカルの値検査のみ。外部操作なし", "validation": "正常数値はTrue、欠落と非有限値はFalse",
                "rollback": "skill-disableで有効化を解除する", "phases": ["review"],
                "resources": [{"path": p, "purpose": purpose} for p, purpose in [
                    ("SKILL.md", "入口"), ("references/evidence.md", "根拠"),
                    ("scripts/check.py", "値検査"), ("tests/test_check.py", "正常と欠落・非有限の検査")]],
                "references": [{"path": "references/evidence.md", "source": payload["candidate"]["evidence"],
                                "relevance": "実測と結論を分ける理由"}]}
    if kind == "skill_build":
        d = payload["design"]
        return {"files": {
            "SKILL.md": f"---\nname: {d['name']}\ndescription: Check evidence fields in demo reviews.\n---\n\n実測値を解釈する前に[根拠](references/evidence.md)を読む。scripts/check.pyのvalidで欠落・非有限値を確認する。研究上の支持判定は別にレビューする。\n",
            "references/evidence.md": f"# 根拠\n\n出典: {d['references'][0]['source']}\n\nデモの集計値は制御経路の動作実証であり、研究能力や統計的有意差の証拠ではない。\n",
            "scripts/check.py": "import math\n\ndef valid(value):\n    return all(type(value.get(k)) in (int, float) and math.isfinite(value[k]) for k in ('baseline', 'treatment'))\n",
            "tests/test_check.py": "import unittest\nfrom scripts.check import valid\n\nclass CheckTests(unittest.TestCase):\n    def test_values(self):\n        self.assertTrue(valid({'baseline': 2, 'treatment': 1}))\n    def test_missing(self):\n        self.assertFalse(valid({'baseline': 2}))\n    def test_nonfinite(self):\n        self.assertFalse(valid({'baseline': 2, 'treatment': float('nan')}))\n"}}
    if kind == "deepen":
        return {"understanding": "二次関数で制御経路を動作実証する。AI研究能力の評価ではない。",
                "questions": [{"id": f"q{i+1}", "question": f"動作実証の条件{i+1}：更新幅、停止回数、比較条件をどのように固定しますか？"}
                              for i in range(state["config"]["deep_questions"])]}
    if kind == "ideas":
        return {"candidates": [{"title": f"更新幅候補{payload['offset']+i+1}",
                                "hypothesis": "適切な更新幅なら二乗誤差が減る", "rationale": "既知の解析解で実装経路を検証",
                                "method": "8回の勾配更新", "risk": "この例から未知の研究成果は主張できない"}
                               for i in range(payload["count"])]}
    if kind == "plan":
        return {"direction": "既知の二次関数で対話から報告までを動作実証する。",
                "experiments": [{"candidate_id": c["id"], "title": c["title"],
                                 "hypothesis": c["hypothesis"], "method": f"更新幅 {0.05*(i+1)}、8回更新",
                                 "baseline": "更新前", "treatment": "更新後", "metric": "二乗誤差（無次元）",
                                 "direction": "minimize", "min_effect": 0.001,
                                 "success_rule": "数値丸めより十分大きい差を確認する動作実証の閾値",
                                 "stop_rule": "8更新で終了", "limitations": "解析解が既知の例"}
                                for i, c in enumerate(payload["candidates"][:state["config"]["experiments_per_cycle"]])],
                "open_questions": []}
    if kind == "implement":
        index = int(payload["experiment"]["id"][1:])
        return {"files": {"experiment.py": CODE.replace("RATE", str(0.05 * index))},
                "notes": "標準ライブラリだけで計算する動作実証実装"}
    if kind == "review":
        return {"experiments": [{"id": x["id"], "assessment": "supported" if x.get("threshold_met") else "inconclusive",
                                 "interpretation": "実測集計の記述的な差を確認した。研究上の新規性は評価していない。",
                                 "limitations": "既知関数の動作実証。統計的有意差の検定なし。"}
                                for x in payload["results"]],
                "next_questions": ["更新幅を変えたとき収束の傾向が維持されるか"],
                "reusable_lessons": ["これは制御経路の実行確認であり、AIの研究能力の検証ではない"]}
    raise ValueError(kind)
