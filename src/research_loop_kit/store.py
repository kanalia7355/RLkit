"""SQLiteで状態・ジョブ・試行を一緒に確定する。"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

from .config import LoopError, dump, upgrade


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


# DBに別行で持ち、stateの本文へは保存しない派生項目。
DERIVED_KEYS = ("history", "jobs", "failed_attempts", "diagnostics")


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / ".rlk" / "state.sqlite3"
        self._migrated = False

    @contextmanager
    def transaction(self, rollback=None):
        if not self.path.exists():
            raise LoopError("未初期化です。rlk init を実行してください")
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            if not self._migrated:
                self._migrate(db)
            yield db
            db.commit()
            self._migrated = True
        except BaseException:
            try:
                # ファイルを戻すまでDBの書き込みロックを保持する。
                # 同時submitに、巻き戻す途中のsrcを参照させない。
                if rollback is not None:
                    rollback.__exit__(*sys.exc_info())
            finally:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _migrate(db):
        """旧版のDB（historyをstate本文に保持）を、サイクル別の行へ移す。"""
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='state'").fetchone():
            return  # initialize中
        db.execute("CREATE TABLE IF NOT EXISTS history (cycle INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        row = db.execute("SELECT body FROM state WHERE id=1").fetchone()
        if row is None:
            return
        body = json.loads(row[0])
        if "history" not in body:
            return
        for entry in body.pop("history"):
            db.execute("INSERT OR REPLACE INTO history VALUES (?,?)", (entry["cycle"], dump(entry)))
        db.execute("UPDATE state SET body=? WHERE id=1", (dump(body),))

    def initialize(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("xb"):
            pass
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE jobs (id INTEGER PRIMARY KEY, cycle INTEGER NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    attempt INTEGER NOT NULL DEFAULT 0, token TEXT, started REAL,
                    result TEXT, error TEXT);
                CREATE TABLE events (id INTEGER PRIMARY KEY, time REAL, kind TEXT, body TEXT);
                CREATE TABLE attempts (job INTEGER, attempt INTEGER, token TEXT, status TEXT,
                    body TEXT, PRIMARY KEY(job, attempt));
                CREATE TABLE IF NOT EXISTS history (cycle INTEGER PRIMARY KEY, body TEXT NOT NULL);
            """)
            db.execute("INSERT INTO state VALUES (1, ?)", (dump(strip_derived(state)),))

    @staticmethod
    def state(db):
        """state本文。履歴は含まない（必要なら history(db) を使う）。"""
        state = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
        state["config"] = upgrade(state["config"])
        return state

    @staticmethod
    def save(db, state):
        db.execute("UPDATE state SET body=? WHERE id=1", (dump(strip_derived(state)),))

    @staticmethod
    def history(db):
        return [json.loads(body) for (body,) in db.execute("SELECT body FROM history ORDER BY cycle")]

    @staticmethod
    def add_history(db, entry):
        db.execute("INSERT INTO history VALUES (?,?)", (entry["cycle"], dump(entry)))

    @staticmethod
    def event(db, kind, body):
        db.execute("INSERT INTO events(time,kind,body) VALUES (?,?,?)", (time.time(), kind, dump(body)))

    @staticmethod
    def job(db, cycle, kind, payload):
        return db.execute("INSERT INTO jobs(cycle,kind,payload) VALUES (?,?,?)", (cycle, kind, dump(payload))).lastrowid

    @staticmethod
    def jobs(db, cycle=None, statuses=None):
        query, args = "SELECT * FROM jobs", []
        conditions = []
        if cycle is not None:
            conditions.append("cycle=?")
            args.append(cycle)
        if statuses:
            conditions.append(f"status IN ({','.join('?' * len(statuses))})")
            args += list(statuses)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        rows = db.execute(query + " ORDER BY id", args)
        return [
            dict(row, payload=json.loads(row["payload"]), result=json.loads(row["result"]) if row["result"] else None)
            for row in rows
        ]


def strip_derived(state):
    return {key: value for key, value in state.items() if key not in DERIVED_KEYS}
