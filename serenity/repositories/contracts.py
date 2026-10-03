from typing import List, Optional

import asyncpg

from serenity.config import get_settings
from serenity.services.contract_rules import active_slots, role_priority


class ContractDB:
    def __init__(self, pool):
        self.pool = pool

    async def connect(self):
        """Pool is owned by the application."""

    async def reset_all(self) -> int:
        """Полный сброс контрактов и явок. Возвращает число сброшенных пользователей."""
        await self.connect()

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    TRUNCATE TABLE public.contract_signups,
                                   public.attendance_events,
                                   public.contracts
                    RESTART IDENTITY CASCADE;
                    """
                )
                updated = await conn.fetchval(
                    """
                    WITH updated AS (
                        UPDATE public.contract_users
                        SET weekly_attendance = 0,
                            total_attendance = 0,
                            last_attended_at = NULL,
                            updated_at = now()
                        RETURNING 1
                    )
                    SELECT COUNT(*) FROM updated;
                    """
                )
                return int(updated or 0)

    async def upsert_user(self, user_id: int, rank: int):
        query = """
        INSERT INTO public.contract_users (discord_id, rank)
        VALUES ($1, $2)
        ON CONFLICT (discord_id) DO UPDATE
        SET rank = EXCLUDED.rank,
            updated_at = now();
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id, rank)

    async def create_contract(self, channel_id: int, message_id: int, host_id: int) -> int:
        query = """
        INSERT INTO public.contracts (channel_id, message_id, host_id)
        VALUES ($1, $2, $3)
        RETURNING id;
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, channel_id, message_id, host_id)
            return int(row["id"])

    async def get_contract_by_message(self, message_id: int) -> Optional[asyncpg.Record]:
        query = "SELECT * FROM public.contracts WHERE message_id = $1"
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, message_id)

    async def add_signup(self, contract_id: int, user_id: int):
        query = """
        INSERT INTO public.contract_signups (contract_id, user_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING;
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, contract_id, user_id)

    async def remove_signup(self, contract_id: int, user_id: int):
        query = "DELETE FROM public.contract_signups WHERE contract_id = $1 AND user_id = $2"
        async with self.pool.acquire() as conn:
            await conn.execute(query, contract_id, user_id)

    async def fetch_signups(self, contract_id: int, closed: bool) -> List[asyncpg.Record]:
        order_clause = (
            "ORDER BY CASE WHEN cs.user_id = c.host_id THEN 0 ELSE 1 END, cu.rank ASC, cu.weekly_attendance ASC, cs.created_at ASC"
            if not closed
            else "ORDER BY CASE WHEN cs.user_id = c.host_id THEN 0 ELSE 1 END, cu.rank ASC, cs.created_at ASC"
        )
        query = f"""
        SELECT
            cs.user_id,
            cs.created_at,
            cu.rank,
            cu.weekly_attendance,
            cu.total_attendance
        FROM public.contract_signups cs
        JOIN public.contracts c ON c.id = cs.contract_id
        JOIN public.contract_users cu ON cu.discord_id = cs.user_id
        WHERE cs.contract_id = $1
        {order_clause}
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, contract_id)
            return list(rows)

    async def close_contract(self, contract_id: int):
        query = "UPDATE public.contracts SET closed = TRUE WHERE id = $1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, contract_id)

    async def mark_attendance(self, contract_id: int, marker_id: int) -> int:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(731824511)")
                contract_row = await conn.fetchrow(
                    "SELECT attendance_marked, host_id FROM public.contracts WHERE id = $1 FOR UPDATE",
                    contract_id,
                )
                if not contract_row or contract_row["attendance_marked"]:
                    return 0

                host_id = int(contract_row["host_id"])
                await conn.execute(
                    """
                    INSERT INTO public.contract_users (discord_id, rank)
                    VALUES ($1, $2)
                    ON CONFLICT (discord_id) DO NOTHING;
                    """,
                    host_id,
                    role_priority().get(get_settings().high_staff_role_id, 999),
                )
                await conn.execute(
                    """
                    INSERT INTO public.contract_signups (contract_id, user_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING;
                    """,
                    contract_id,
                    host_id,
                )

                await conn.execute(
                    """
                    UPDATE public.contracts
                    SET attendance_marked = TRUE
                    WHERE id = $1
                    """,
                    contract_id,
                )

                updated_count = await conn.fetchval(
                    """
                    WITH ranked_signups AS (
                        SELECT
                            cs.user_id,
                            ROW_NUMBER() OVER (
                                ORDER BY CASE WHEN cs.user_id = c.host_id THEN 0 ELSE 1 END,
                                         cu.rank ASC,
                                         cu.weekly_attendance ASC,
                                         cs.created_at ASC
                            ) AS rn
                        FROM public.contract_signups cs
                        JOIN public.contracts c ON c.id = cs.contract_id
                        JOIN public.contract_users cu ON cu.discord_id = cs.user_id
                        WHERE cs.contract_id = $1
                    ),
                    eligible AS (
                        SELECT user_id FROM ranked_signups WHERE rn <= $2
                    ),
                    updated AS (
                        UPDATE public.contract_users cu
                        SET weekly_attendance = cu.weekly_attendance + 1,
                            total_attendance = cu.total_attendance + 1,
                            last_attended_at = now(),
                            updated_at = now()
                        FROM eligible
                        WHERE cu.discord_id = eligible.user_id
                        RETURNING cu.discord_id
                    ),
                    inserted AS (
                        INSERT INTO public.attendance_events (contract_id, user_id, marked_by)
                        SELECT $1, discord_id, $3 FROM updated
                    )
                    SELECT COUNT(*) FROM updated;
                    """,
                    contract_id,
                    active_slots(),
                    marker_id,
                )
                return int(updated_count or 0)

    async def fetch_profile(self, user_id: int) -> Optional[asyncpg.Record]:
        query = """
        SELECT discord_id, rank, weekly_attendance, total_attendance, last_attended_at
        FROM public.contract_users
        WHERE discord_id = $1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, user_id)

    async def set_meta(self, key: str, value: str):
        query = """
        INSERT INTO public.contract_meta (key, value)
        VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, key, value)

    async def get_meta(self, key: str) -> Optional[str]:
        query = "SELECT value FROM public.contract_meta WHERE key = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, key)
            return row["value"] if row else None
