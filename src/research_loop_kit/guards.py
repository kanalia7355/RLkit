"""lab_exの検証観点を、分野に依存しない実測・成果物契約へ適用する。"""

import ast
import hashlib
import statistics

from .config import LoopError, number, read_json
from .store import digest


def inspect_code(sources):
    """静的な注意事項。動的な配線や研究の正しさを保証する検査ではない。"""
    findings = []
    for filename, source in sources.items():
        tree = ast.parse(source, filename=filename)
        loaded = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = {a.arg for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs}
                used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
                for arg in sorted((args & {"config", "cfg", "params"}) - used):
                    findings.append(f"{filename}:{node.lineno}: 設定引数 {arg} が参照されていない")
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                if name in {"open", "read_text", "write_text"} and not any(k.arg == "encoding" for k in node.keywords):
                    mode = next((k.value for k in node.keywords if k.arg == "mode"), None)
                    if mode is None and name == "open":
                        index = 1 if isinstance(node.func, ast.Name) else 0
                        mode = node.args[index] if len(node.args) > index else None
                    binary = isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value
                    if not binary:
                        findings.append(f"{filename}:{node.lineno}: テキスト入出力のencodingを確認")
        # 外部利用・コールバックもあり得るため停止条件にしない。
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name not in loaded:
                findings.append(f"{filename}:{node.lineno}: {node.name} の同一ファイル内参照なし（外部利用を確認）")
    return {"status": "warning" if findings else "no_static_findings", "findings": findings,
            "limits": "ASTの注意喚起のみ。動的配線・パラメータ効果・ハードコード不存在は未検証"}


def verify_evidence(root, entry):
    """保存された数値を再読込し、集計・コード・事前登録と照合する。"""
    checked = []
    for result in entry["results"]:
        if result["status"] == "failed":
            if result.get("threshold_met") or not result.get("error"):
                raise LoopError("失敗結果の記録が不正です")
            checked.append({"id": result["id"], "status": "failed_recorded"})
            continue
        directory = (root / result["evidence"]).resolve()
        if not directory.is_relative_to(root.resolve()):
            raise LoopError("証跡パスが研究フォルダ外です")
        manifest = read_json(directory / "preregistration.json")
        if manifest != result["manifest"] or manifest["proposal_hash"] != entry["proposal_hash"]:
            raise LoopError("事前登録が集計・採用方針と一致しません")
        sources = {p.name: p.read_text(encoding="utf-8") for p in (directory / "code").glob("*.py")}
        if digest(sources) != manifest["code_hash"]:
            raise LoopError("事前登録後に実験コードが変更されています")
        values = result["values"]
        if [v["seed"] for v in values] != manifest["seeds"] or len(values) != result["n"]:
            raise LoopError("seed一覧と集計件数が一致しません")
        for value in values:
            run_dir = directory / f"seed-{value['seed']}"
            measured = read_json(run_dir / "metrics.json")
            expected = {key: value[key] for key in ("seed", "baseline", "treatment")}
            if measured != expected:
                raise LoopError("保存された測定値と報告対象が一致しません")
            number(measured["baseline"], "baseline")
            number(measured["treatment"], "treatment")
            for name in ("stdout.log", "stderr.log"):
                if not (run_dir / name).is_file():
                    raise LoopError(f"実行ログがありません: {name}")
        spec = manifest["experiment"]
        sign = 1 if spec["direction"] == "maximize" else -1
        effects = [sign * (v["treatment"] - v["baseline"]) for v in values]
        expected = {"baseline_mean": statistics.mean(v["baseline"] for v in values),
                    "treatment_mean": statistics.mean(v["treatment"] for v in values),
                    "effect_mean": statistics.mean(effects),
                    "effect_std": statistics.stdev(effects) if len(effects) > 1 else None,
                    "threshold_met": statistics.mean(effects) >= spec["min_effect"]}
        if any(result[key] != value for key, value in expected.items()):
            raise LoopError("記述統計の再計算と集計値が一致しません")
        if read_json(directory / "analysis.json") != result:
            raise LoopError("保存された分析とレビュー対象が一致しません")
        checked.append({"id": result["id"], "status": "verified", "n": len(values)})
    return checked


def verify_reports(reports, documents):
    """存在だけでなく期待する本文との一致を検査しハッシュを残す。"""
    hashes = {}
    for name, expected in documents.items():
        path = reports / name
        if path.read_text(encoding="utf-8") != expected:
            raise LoopError(f"成果物の保存・本文検査に失敗しました: {name}")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes
