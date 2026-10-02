"""One PostgreSQL pool, ordered migrations and a single active bot per guild."""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
_database = None


async def configure_connection(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def migrate(pool, directory=MIGRATIONS):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(731824510)")
            await conn.execute("""CREATE TABLE IF NOT EXISTS public.schema_migrations (
                version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            applied = {
                row["version"]: row["checksum"]
                for row in await conn.fetch(
                    "SELECT version, checksum FROM public.schema_migrations"
                )
            }
            for file in sorted(directory.glob("*.sql")):
                content = file.read_bytes()
                checksum = hashlib.sha256(content).hexdigest()
                if file.name in applied:
                    if applied[file.name] != checksum:
                        raise RuntimeError(f"Applied migration changed: {file.name}")
                    continue
                await conn.execute(content.decode("utf-8"))
                await conn.execute(
                    "INSERT INTO public.schema_migrations(version, checksum) VALUES ($1,$2)",
                    file.name,
                    checksum,
                )
                log.info("Applied migration %s", file.name)


class Database:
    def __init__(self, url, *, min_size=2, max_size=10):
        self.url = url
        self.min_size = min_size
        self.max_size = max_size
        self.pool = None
        self._lease = None
        self._guild_id = None

    async def open(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                self.url,
                min_size=self.min_size,
                max_size=self.max_size,
                timeout=15,
                command_timeout=30,
                init=configure_connection,
                server_settings={"application_name": "serenity"},
            )
        await migrate(self.pool)

    async def acquire_bot_lease(self, guild_id):
        self._lease = await self.pool.acquire()
        self._guild_id = guild_id
        if not await self._lease.fetchval("SELECT pg_try_advisory_lock($1::bigint)", guild_id):
            await self.pool.release(self._lease)
            self._lease = None
            raise RuntimeError("Another Serenity instance already owns this guild")

    async def check_lease(self):
        if self._lease is None or self._lease.is_closed():
            raise RuntimeError("Bot database lease lost")
        await self._lease.fetchval("SELECT 1")

    async def close(self):
        if self.pool:
            if self._lease is not None:
                try:
                    await self._lease.execute(
                        "SELECT pg_advisory_unlock($1::bigint)", self._guild_id
                    )
                except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError):
                    log.warning("Lease connection was already lost during shutdown")
                finally:
                    try:
                        await self.pool.release(self._lease)
                    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError):
                        log.warning("Could not release lost lease connection")
                    finally:
                        self._lease = None
            try:
                await asyncio.wait_for(self.pool.close(), timeout=15)
            except asyncio.TimeoutError:
                self.pool.terminate()
            self.pool = None


def set_database(database):
    global _database
    _database = database


def get_database():
    if _database is None or _database.pool is None:
        raise RuntimeError("Database is not started")
    return _database
