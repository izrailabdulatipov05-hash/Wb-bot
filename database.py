import os
import logging
from datetime import date
import asyncpg

logger = logging.getLogger(__name__)

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))
    return _pool


class Database:
    def __init__(self):
        pass

    async def init(self):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id   BIGINT PRIMARY KEY,
                    username      TEXT DEFAULT '',
                    wb_token      TEXT DEFAULT '',
                    plan          TEXT DEFAULT 'test',
                    review_limit  INTEGER DEFAULT 9999,
                    created_at    TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS replies (
                    id            SERIAL PRIMARY KEY,
                    telegram_id   BIGINT,
                    feedback_id   TEXT,
                    rating        INTEGER,
                    reply         TEXT,
                    created_at    TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_replies_user ON replies(telegram_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_replies_feedback ON replies(feedback_id)
            """)
        logger.info("Database initialized")

    async def get_user(self, telegram_id: int):
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
            return dict(row) if row else None

    async def create_user(self, telegram_id: int, username: str):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (telegram_id, username) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                telegram_id, username
            )

    async def save_wb_token(self, telegram_id: int, token: str):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET wb_token=$1 WHERE telegram_id=$2",
                token, telegram_id
            )

    async def get_users_with_token(self):
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT telegram_id, wb_token FROM users WHERE wb_token != '' AND wb_token IS NOT NULL"
            )
            return [dict(r) for r in rows]

    async def log_reply(self, telegram_id: int, feedback_id: str, rating: int, reply: str):
        pool = await get_pool()
        async with pool.acquire() as conn:
            exists = await conn.fetchrow("SELECT 1 FROM replies WHERE feedback_id=$1", feedback_id)
            if exists:
                return False
            await conn.execute(
                "INSERT INTO replies (telegram_id, feedback_id, rating, reply) VALUES ($1,$2,$3,$4)",
                telegram_id, feedback_id, rating, reply
            )
            return True

    async def get_stats(self, telegram_id: int) -> dict:
        today_str = date.today().isoformat()
        month_str = date.today().strftime("%Y-%m")
        pool = await get_pool()
        async with pool.acquire() as conn:
            today = await conn.fetchval(
                "SELECT COUNT(*) FROM replies WHERE telegram_id=$1 AND created_at::date = $2::date",
                telegram_id, today_str
            )
            month = await conn.fetchval(
                "SELECT COUNT(*) FROM replies WHERE telegram_id=$1 AND TO_CHAR(created_at,'YYYY-MM')=$2",
                telegram_id, month_str
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM replies WHERE telegram_id=$1", telegram_id
            )
        return {"today": today or 0, "month": month or 0, "total": total or 0}

    async def get_history(self, telegram_id: int, limit: int = 5):
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM replies WHERE telegram_id=$1 ORDER BY created_at DESC LIMIT $2",
                telegram_id, limit
            )
            return [dict(r) for r in rows]
