"""実装の実行前検証、実験入力の固定、研究の確認段階を扱う。"""

import ast
from importlib import metadata
from importlib.resources import files
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys

from .config import LoopError, dump, nonempty, read_json
from .fsutil import no_links, write_new
from .providers import process_run
from .shared_source import code_files, read_code
from .store import digest

CHECKS = ("metric", "baseline", "treatment", "data_split", "seed")


def relative_file(root, name):
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise LoopError("データは研究内の相対ファイルパスで指定してください")
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in ("", ".", "..") for p in name.split("/")):
        raise LoopError("データのパス逸脱は許可しません")
    if any(p.startswith(".") for p in path.parts) or path.parts[0] in ("src", "reports", "experiments"):
        raise LoopError("データはdata/やimports/配下に置き、コード・状態・認証情報を指定しないでください")
    if path.suffix.lower() in (".pem", ".key"):
        raise LoopError("認証用の鍵は実験入力に登録しません")
    target = root / name
    try:
        no_links(target, root)
    except FileNotFoundError as exc:
        raise LoopError(f"登録データがありません: {name}") from exc
    if not target.is_file():
        raise LoopError(f"通常のデータファイルが必要です: {name}")
    return target


def data_manifest(root, names):
    import hashlib

    result = []
    total = 0
    if len(names) != len(set(names)):
        raise LoopError("データファイルが重複しています")
    for name in sorted(names):
        path = relative_file(root, name)
        total += path.stat().st_size
        if total > 100 * 1024 * 1024:
            raise LoopError("実験入力の固定は合計100MiB以内です")
        sha = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                sha.update(chunk)
        result.append({"path": name, "bytes": size, "sha256": sha.hexdigest()})
    return result


def environment():
    return {
        "python": sys.version,
        "executable": sys.executable,
        "packages": sorted(
            [
                {"name": d.metadata["Name"], "version": d.version}
                for d in metadata.distributions()
                if d.metadata["Name"]
            ],
            key=lambda d: (d["name"].lower(), d["version"]),
        ),
        "variables": {
            k: os.environ[k] for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "CUDA_VISIBLE_DEVICES") if k in os.environ
        },
    }


def snapshot_inputs(root, directory, expected):
    names = [f["path"] for f in expected]
    if data_manifest(root, names) != expected:
        raise LoopError("実行前レビュー後に入力データが変更されています")
    directory.mkdir(parents=True, exist_ok=True)
    for record in expected:
        target = directory / record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(relative_file(root, record["path"]), target)
    if data_manifest(directory, names) != expected:
        raise LoopError("固定中に入力データが変更されています")
    return str(directory)


def validate_review(result):
    if result.get("decision") not in ("approved", "rejected"):
        raise LoopError("実行前レビューはapproved / rejectedで判定してください")
    nonempty(result.get("summary"), "実行前レビューの根拠")
    checks = result.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        raise LoopError("指標・対照・介入・データ分割・seedの確認が必要です")
    for key, check in checks.items():
        if not isinstance(check, dict) or check.get("status") not in ("passed", "failed", "not_applicable"):
            raise LoopError("各確認にはstatusとevidenceを指定してください")
        nonempty(check.get("evidence"), "計画とコードを照合した根拠")
        if result["decision"] == "approved" and (
            check["status"] == "failed" or (check["status"] == "not_applicable" and key != "data_split")
        ):
            raise LoopError("未確認・不一致の実装を実行できません")
    if result["decision"] == "approved":
        tests = result.get("tests")
        if not isinstance(tests, dict) or not tests or len(tests) > 20:
            raise LoopError("実行前レビューには動作テストが必要です")
        for name, code in tests.items():
            if not re.fullmatch(r"test_[a-zA-Z0-9_]+\.py", name):
                raise LoopError("検証テストはtest_*.pyファイルです")
            nonempty(code, "検証テスト")
            if len(code) > 200_000:
                raise LoopError("検証テストが大きすぎます")
            try:
                ast.parse(code, filename=name)
            except SyntaxError as exc:
                raise LoopError(f"検証テストの構文エラー: {exc}") from exc


