import sqlite3
import os
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "bot.db")


class Database:
    def __init__(self):
        self.path = DB_PATH

    def init(self):
        conn = sqlite3.connect(self.path)
        c = conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id   INTEGER PRIMARY KEY,
                username      TEXT DEFAULT '',
                wb_token      TEXT DEFAULT '',
                plan          TEXT DEFAULT 'test',
                review_limit  INTEGER DEFAULT 9999,
                created_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS replies (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id   INTEGER,
                feedback_id   TEXT,
                rating        INTEGER,
                reply         TEXT,
                created_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_replies_user ON replies(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_replies_feedback ON replies(feedback_id);
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized")

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_user(self, telegram_id: int):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
            return dict(row) if row else None

    def create_user(self, telegram_id: int, username: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?,?)",
                (telegram_id, username)
            )
            conn.commit()

    def save_wb_token(self, telegram_id: int, token: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET wb_token=? WHERE telegram_id=?",
                (token, telegram_id)
            )
            conn.commit()

    def get_users_with_token(self):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT telegram_id, wb_token FROM users WHERE wb_token != '' AND wb_token IS NOT NULL"
            ).fetchall()
            return [dict(r) for r in rows]

    def log_reply(self, telegram_id: int, feedback_id: str, rating: int, reply: str):
        # Проверяем что не отвечали на этот отзыв раньше
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM replies WHERE feedback_id=?", (feedback_id,)
            ).fetchone()
            if exists:
                return False
            conn.execute(
                "INSERT INTO replies (telegram_id, feedback_id, rating, reply) VALUES (?,?,?,?)",
                (telegram_id, feedback_id, rating, reply)
            )
            conn.commit()
            return True

    def is_already_replied(self, feedback_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM replies WHERE feedback_id=?", (feedback_id,)
            ).fetchone()
            return row is not None

    def get_stats(self, telegram_id: int) -> dict:
        today_str = date.today().isoformat()
        month_str = date.today().strftime("%Y-%m")
        with self._conn() as conn:
            today = conn.execute(
                "SELECT COUNT(*) as n FROM replies WHERE telegram_id=? AND created_at LIKE ?",
                (telegram_id, f"{today_str}%")
            ).fetchone()["n"]
            month = conn.execute(
                "SELECT COUNT(*) as n FROM replies WHERE telegram_id=? AND created_at LIKE ?",
                (telegram_id, f"{month_str}%")
            ).fetchone()["n"]
            total = conn.execute(
                "SELECT COUNT(*) as n FROM replies WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()["n"]
        return {"today": today, "month": month, "total": total}

    def get_history(self, telegram_id: int, limit: int = 5):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM replies WHERE telegram_id=? ORDER BY created_at DESC LIMIT ?",
                (telegram_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
