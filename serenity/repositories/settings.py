class SettingsRepository:
    def __init__(self, pool):
        self.pool = pool

    async def seed(self, guild_id, defaults):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    "INSERT INTO public.admin_settings(guild_id,key,value) VALUES($1,$2,$3) "
                    "ON CONFLICT DO NOTHING",
                    [(guild_id, key, value) for key, value in defaults.items()],
                )
                rows = await conn.fetch(
                    "SELECT key,value FROM public.admin_settings WHERE guild_id=$1", guild_id
                )
                return {row["key"]: row["value"] for row in rows}

    async def save(self, guild_id, key, value, actor_id, expected):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                old = await conn.fetchval(
                    "SELECT value FROM public.admin_settings WHERE guild_id=$1 AND key=$2 "
                    "FOR UPDATE",
                    guild_id,
                    key,
                )
                if old != expected:
                    raise ValueError("Настройку уже изменили. Откройте раздел заново.")
                await conn.execute(
                    "UPDATE public.admin_settings SET value=$3,updated_at=now() "
                    "WHERE guild_id=$1 AND key=$2",
                    guild_id,
                    key,
                    value,
                )
                if key == "car_catalog_channel_id":
                    await conn.execute(
                        "INSERT INTO public.car_catalog_settings(guild_id,channel_id) VALUES($1,$2) "
                        "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id",
                        guild_id,
                        value,
                    )
                await conn.execute(
                    "INSERT INTO public.settings_history(guild_id,key,old_value,new_value,actor_id) "
                    "VALUES($1,$2,$3,$4,$5)",
                    guild_id,
                    key,
                    old,
                    value,
                    actor_id,
                )

    async def history(self, guild_id):
        return await self.pool.fetch(
            "SELECT * FROM public.settings_history WHERE guild_id=$1 ORDER BY id DESC LIMIT 20",
            guild_id,
        )
