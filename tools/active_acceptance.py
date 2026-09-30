"""この開発セッションのAgentが作成した2題材の作業回答を再実行する。

backend=activeで作業票を取得し、保存した回答をsubmitする受け入れ検証。
認証済み外部CLIや未知課題での独立したAgent性能測定ではない。
"""

import argparse
import csv
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit.config import dump
from research_loop_kit.engine import Engine
from research_loop_kit.sessions import Sessions
from research_loop_kit.store import digest

COMPUTE = """import math
import random


def compare(seed, steps, stop=None):
    alpha = random.Random(seed).uniform(0.5, 1.5)
    truth = math.expm1(alpha) / alpha
    baseline = treatment = 0.0
    for i in range(steps):
        left, right = math.exp(alpha * i / steps), math.exp(alpha * (i + 1) / steps)
        baseline += left / steps
        treatment += (left + right) / (2 * steps)
        if stop is not None and stop.step(abs(treatment - truth)):
            break
    return abs(baseline - truth), abs(treatment - truth)
"""

CSV_CODE = """import random


def compare(rows, seed, stop=None):
    order = list(rows)
    random.Random(seed).shuffle(order)
    train, test = order[:30], order[30:]
    mx = sum(x for x,y in train) / len(train)
    my = sum(y for x,y in train) / len(train)
    slope = sum((x-mx)*(y-my) for x,y in train) / sum((x-mx)**2 for x,y in train)
    intercept = my - slope * mx
    baseline = treatment = 0.0
    n = 0
    for x,y in test:
        baseline += (my-y)**2
        treatment += (intercept+slope*x-y)**2
        n += 1
        if stop is not None and stop.step(treatment/n):
            break
    return baseline/n, treatment/n
"""

COMPUTE_TEST = """import math
import random
import unittest
from research.methods import compare

class Tests(unittest.TestCase):
    def test_analytic_one_interval(self):
        a = random.Random(999).uniform(0.5,1.5)
        exact = math.expm1(a)/a
        b,t = compare(999,1)
        self.assertAlmostEqual(b, abs(1-exact))
        self.assertAlmostEqual(t, abs((1+math.exp(a))/2-exact))
    def test_refinement(self):
        _,coarse = compare(999,8)
        _,fine = compare(999,16)
        self.assertLess(fine,coarse/3)
    def test_seed_repeatability(self):
        self.assertEqual(compare(999,32), compare(999,32))
"""

CSV_TEST = """import unittest
from research.methods import compare

class Tests(unittest.TestCase):
    def test_exact_affine_relation(self):
        b,t = compare([(float(i),3+2*float(i)) for i in range(40)],999)
        self.assertGreater(b,0)
        self.assertAlmostEqual(t,0)
    def test_seed_repeatability(self):
        rows = [(float(i),3+2*float(i)) for i in range(40)]
        self.assertEqual(compare(rows,998), compare(rows,998))
    def test_test_target_does_not_fit_model(self):
        import random
        rows = [(float(i),3+2*float(i)) for i in range(40)]
        indices = list(range(40))
        random.Random(999).shuffle(indices)
        for i in indices[30:]:
            rows[i] = (rows[i][0], rows[i][1]+10)
        _,t = compare(rows,999)
        self.assertAlmostEqual(t,100)
"""

ENTRY = """import argparse
import json
from pathlib import Path
from rlk_stop import StopController
from research.methods import compare
{imports}
p = argparse.ArgumentParser()
p.add_argument("--seed",type=int,required=True)
p.add_argument("--output",required=True)
a = p.parse_args()
{data}
b,t = {call}
Path(a.output).write_text(json.dumps({{"seed":a.seed,"baseline":b,"treatment":t}}),encoding="utf-8")
"""


