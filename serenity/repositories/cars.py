from typing import Literal

import asyncpg

CatalogType = Literal["family", "cargo"]


class CarsRepository:
    def __init__(self, pool):
        self.pool = pool

    async def init(self):
        """Schema is migrated before extensions start."""

    async def ensure_guild_settings(self, guild_id: int, default_channel_id: int) -> None:
        await self.init()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.car_catalog_settings (guild_id, channel_id)
                VALUES ($1, $2)
                ON CONFLICT(guild_id) DO NOTHING
                """,
                guild_id,
                default_channel_id,
            )

    async def get_catalog_channel_id(self, guild_id: int) -> int | None:
        await self.init()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT channel_id FROM public.car_catalog_settings WHERE guild_id = $1",
                guild_id,
            )
            return int(row["channel_id"]) if row else None

    async def upsert_catalog_message(
        self,
        guild_id: int,
        category: CatalogType,
        page_index: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        await self.init()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.car_catalog_messages (guild_id, category, page_index, channel_id, message_id)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT(guild_id, category, page_index)
                DO UPDATE SET channel_id = excluded.channel_id, message_id = excluded.message_id
                """,
                guild_id,
                category,
                page_index,
                channel_id,
                message_id,
            )

    async def get_catalog_messages(
        self, guild_id: int, category: CatalogType
    ) -> list[asyncpg.Record]:
        await self.init()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT page_index, channel_id, message_id
                FROM public.car_catalog_messages
                WHERE guild_id = $1 AND category = $2
                ORDER BY page_index ASC
                """,
                guild_id,
                category,
            )
            return list(rows)

    async def delete_catalog_message(
        self, guild_id: int, category: CatalogType, page_index: int
    ) -> None:
        await self.init()
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM public.car_catalog_messages WHERE guild_id = $1 AND category = $2 AND page_index = $3",
                guild_id,
                category,
                page_index,
            )

    async def add_car(
        self,
        guild_id: int,
        category: CatalogType,
        title: str,
        max_speed_kmh: int,
        accel_0_100: float,
        trunk_kg: int,
        url: str,
        image_url: str,
        payload_tons_text: str | None = None,
    ) -> None:
        await self.init()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.cars (
                    guild_id, category, title, max_speed_kmh, accel_0_100,
                    trunk_kg, payload_tons_text, url, image_url
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                guild_id,
                category,
                title,
                max_speed_kmh,
                accel_0_100,
                trunk_kg,
                payload_tons_text,
                url,
                image_url,
            )

    async def delete_car(self, guild_id: int, car_id: int, category: CatalogType) -> bool:
        await self.init()
        async with self.pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM public.cars WHERE guild_id = $1 AND id = $2 AND category = $3",
                guild_id,
                car_id,
                category,
            )
            return int(status.split()[-1]) > 0

    async def list_cars(self, guild_id: int, category: CatalogType) -> list[asyncpg.Record]:
        await self.init()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, title, max_speed_kmh, accel_0_100, trunk_kg, payload_tons_text, url, image_url
                FROM public.cars
                WHERE guild_id = $1 AND category = $2
                ORDER BY max_speed_kmh DESC, accel_0_100 ASC, LOWER(title) ASC
                """,
                guild_id,
                category,
            )
            return list(rows)
