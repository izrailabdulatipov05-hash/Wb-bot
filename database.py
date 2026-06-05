import os
import logging
import asyncpg
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)
_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        db_url = os.getenv("DATABASE_URL", "")
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        _pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    return _pool


class Database:
    async def _init(self):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id     BIGINT PRIMARY KEY,
                    username        TEXT DEFAULT '',
                    wb_token        TEXT DEFAULT '',
                    plan            TEXT DEFAULT 'trial',
                    tokens_left     INTEGER DEFAULT 10,
                    tokens_total    INTEGER DEFAULT 10,
                    sub_expires     TIMESTAMP,
                    notified_expiry BOOLEAN DEFAULT FALSE,
                    is_active       BOOLEAN DEFAULT TRUE,
                    created_at      TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS replies (
                    id          SERIAL PRIMARY KEY,
                    telegram_id BIGINT,
                    feedback_id TEXT UNIQUE,
                    rating      INTEGER,
                    reply       TEXT,
                    created_at  TIMESTAMP DEFAULT NOW()
                )
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
                """INSERT INTO users (telegram_id, username, plan, tokens_left, tokens_total)
                   VALUES ($1,$2,'trial',10,10) ON CONFLICT DO NOTHING""",
                telegram_id, username
            )

    async def save_wb_token(self, telegram_id: int, token: str):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO users (telegram_id, wb_token) VALUES ($1,$2)
                   ON CONFLICT (telegram_id) DO UPDATE SET wb_token=$2""",
                telegram_id, token
            )

    async def activate_plan(self, telegram_id: int, plan: str, tokens: int, days: int):
        """Активирует подписку пользователю"""
        expires = datetime.now() + timedelta(days=days)
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE users SET plan=$2, tokens_left=$3, tokens_total=$3,
                   sub_expires=$4, notified_expiry=FALSE, is_active=TRUE
                   WHERE telegram_id=$1""",
                telegram_id, plan, tokens, expires
            )

    async def use_token(self, telegram_id: int) -> bool:
        """Списывает 1 токен. Возвращает False если токенов нет"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tokens_left, sub_expires, plan FROM users WHERE telegram_id=$1",
                telegram_id
            )
            if not row:
                return False
            # Проверяем истечение подписки
            if row["sub_expires"] and datetime.now() > row["sub_expires"] and row["plan"] != "trial":
                await conn.execute(
                    "UPDATE users SET is_active=FALSE, tokens_left=0 WHERE telegram_id=$1",
                    telegram_id
                )
                return False
            if row["tokens_left"] <= 0:
                return False
            await conn.execute(
                "UPDATE users SET tokens_left=tokens_left-1 WHERE telegram_id=$1",
                telegram_id
            )
            return True

    async def get_users_with_token(self):
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT telegram_id, wb_token, tokens_left, sub_expires, plan
                   FROM users WHERE wb_token != '' AND tokens_left > 0"""
            )
            return [dict(r) for r in rows]

    async def get_users_expiring_soon(self):
        """Пользователи у которых подписка истекает завтра"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            tomorrow = datetime.now() + timedelta(days=1)
            rows = await conn.fetch(
                """SELECT telegram_id FROM users
                   WHERE sub_expires BETWEEN NOW() AND $1
                   AND notified_expiry=FALSE AND plan != 'trial'""",
                tomorrow
            )
            return [r["telegram_id"] for r in rows]

    async def mark_expiry_notified(self, telegram_id: int):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET notified_expiry=TRUE WHERE telegram_id=$1", telegram_id
            )

    async def _is_replied(self, feedback_id: str) -> bool:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 FROM replies WHERE feedback_id=$1", feedback_id)
            return row is not None

    async def _log_reply(self, telegram_id, feedback_id, rating, reply):
        pool = await get_pool()
        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO replies (telegram_id,feedback_id,rating,reply) VALUES ($1,$2,$3,$4)",
                    telegram_id, feedback_id, rating, reply
                )
            except Exception:
                pass

    async def _get_count(self, telegram_id):
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM replies WHERE telegram_id=$1", telegram_id
            ) or 0

    async def _get_history(self, telegram_id, limit=5):
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM replies WHERE telegram_id=$1 ORDER BY created_at DESC LIMIT $2",
                telegram_id, limit
            )
            return [dict(r) for r in rows]
