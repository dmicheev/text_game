"""Лёгкая идемпотентная миграция схемы под мультиплатформенную модель.

Запускается до create_all: актуализирует существующие таблицы,
созданные предыдущей (telegram-only) версией схемы.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def _column_exists(conn, table: str, column: str) -> bool:
    result = await conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.scalar() is not None


async def _has_rows(conn, table: str) -> bool:
    try:
        result = await conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))  # noqa: S608
        return result.scalar() is not None
    except Exception:
        return False


async def migrate(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        if await _column_exists(conn, "users", "tg_id"):
            logger.info("migrating users.tg_id -> platform/platform_user_id")
            await conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN IF NOT EXISTS platform varchar(16) "
                    "NOT NULL DEFAULT 'telegram'"
                )
            )
            await conn.execute(text("ALTER TABLE users RENAME COLUMN tg_id TO platform_user_id"))
            await conn.execute(text("DROP INDEX IF EXISTS ix_users_tg_id"))
            await conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_tg_id"))
            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_platform_pid "
                    "ON users (platform, platform_user_id)"
                )
            )
            await conn.execute(text("DROP INDEX IF EXISTS ix_users_platform_user_id"))

        if await _column_exists(conn, "games", "dashboard_message_id"):
            if await _has_rows(conn, "games"):
                await conn.execute(
                    text(
                        "ALTER TABLE games ALTER COLUMN dashboard_message_id "
                        "TYPE varchar(64) USING dashboard_message_id::text"
                    )
                )
            else:
                await conn.execute(
                    text("ALTER TABLE games ALTER COLUMN dashboard_message_id TYPE varchar(64)")
                )
        if await _column_exists(conn, "games", "dashboard_chat_id"):
            await conn.execute(
                text(
                    "ALTER TABLE games ADD COLUMN IF NOT EXISTS dashboard_platform "
                    "varchar(16)"
                )
            )
            await conn.execute(
                text(
                    "UPDATE games SET dashboard_platform = 'telegram' "
                    "WHERE dashboard_platform IS NULL"
                )
            )

        if await _column_exists(conn, "games", "dashboard_chat_id"):
            await conn.execute(
                text(
                    "ALTER TABLE games ADD COLUMN IF NOT EXISTS style_temperature "
                    "double precision"
                )
            )

        if await _column_exists(conn, "chapters", "summary"):
            await conn.execute(
                text("ALTER TABLE chapters ADD COLUMN IF NOT EXISTS memory text")
            )
            await conn.execute(
                text("ALTER TABLE chapters ADD COLUMN IF NOT EXISTS illustration bytea")
            )
            await conn.execute(
                text(
                    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS "
                    "illustration_prompt text"
                )
            )
