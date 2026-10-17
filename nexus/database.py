from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import libsql

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()

db: Optional["TursoDB"] = None


class TursoResult:
    def __init__(self, rows: list):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


class TursoDB:
    """Async wrapper around the sync libsql client."""

    def __init__(self, conn: libsql.Connection):
        self.conn = conn
        self._lock = asyncio.Lock()

    async def execute(self, sql: str, params: tuple | list = ()) -> TursoResult:
        args = list(params) if params else []
        async with self._lock:
            def _run():
                cur = self.conn.execute(sql, args)
                try:
                    rows = cur.fetchall()
                except Exception:
                    rows = []
                self.conn.commit()
                return rows
            rows = await asyncio.to_thread(_run)
        return TursoResult(rows)

    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


async def init_db() -> None:
    global db
    if not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
        raise RuntimeError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required.")

    # libsql uses HTTP under the hood — works with current Turso
    conn = libsql.connect(
        database=TURSO_DATABASE_URL,
        auth_token=TURSO_AUTH_TOKEN,
    )
    db = TursoDB(conn)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            log_channel_id INTEGER,
            link_filter_enabled INTEGER NOT NULL DEFAULT 1,
            antispam_enabled INTEGER NOT NULL DEFAULT 1,
            min_account_age_days INTEGER NOT NULL DEFAULT 7,
            spam_timeout_minutes INTEGER NOT NULL DEFAULT 1,
            link_notice_enabled INTEGER NOT NULL DEFAULT 1,
            word_filter_enabled INTEGER NOT NULL DEFAULT 0,
            mention_spam_enabled INTEGER NOT NULL DEFAULT 1,
            verify_enabled INTEGER NOT NULL DEFAULT 0,
            verify_role_id INTEGER,
            verify_channel_id INTEGER,
            warn_timeout_threshold INTEGER NOT NULL DEFAULT 0,
            warn_timeout_minutes INTEGER NOT NULL DEFAULT 10,
            warn_kick_threshold INTEGER NOT NULL DEFAULT 0,
            warn_ban_threshold INTEGER NOT NULL DEFAULT 0,
            urlhaus_enabled INTEGER NOT NULL DEFAULT 1
        )
    """)
    migrations = [
        "ALTER TABLE guild_config ADD COLUMN spam_timeout_minutes INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE guild_config ADD COLUMN link_notice_enabled INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE guild_config ADD COLUMN word_filter_enabled INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN mention_spam_enabled INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE guild_config ADD COLUMN verify_enabled INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN verify_role_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN verify_channel_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN warn_timeout_threshold INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN warn_timeout_minutes INTEGER NOT NULL DEFAULT 10",
        "ALTER TABLE guild_config ADD COLUMN warn_kick_threshold INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN warn_ban_threshold INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN urlhaus_enabled INTEGER NOT NULL DEFAULT 1",
    ]
    for sql in migrations:
        try:
            await db.execute(sql)
        except Exception:
            pass

    for sql in (
        """CREATE TABLE IF NOT EXISTS allowed_domains (
            guild_id INTEGER NOT NULL, domain TEXT NOT NULL, PRIMARY KEY (guild_id, domain))""",
        """CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS ignored_channels (
            guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, PRIMARY KEY (guild_id, channel_id))""",
        """CREATE TABLE IF NOT EXISTS whitelist_roles (
            guild_id INTEGER NOT NULL, role_id INTEGER NOT NULL, PRIMARY KEY (guild_id, role_id))""",
        """CREATE TABLE IF NOT EXISTS whitelist_users (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, PRIMARY KEY (guild_id, user_id))""",
        """CREATE TABLE IF NOT EXISTS banned_words (
            guild_id INTEGER NOT NULL, word TEXT NOT NULL, PRIMARY KEY (guild_id, word))""",
    ):
        await db.execute(sql)


async def ensure_guild_config(guild_id: int) -> None:
    assert db is not None
    await db.execute("INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,))


async def get_config(guild_id: int) -> dict:
    assert db is not None
    await ensure_guild_config(guild_id)
    cursor = await db.execute(
        """SELECT log_channel_id, link_filter_enabled, antispam_enabled, min_account_age_days,
                  spam_timeout_minutes, link_notice_enabled, word_filter_enabled, mention_spam_enabled,
                  verify_enabled, verify_role_id, verify_channel_id,
                  warn_timeout_threshold, warn_timeout_minutes, warn_kick_threshold, warn_ban_threshold,
                  urlhaus_enabled
           FROM guild_config WHERE guild_id = ?""",
        (guild_id,),
    )
    row = await cursor.fetchone()
    return {
        "log_channel_id": row[0],
        "link_filter_enabled": bool(row[1]),
        "antispam_enabled": bool(row[2]),
        "min_account_age_days": int(row[3]),
        "spam_timeout_minutes": int(row[4] or 1),
        "link_notice_enabled": bool(row[5] if row[5] is not None else 1),
        "word_filter_enabled": bool(row[6] if row[6] is not None else 0),
        "mention_spam_enabled": bool(row[7] if row[7] is not None else 1),
        "verify_enabled": bool(row[8] if row[8] is not None else 0),
        "verify_role_id": row[9],
        "verify_channel_id": row[10],
        "warn_timeout_threshold": int(row[11] or 0),
        "warn_timeout_minutes": int(row[12] or 10),
        "warn_kick_threshold": int(row[13] or 0),
        "warn_ban_threshold": int(row[14] or 0),
        "urlhaus_enabled": bool(row[15] if len(row) > 15 and row[15] is not None else 1),
    }


async def get_allowed_domains(guild_id: int) -> set[str]:
    assert db is not None
    cursor = await db.execute("SELECT domain FROM allowed_domains WHERE guild_id = ?", (guild_id,))
    return {r[0] for r in await cursor.fetchall()}


async def get_ignored_channels(guild_id: int) -> set[int]:
    assert db is not None
    cursor = await db.execute("SELECT channel_id FROM ignored_channels WHERE guild_id = ?", (guild_id,))
    return {r[0] for r in await cursor.fetchall()}


async def get_whitelist_roles(guild_id: int) -> set[int]:
    assert db is not None
    cursor = await db.execute("SELECT role_id FROM whitelist_roles WHERE guild_id = ?", (guild_id,))
    return {r[0] for r in await cursor.fetchall()}


async def get_whitelist_users(guild_id: int) -> set[int]:
    assert db is not None
    cursor = await db.execute("SELECT user_id FROM whitelist_users WHERE guild_id = ?", (guild_id,))
    return {r[0] for r in await cursor.fetchall()}


async def get_banned_words(guild_id: int) -> set[str]:
    assert db is not None
    cursor = await db.execute("SELECT word FROM banned_words WHERE guild_id = ?", (guild_id,))
    return {r[0].lower() for r in await cursor.fetchall()}


async def is_whitelisted(member) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_messages:
        return True
    users = await get_whitelist_users(member.guild.id)
    if member.id in users:
        return True
    roles = await get_whitelist_roles(member.guild.id)
    return any(r.id in roles for r in member.roles)


async def count_warnings(guild_id: int, user_id: int) -> int:
    assert db is not None
    cursor = await db.execute(
        "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
    )
    row = await cursor.fetchone()
    return row[0] if row else 0
