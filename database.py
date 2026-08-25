import os
import logging
import asyncpg
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

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

    @asynccontextmanager
    async def generation_lock(self, telegram_id: int):
        """Hold a PostgreSQL advisory lock for one user's whole generation run."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            acquired = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1::bigint)", telegram_id
            )
            if not acquired:
                yield None
                return
            try:
                yield conn
            finally:
                await conn.execute(
                    "SELECT pg_advisory_unlock($1::bigint)", telegram_id
                )

    async def get_user(self, telegram_id: int, conn=None):
        if conn is None:
            pool = await get_pool()
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT * FROM users WHERE telegram_id=$1", telegram_id
                )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id=$1", telegram_id
            )
        return dict(row) if row else None

        async def create_user(self, telegram_id: int, username: str):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO users (telegram_id, username, tokens_left, tokens_total)
                   VALUES ($1, $2, 10, 10) ON CONFLICT DO NOTHING""",
                telegram_id, username
            )

    async def save_wb_token(self, telegram_id: int, token: str):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO users (telegram_id, wb_token) VALUES ($1, $2)
                   ON CONFLICT (telegram_id) DO UPDATE SET wb_token=$2""",
                telegram_id, token
            )

    async def activate_plan(self, telegram_id: int, plan: str, tokens: int, days: int):
        expires = datetime.now() + timedelta(days=days)
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE users SET plan=$2, tokens_left=$3, tokens_total=$3,
                   sub_expires=$4, notified_expiry=FALSE, is_active=TRUE
                   WHERE telegram_id=$1""",
                telegram_id, plan, tokens, expires
            )

    async def reserve_token(self, telegram_id: int, conn=None) -> bool:
        """Atomically reserve one token before calling the text-generation API."""
        async def reserve(connection):
            row = await connection.fetchrow(
                """UPDATE users
                   SET tokens_left=tokens_left-1
                   WHERE telegram_id=$1
                     AND tokens_left > 0
                     AND (sub_expires IS NULL OR plan='trial' OR sub_expires >= NOW())
                   RETURNING telegram_id""",
                telegram_id
            )
            if row:
                return True
            await connection.execute(
                """UPDATE users SET is_active=FALSE, tokens_left=0
                   WHERE telegram_id=$1
                     AND sub_expires IS NOT NULL
                     AND plan <> 'trial'
                     AND sub_expires < NOW()""",
                telegram_id
            )
            return False

        if conn is not None:
            return await reserve(conn)
        pool = await get_pool()
        async with pool.acquire() as connection:
            return await reserve(connection)

    async def use_token(self, telegram_id: int) -> bool:
        """Backward-compatible name for an atomic token reservation."""
        return await self.reserve_token(telegram_id)

    async def refund_token(self, telegram_id: int, conn=None):
        """Return a token when generation or publishing did not succeed."""
        async def refund(connection):
            await connection.execute(
                """UPDATE users
                   SET tokens_left=LEAST(tokens_left + 1, tokens_total)
                   WHERE telegram_id=$1""",
                telegram_id
            )

        if conn is not None:
            await refund(conn)
            return
        pool = await get_pool()
        async with pool.acquire() as connection:
            await refund(connection)

        async def get_users_with_token(self):
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT telegram_id, wb_token FROM users WHERE wb_token != '' AND tokens_left > 0"
            )
            return [dict(r) for r in rows]

    async def get_users_expiring_soon(self):
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT telegram_id FROM users
                   WHERE sub_expires BETWEEN NOW() AND NOW() + INTERVAL '1 day'
                   AND notified_expiry=FALSE AND plan != 'trial'"""
            )
            return [r["telegram_id"] for r in rows]

    async def mark_expiry_notified(self, telegram_id: int):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET notified_expiry=TRUE WHERE telegram_id=$1", telegram_id
            )

    async def _is_replied(self, feedback_id: str, conn=None) -> bool:
        if conn is None:
            pool = await get_pool()
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT 1 FROM replies WHERE feedback_id=$1", feedback_id
                )
        else:
            row = await conn.fetchrow(
                "SELECT 1 FROM replies WHERE feedback_id=$1", feedback_id
            )
        return row is not None

    async def _log_reply(self, telegram_id, feedback_id, rating, reply, conn=None):
        async def log(connection):
            try:
                await connection.execute(
                    "INSERT INTO replies (telegram_id, feedback_id, rating, reply) VALUES ($1,$2,$3,$4)",
                    telegram_id, feedback_id, rating, reply
                )
            except Exception:
                pass

        if conn is not None:
            await log(conn)
            return
        pool = await get_pool()
        async with pool.acquire() as connection:
            await log(connection)

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
