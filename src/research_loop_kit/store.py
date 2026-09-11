"""SQLiteで状態・ジョブ・試行を一緒に確定する。"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .config import LoopError, dump


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def write_new(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / ".rlk" / "state.sqlite3"

    @contextmanager
    def transaction(self):
        if not self.path.exists():
            raise LoopError("未初期化です。rlk init を実行してください")
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

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
            """)
            db.execute("INSERT INTO state VALUES (1, ?)", (dump(state),))

    @staticmethod
    def state(db):
        return json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])

    @staticmethod
    def save(db, state):
        db.execute("UPDATE state SET body=? WHERE id=1", (dump(state),))

    @staticmethod
    def event(db, kind, body):
        db.execute("INSERT INTO events(time,kind,body) VALUES (?,?,?)", (time.time(), kind, dump(body)))

    @staticmethod
    def job(db, cycle, kind, payload):
        return db.execute("INSERT INTO jobs(cycle,kind,payload) VALUES (?,?,?)",
                          (cycle, kind, dump(payload))).lastrowid

    @staticmethod
    def jobs(db, cycle=None):
        if cycle is None:
            rows = db.execute("SELECT * FROM jobs ORDER BY id")
        else:
            rows = db.execute("SELECT * FROM jobs WHERE cycle=? ORDER BY id", (cycle,))
        return [dict(row, payload=json.loads(row["payload"]),
                     result=json.loads(row["result"]) if row["result"] else None) for row in rows]
