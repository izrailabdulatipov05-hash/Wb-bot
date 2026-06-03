import sqlite3
import os
import logging
from datetime import date

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        self.path = "bot.db"

    def init(self):
        conn = sqlite3.connect(self.path)
        c = conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS replies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                feedback_id TEXT UNIQUE,
                rating      INTEGER,
                reply       TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized")

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def is_replied(self, feedback_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM replies WHERE feedback_id=?", (feedback_id,)).fetchone()
            return row is not None

    def log_reply(self, telegram_id, feedback_id, rating, reply):
        with self._conn() as conn:
            try:
                conn.execute("INSERT INTO replies (telegram_id,feedback_id,rating,reply) VALUES (?,?,?,?)",
                           (telegram_id, feedback_id, rating, reply))
                conn.commit()
            except:
                pass

    def get_count(self, telegram_id):
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) as n FROM replies WHERE telegram_id=?",
                              (telegram_id,)).fetchone()["n"]

    def get_history(self, telegram_id, limit=5):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM replies WHERE telegram_id=? ORDER BY created_at DESC LIMIT ?",
                              (telegram_id, limit)).fetchall()
            return [dict(r) for r in rows]
