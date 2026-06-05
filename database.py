import sqlite3
import os
import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)
DB_PATH = "bot.db"


class Database:
    def __init__(self):
        self.path = DB_PATH

    async def _init(self):
        conn = sqlite3.connect(self.path)
        c = conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id     INTEGER PRIMARY KEY,
                username        TEXT DEFAULT '',
                wb_token        TEXT DEFAULT '',
                plan            TEXT DEFAULT 'trial',
                tokens_left     INTEGER DEFAULT 10,
                tokens_total    INTEGER DEFAULT 10,
                sub_expires     TEXT,
                notified_expiry INTEGER DEFAULT 0,
                is_active       INTEGER DEFAULT 1,
                created_at      TEXT DEFAULT (datetime('now'))
            );
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

    async def get_user(self, telegram_id: int):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
            return dict(row) if row else None

    async def create_user(self, telegram_id: int, username: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?,?)",
                (telegram_id, username)
            )
            conn.commit()

    async def save_wb_token(self, telegram_id: int, token: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO users (telegram_id, wb_token) VALUES (?,?) ON CONFLICT(telegram_id) DO UPDATE SET wb_token=?",
                (telegram_id, token, token)
            )
            conn.commit()

    async def activate_plan(self, telegram_id: int, plan: str, tokens: int, days: int):
        expires = (datetime.now() + timedelta(days=days)).isoformat()
        with self._conn() as conn:
            conn.execute(
                """UPDATE users SET plan=?, tokens_left=?, tokens_total=?,
                   sub_expires=?, notified_expiry=0, is_active=1 WHERE telegram_id=?""",
                (plan, tokens, tokens, expires, telegram_id)
            )
            conn.commit()

    async def use_token(self, telegram_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT tokens_left, sub_expires, plan FROM users WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()
            if not row:
                return False
            if row["sub_expires"] and row["plan"] != "trial":
                if datetime.now() > datetime.fromisoformat(row["sub_expires"]):
                    conn.execute("UPDATE users SET is_active=0, tokens_left=0 WHERE telegram_id=?", (telegram_id,))
                    conn.commit()
                    return False
            if row["tokens_left"] <= 0:
                return False
            conn.execute("UPDATE users SET tokens_left=tokens_left-1 WHERE telegram_id=?", (telegram_id,))
            conn.commit()
            return True

    async def get_users_with_token(self):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT telegram_id, wb_token, tokens_left FROM users WHERE wb_token != '' AND tokens_left > 0"
            ).fetchall()
            return [dict(r) for r in rows]

    async def get_users_expiring_soon(self):
        tomorrow = (datetime.now() + timedelta(days=1)).isoformat()
        now = datetime.now().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT telegram_id FROM users
                   WHERE sub_expires BETWEEN ? AND ?
                   AND notified_expiry=0 AND plan != 'trial'""",
                (now, tomorrow)
            ).fetchall()
            return [r["telegram_id"] for r in rows]

    async def mark_expiry_notified(self, telegram_id: int):
        with self._conn() as conn:
            conn.execute("UPDATE users SET notified_expiry=1 WHERE telegram_id=?", (telegram_id,))
            conn.commit()

    async def _is_replied(self, feedback_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM replies WHERE feedback_id=?", (feedback_id,)).fetchone()
            return row is not None

    async def _log_reply(self, telegram_id, feedback_id, rating, reply):
        with self._conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO replies (telegram_id,feedback_id,rating,reply) VALUES (?,?,?,?)",
                    (telegram_id, feedback_id, rating, reply)
                )
                conn.commit()
            except Exception:
                pass

    async def _get_count(self, telegram_id):
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) as n FROM replies WHERE telegram_id=?", (telegram_id,)
            ).fetchone()["n"]

    async def _get_history(self, telegram_id, limit=5):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM replies WHERE telegram_id=? ORDER BY created_at DESC LIMIT ?",
                (telegram_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