def test_implementation(root, job, result, directory, timeout):
    sources = code_files(root, job["payload"]["implementation"])
    work = directory / "validation"
    for name, code in sources.items():
        write_new(work / name, code)
    for name, code in result["tests"].items():
        write_new(work / "tests" / name, code)
    inputs = snapshot_inputs(root, work / "inputs", job["payload"]["data_manifest"])
    process_run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        work,
        work / "stdout.log",
        work / "stderr.log",
        min(timeout, 60),
        env_overrides={"PYTHONPATH": os.pathsep.join([str(work), str(work / "src")]), "RLK_INPUT_DIR": inputs},
    )
    log = (work / "stderr.log").read_text(encoding="utf-8")
    match = re.search(r"Ran ([1-9][0-9]*) tests?", log)
    if not match or "\nOK" not in log or "skipped=" in log:
        raise LoopError("少なくとも1件の未skip検証テスト成功が必要です")
    policy = job["payload"]["experiment"].get("stop_policy")
    stop_check = None
    if policy:
        check = work / "stop-check"
        check.mkdir()
        seed = job["payload"].get("validation_seed", 0)
        process_run(
            [sys.executable, str(work / "experiment.py"), "--seed", str(seed), "--output", str(check / "metrics.json")],
            check,
            check / "stdout.log",
            check / "stderr.log",
            min(timeout, 60),
            env_overrides={
                "PYTHONPATH": str(work / "src"),
                "RLK_INPUT_DIR": inputs,
                "PYTHONDONTWRITEBYTECODE": "1",
                "RLK_STOP_POLICY": dump(policy),
                "RLK_STOP_RECORD": str(check / "termination.json"),
                "RLK_COMPARISON_POLICY": dump(job["payload"]["experiment"].get("comparison_policy")),
                "RLK_COMPARISON_RECORD": str(check / "comparison.json"),
            },
        )
        record = verify_stop(check / "termination.json", policy)
        stop_check = {"seed": seed, "record": record}
        comparison = job["payload"]["experiment"].get("comparison_policy")
        if comparison:
            stop_check["comparison"] = verify_comparison(
                check / "comparison.json", comparison, read_json(check / "metrics.json")
            )
    observed = read_code(work)
    expected = dict(sources, **{"tests/" + p: text for p, text in result["tests"].items()})
    if (
        observed != expected
        or data_manifest(work / "inputs", [f["path"] for f in job["payload"]["data_manifest"]])
        != job["payload"]["data_manifest"]
    ):
        raise LoopError("検証中にコード・テスト・入力データが変更されました")
    validation = {
        "stop_check": stop_check,
        "environment": environment(),
        "code_hash": digest(sources),
        "plan_hash": digest(job["payload"]["experiment"]),
        "tests_hash": digest(result["tests"]),
        "tests_passed": int(match[1]),
        "evidence": work.relative_to(root).as_posix(),
        "data_manifest": job["payload"]["data_manifest"],
    }
    write_new(work / "validation.json", dump(validation))
    return validation


def verify_validation(root, validation, sources, experiment):
    if validation["code_hash"] != digest(sources) or validation["plan_hash"] != digest(experiment):
        raise LoopError("実行前レビューと実行コード・計画が一致しません")
    directory = root / validation["evidence"]
    no_links(directory, root)
    if read_json(directory / "validation.json") != validation:
        raise LoopError("実行前検証の記録が変更されています")
    code = read_code(directory, root)
    tests = {p.removeprefix("tests/"): text for p, text in code.items() if p.startswith("tests/")}
    if (
        digest(tests) != validation["tests_hash"]
        or {p: text for p, text in code.items() if not p.startswith("tests/")} != sources
    ):
        raise LoopError("実行前検証のコード・テストが変更されています")
    if experiment.get("stop_policy"):
        check = validation.get("stop_check")
        if (
            not check
            or verify_stop(directory / "stop-check/termination.json", experiment["stop_policy"]) != check["record"]
        ):
            raise LoopError("停止条件の実行前検証記録が一致しません")
    if experiment.get("comparison_policy"):
        observed = verify_comparison(
            directory / "stop-check/comparison.json",
            experiment["comparison_policy"],
            read_json(directory / "stop-check/metrics.json"),
        )
        if observed != validation.get("stop_check", {}).get("comparison"):
            raise LoopError("比較予算の実行前検証が一致しません")
    for name in ("stdout.log", "stderr.log"):
        if not (directory / name).is_file():
            raise LoopError("実行前検証ログがありません")


def claim_stage(result):
    if result.get("status") != "measured":
        return "未確認（途中結果・失敗）"
    if result.get("manifest", {}).get("stage") == "confirmation":
        return "確認実験で閾値到達" if result.get("threshold_met") else "確認実験で未支持"
    return "探索段階（独立した確認実験は未実施）"


def stop_source():
    return files("research_loop_kit").joinpath("stopping.py").read_text(encoding="utf-8")


def verify_stop(path, policy):
    from .stopping import verify_record

    try:
        return verify_record(read_json(path), policy)
    except (OSError, ValueError, LoopError) as exc:
        raise LoopError(f"停止条件の検証に失敗しました: {exc}") from exc


def verify_comparison(path, policy, metrics=None):
    from .stopping import verify_comparison as verify

    try:
        record = verify(read_json(path), policy, metrics)
        termination = verify_stop(Path(path).parent / "termination.json", policy["treatment"]["stop_policy"])
        if record["conditions"]["treatment"]["stop"] != termination:
            raise LoopError("介入の比較記録とtermination.jsonが一致しません")
        return record
    except (LoopError, ValueError, OSError) as exc:
        raise LoopError(f"比較予算の検証に失敗しました: {exc}") from exc
