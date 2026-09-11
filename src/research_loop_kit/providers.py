"""各エージェントCLIはファイル応答の共通契約に接続する。"""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

from .config import LoopError, read_json


def command(config, kind):
    cfg = dict(config, **config["roles"].get(kind, {}))
    backend = cfg["backend"]
    args = {
        "codex": ["codex", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write"],
        "claude": ["claude", "-p"],
        "gemini": ["gemini", "-p"],
        "opencode": ["opencode", "run"],
        "custom": cfg["custom_command"],
    }.get(backend)
    if not args:
        raise LoopError(f"{backend} は外部CLIモードではありません")
    args = list(args)
    if cfg["model"]:
        args += ["--model", cfg["model"]]
    args += cfg["agent_args"]
    return args


def stop_tree(process):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def process_run(argv, cwd, stdout, stderr, timeout, env_overrides=None):
    """シェル解釈を使わず、タイムアウト時には子プロセスも停止する。"""
    executable = shutil.which(argv[0])
    if executable is None:
        raise LoopError(f"実行ファイルが見つかりません: {argv[0]}")
    # Windowsのnpm shimはnodeを直接使い、cmd.exeへのプロンプト補間を避ける。
    if os.name == "nt" and Path(executable).suffix.lower() in (".cmd", ".bat", ".ps1"):
        raise LoopError("Windowsのシェルshimは直接起動しません。custom_commandにnode.exeとCLIのJS入口を配列で設定するか、activeモードを使ってください")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.update(env_overrides or {})
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with Path(stdout).open("wb") as out, Path(stderr).open("wb") as err:
        process = subprocess.Popen([executable, *argv[1:]], cwd=cwd, stdout=out, stderr=err,
                                   stdin=subprocess.DEVNULL, env=env, shell=False, **options)
        try:
            result = process.wait(timeout=timeout)
        except BaseException:
            stop_tree(process)
            raise
    if result:
        raise LoopError(f"プロセス終了コード {result}。ログ: {stderr}")


def invoke(job, state, ticket_dir, timeout):
    cfg = dict(state["config"], **state["config"]["roles"].get(job["kind"], {}))
    if cfg["backend"] == "demo":
        from .demo import respond
        return respond(job, state)
    if cfg["backend"] == "active":
        raise LoopError("activeモードは現在のAgentで作業票を処理し、rlk submitで結果を登録してください")
    prompt_path = ticket_dir / "prompt.md"
    # 長い研究文をコマンドラインに埋め込まない。相対パスもshellへ渡さない。
    prompt = f"Read the UTF-8 task at {prompt_path.resolve()}. Follow it and write response.json to the specified absolute path."
    process_run(command(state["config"], job["kind"]) + [prompt], ticket_dir,
                ticket_dir / "agent.stdout.log", ticket_dir / "agent.stderr.log", timeout)
    return read_json(ticket_dir / "response.json")
