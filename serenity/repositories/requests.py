from contextlib import asynccontextmanager

from serenity.database import get_database


class RequestRepository:
    def __init__(self, pool=None):
        self.pool = pool if pool is not None else get_database().pool

    async def create(self, guild_id, user_id, kind, payload, interaction_id=None):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """INSERT INTO public.requests(guild_id,user_id,kind,payload,interaction_id)
                    VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING RETURNING *""",
                    guild_id,
                    user_id,
                    kind,
                    payload,
                    interaction_id,
                )
                if row:
                    return row, True
                row = await conn.fetchrow(
                    """SELECT * FROM public.requests WHERE
                    (guild_id=$1 AND user_id=$2 AND kind=$3 AND status='pending')
                    OR interaction_id=$4 ORDER BY id DESC LIMIT 1""",
                    guild_id,
                    user_id,
                    kind,
                    interaction_id,
                )
                return row, False

    async def attach_message(self, request_id, channel_id, message_id):
        await self.pool.execute(
            "UPDATE public.requests SET channel_id=$2,message_id=$3 WHERE id=$1",
            request_id,
            channel_id,
            message_id,
        )

    async def pending(self, kinds):
        return await self.pool.fetch(
            "SELECT * FROM public.requests WHERE status='pending' AND kind=ANY($1::text[]) ORDER BY id",
            kinds,
        )

    async def get(self, request_id):
        return await self.pool.fetchrow("SELECT * FROM public.requests WHERE id=$1", request_id)

    @asynccontextmanager
    async def locked(self, request_id):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM public.requests WHERE id=$1 FOR UPDATE", request_id
                )
                yield conn, row

    @staticmethod
    async def finish(conn, request_id, status, actor_id):
        await conn.execute(
            "UPDATE public.requests SET status=$2,handled_by=$3,updated_at=now() WHERE id=$1",
            request_id,
            status,
            actor_id,
        )
