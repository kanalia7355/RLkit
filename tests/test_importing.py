"""既存研究の取り込みをセッション入口と実験ループから検証する。"""

import hashlib
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_loop_kit.config import LoopError
from research_loop_kit.demo import ANSWERS
from research_loop_kit.engine import Engine
from research_loop_kit.importing import preview
from research_loop_kit.sessions import Sessions
from research_loop_kit.agent_entry import main as agent_main


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.clone = self.base / "kit"
        self.clone.mkdir()
        self.source = self.base / "existing"
        self.source.mkdir()
        (self.source / "report.md").write_text("# 既存研究\n前回の結果は未再検証。\n", encoding="utf-8")
        (self.source / "experiment.py").write_text("raise RuntimeError('must not run on import')\n", encoding="utf-8")
        (self.source / "data.bin").write_bytes(bytes(range(256)))
        self.paths = ["report.md", "experiment.py", "data.bin"]
        self.hub = Sessions(self.clone)
        self.session = self.hub.open()["session_id"]
        self.context = {"summary": "既存の実験と結果から次の比較を検討する", "answers": {"topic": "既存研究の継続"}}

    def import_study(self, **kwargs):
        return self.hub.import_study(self.session, self.source, self.paths, preview(self.source, self.paths)["hash"],
                                     "継続研究", kwargs.get("context", self.context), kwargs.get("settings"))

    def test_snapshot_preserves_originals_and_never_runs_source(self):
        before = {p: (self.source / p).read_bytes() for p in self.paths}
        selection = self.import_study()
        root = self.clone / selection["path"]
        state = Engine(root).status()
        self.assertEqual(state["runs"], 0)
        self.assertFalse(state["authorized"])
        self.assertEqual(state["history"], [])
        self.assertEqual(state["phase"], "interview")
        for path, data in before.items():
            self.assertEqual((self.source / path).read_bytes(), data)
            self.assertEqual((root / "imports/source" / path).read_bytes(), data)
        self.assertTrue((root / "reports/IMPORT_REPORT.md").exists())
        self.assertNotIn("topic", Engine(root).questions())
        self.assertIn("interest", Engine(root).questions())
        self.assertEqual(self.hub.menu()["projects"][0]["id"], selection["project_id"])

    def test_changed_preview_refused_without_creating_study(self):
        inspection = preview(self.source, self.paths)
        (self.source / "report.md").write_text("更新済み", encoding="utf-8")
        with self.assertRaises(LoopError):
            self.hub.import_study(self.session, self.source, self.paths, inspection["hash"], "継続研究", self.context)
        self.assertEqual(self.hub.catalog(), [])

    def test_copy_failure_does_not_publish_partial_study(self):
        with patch("research_loop_kit.sessions.copy_snapshot", side_effect=OSError("コピー中断")):
            with self.assertRaises(OSError):
                self.import_study()
        self.assertEqual(self.hub.catalog(), [])
        self.import_study()
        self.assertEqual(len(self.hub.catalog()), 1)

    def test_invalid_paths_and_private_state_are_rejected(self):
        for path in ("../outside.md", "/absolute.md", "a/../report.md", "a\\report.md", ".env",
                     ".rlk/state.sqlite3", ".git/config", ".claude/settings.json", "private.key"):
            with self.subTest(path=path), self.assertRaises((LoopError, OSError)):
                preview(self.source, [path])

    def test_size_limit_and_duplicate_selection(self):
        with patch("research_loop_kit.importing.MAX_BYTES", 1):
            with self.assertRaises(LoopError):
                preview(self.source, self.paths)
        with self.assertRaises(LoopError):
            preview(self.source, ["report.md", "report.md"])

    def test_existing_selected_session_cannot_import_another_study(self):
        self.import_study()
        with self.assertRaises(LoopError):
            self.import_study()
        self.assertEqual(len(self.hub.catalog()), 1)

    def test_import_context_reaches_next_proposal_and_real_execution(self):
        selection = self.import_study(context={"summary": "前回は更新幅を比較済み。次は頑健性を調べる。", "answers": ANSWERS},
                                      settings={"backend": "demo", "seeds": [1], "experiments_per_cycle": 1})
        root = self.clone / selection["path"]
        engine = Engine(root)
        engine.deepen()
        engine.run()
        deep = next(j for j in engine.status()["jobs"] if j["kind"] == "deepen")
        prompt = (engine.ticket_dir(deep) / "prompt.md").read_text(encoding="utf-8")
        self.assertIn("前回は更新幅を比較済み", prompt)
        self.assertIn("imports/source/experiment.py", prompt)
        engine.answer({q: "既存資料と比較条件を確認済み" for q in engine.questions()})
        engine.propose()
        engine.run()
        self.assertEqual(engine.status()["phase"], "approval")
        self.assertEqual(engine.status()["runs"], 0)
        engine.accept(engine.status()["proposal_hash"])
        engine.run()
        self.assertEqual(engine.status()["phase"], "complete")
        self.assertEqual(engine.status()["runs"], 1)

    def test_agent_entry_import_commands(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(agent_main(self.clone, ['import-preview', '--source', str(self.source), '--files', *self.paths]), 0)
        inspection = json.loads(output.getvalue())
        context = self.base / 'context.json'
        context.write_text(json.dumps(self.context), encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = agent_main(self.clone, ['import-study', self.session, '--source', str(self.source), '--files', *self.paths,
                '--hash', inspection['hash'], '--name', '既存研究', '--context', str(context)])
        self.assertEqual(code, 0)
        selected = json.loads(output.getvalue())
        self.assertEqual(self.hub.target(self.session, 'status'), self.clone / selected['path'])


if __name__ == "__main__":
    unittest.main()
