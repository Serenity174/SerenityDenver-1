from serenity.database import get_database


class StateRepository:
    def __init__(self, pool=None):
        self.pool = pool if pool is not None else get_database().pool

    async def get(self, guild_id, namespace, key, default=None):
        value = await self.pool.fetchval(
            "SELECT value FROM public.bot_state WHERE guild_id=$1 AND namespace=$2 AND key=$3",
            guild_id,
            namespace,
            str(key),
        )
        return default if value is None else value

    async def put(self, guild_id, namespace, key, value):
        await self.pool.execute(
            """INSERT INTO public.bot_state(guild_id,namespace,key,value)
            VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,namespace,key)
            DO UPDATE SET value=excluded.value, updated_at=now()""",
            guild_id,
            namespace,
            str(key),
            value,
        )

    async def delete(self, guild_id, namespace, key):
        await self.pool.execute(
            "DELETE FROM public.bot_state WHERE guild_id=$1 AND namespace=$2 AND key=$3",
            guild_id,
            namespace,
            str(key),
        )

    async def all(self, namespace):
        return await self.pool.fetch(
            "SELECT guild_id,key,value FROM public.bot_state WHERE namespace=$1", namespace
        )