def run_case(hub, name, *, csv_case=False):
    menu = hub.open()
    selected = hub.select(
        menu["session_id"],
        "new",
        name=name,
        settings={
            "backend": "active",
            "candidate_count": 2,
            "proposal_workers": 1,
            "experiments_per_cycle": 1,
            "deep_questions": 1,
            "seeds": [11, 22, 33],
            "data_files": ["data/observations.csv"] if csv_case else [],
        },
    )
    engine = Engine(hub.root / selected["path"])
    if csv_case:
        path = engine.root / "data/observations.csv"
        path.parent.mkdir()
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["x", "y"])
            for i in range(40):
                x = -2 + i / 10
                writer.writerow([x, 3 + 2 * x + 0.03 * math.sin(i)])
    answers = {
        "topic": "CSVの線形回帰" if csv_case else "数値積分の精度",
        "interest": "訓練用データだけで推定した回帰の評価" if csv_case else "同じ区間数での積分誤差",
        "motivation": "新しい題材で入口と証跡の接続を検証する",
        "prior_work": "既知の数学的性質を利用。外部論文は未調査",
        "data": "40行の生成CSV。実データへの一般化は検証しない" if csv_case else "seedで指数関数の係数を生成",
        "method": "30行訓練・10行評価の分割" if csv_case else "32区間で左端則と台形則を比較",
        "evaluation": "評価データのMSE" if csv_case else "解析的積分値からの絶対誤差",
        "resources": "CPUと標準ライブラリ",
        "constraints": "ネットワーク不要、合成データだけ",
        "deliverable": "事前登録、実測、探索と確認を分けた報告",
    }
    engine.answer(answers)
    transcript = []

    def submit(response, expected):
        job = engine.claim({expected})
        if not job:
            raise RuntimeError(f"作業票を取得できません: {expected}")
        engine.ticket(job)
        directory = engine.ticket_dir(job)
        (directory / "acceptance-response.json").write_text(dump(response), encoding="utf-8")
        engine.submit(job["id"], job["token"], response)
        transcript.append({"id": job["id"], "kind": expected, "response_hash": digest(response)})

    engine.deepen()
    submit(
        {"understanding": answers["method"], "questions": [{"id": "q1", "question": "比較予算と分割を固定しますか？"}]},
        "deepen",
    )
    engine.answer({"q1": "固定する。探索と確認は別seedで行う"})
    engine.propose()
    submit(
        {
            "candidates": [
                {
                    "title": title,
                    "hypothesis": "固定比較条件で誤差が減る",
                    "rationale": "既知の解析・回帰条件",
                    "method": answers["method"],
                    "risk": "合成条件への限定",
                }
                for title in (name, "反例・境界条件を調べる")
            ]
        },
        "ideas",
    )
    plan = {
        "direction": name + "を同一予算で比較する",
        "experiments": [
            {
                "candidate_id": "c1",
                "title": name,
                "hypothesis": "誤差を減らせる",
                "method": answers["method"],
                "baseline": "訓練平均による定数予測" if csv_case else "左端リーマン和",
                "treatment": "切片付き最小二乗回帰" if csv_case else "台形則",
                "metric": answers["evaluation"],
                "direction": "minimize",
                "min_effect": 0.001,
                "success_rule": "既知の合成例で丸め誤差より大きい改善を記述的に確認",
                "stop_rule": "評価10行を走査" if csv_case else "32区間を走査",
                "stop_policy": {"kind": "fixed_iterations", "max_iterations": 10 if csv_case else 32},
                "limitations": "未知のデータや関数へ一般化しない",
                "reference_ids": ["r1"],
            }
        ],
        "references": [
            {
                "id": "r1",
                "source": "このセッションで確認した解析式・正規方程式",
                "claim": "対照と介入の定義",
                "relevance": "テストの独立した期待値",
                "status": "read",
                "locator": "切片my-slope*mx" if csv_case else "expm1(alpha)/alpha",
                "note": "数式から境界条件の期待値を導出した。外部資料の照合は未実施",
            }
        ],
        "open_questions": [],
    }
    submit(plan, "plan")
    engine.accept(engine.status()["proposal_hash"])
    code = ENTRY.format(
        imports="import csv\nimport os" if csv_case else "",
        data='with (Path(os.environ["RLK_INPUT_DIR"])/"data/observations.csv").open(encoding="utf-8",newline="") as f:\n    rows = [(float(r["x"]),float(r["y"])) for r in csv.DictReader(f)]'
        if csv_case
        else "",
        call="compare(rows,a.seed,StopController.from_environment())"
        if csv_case
        else "compare(a.seed,32,StopController.from_environment())",
    )
    submit(
        {
            "files": {"experiment.py": code},
            "shared_files": {"research/methods.py": CSV_CODE if csv_case else COMPUTE},
            "notes": "標準ライブラリで計算。停止記録は実際の走査指標に接続。",
        },
        "implement",
    )
    submit(
        {
            "decision": "approved",
            "summary": "独立した数式・境界条件・分割に基づくテストを実行",
            "checks": {
                key: {
                    "status": "not_applicable" if key == "data_split" and not csv_case else "passed",
                    "evidence": answers["method"] + "をresearch.methods.compareと照合",
                }
                for key in ("metric", "baseline", "treatment", "data_split", "seed")
            },
            "tests": {"test_contract.py": CSV_TEST if csv_case else COMPUTE_TEST},
        },
        "implementation_review",
    )
    engine.run(experiments_only=True)

    def review():
        results = engine.status()["jobs"][-1]["payload"]["results"]
        submit(
            {
                "experiments": [
                    {
                        "id": r["id"],
                        "assessment": "supported" if r["threshold_met"] else "inconclusive",
                        "interpretation": "提供された実測に限定した記述的改善。統計検定未実施。",
                        "limitations": "合成条件のみ。同じAgentによる実装・レビュー。",
                    }
                    for r in results
                ],
                "next_questions": ["異なる生成条件で成立するか"],
                "reusable_lessons": ["固定条件と証跡を分けて検証する"],
            },
            "review",
        )

    review()
    source = engine.status()["history"][0]["results"][0]
    engine.confirm(1, "e1", digest(source), [101, 102, 103])
    engine.run(experiments_only=True)
    review()
    engine.export()
    summary = {
        "case": name,
        "backend": "active",
        "handoffs": transcript,
        "runs": engine.status()["runs"],
        "manual_interventions": 0,
        "unexpected_stalls": 0,
        "implementation_errors": [],
        "results": [
            {
                "stage": r["manifest"]["stage"],
                "n": r["n"],
                "baseline_mean": r["baseline_mean"],
                "treatment_mean": r["treatment_mean"],
                "effect_mean": r["effect_mean"],
                "claim": h["claim_status"][r["id"]],
            }
            for h in engine.status()["history"]
            for r in h["results"]
        ],
        "project": selected["path"],
    }
    (engine.root / "acceptance.json").write_text(dump(summary), encoding="utf-8")
    return summary


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    hub = Sessions(root)
    results = [run_case(hub, "指数関数の数値積分"), run_case(hub, "CSVの線形回帰", csv_case=True)]
    (root / "acceptance-summary.json").write_text(dump(results), encoding="utf-8")
    print(dump(results))


if __name__ == "__main__":
    main()
