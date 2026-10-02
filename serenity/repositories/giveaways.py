import datetime as dt
from dataclasses import dataclass
from typing import List, Optional, Tuple

import asyncpg

from serenity.database import get_database


@dataclass
class Giveaway:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    prize: str
    winners_count: int
    ends_at: dt.datetime
    host_id: int
    finished: bool


DEFAULT_COLOR_HEX = "5865F2"
DEFAULT_COLOR_INT = int(DEFAULT_COLOR_HEX, 16)
DEFAULT_EMOJI = "🎉"


async def pg_pool() -> asyncpg.Pool:
    return get_database().pool


def giveaway_from_row(row: asyncpg.Record) -> Giveaway:
    return Giveaway(
        id=int(row["id"]),
        guild_id=int(row["guild_id"]),
        channel_id=int(row["channel_id"]),
        message_id=int(row["messege_id"]),
        prize=row["name"],
        winners_count=int(row["winner_count"]),
        ends_at=row["end_date"].astimezone(dt.timezone.utc),
        host_id=int(row["host_id"]),
        finished=bool(row["finished"]),
    )


# === Postgres: таблица give ===


async def pg_create_give(
    guild_id: int,
    channel_id: int,
    prize: str,
    winners: int,
    ends_at: dt.datetime,
    host_id: int,
) -> int:
    """
    Создаёт запись в public.give БЕЗ message_id (messege_id='0' временно).
    Возвращает ID розыгрыша.
    """
    pool = await pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO public.give(
                guild_id, channel_id, "name",
                user_ids, end_date, finished,
                messege_id, host_id, winner_count
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            guild_id,
            channel_id,
            prize,
            None,  # user_ids
            ends_at,
            False,  # finished
            "0",  # временно, потом обновим
            str(host_id),
            winners,
        )
        return int(row["id"])


async def pg_set_message_id(give_id: int, message_id: int) -> None:
    pool = await pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.give SET messege_id = $1 WHERE id = $2",
            str(message_id),
            give_id,
        )


async def pg_get_give(give_id: int) -> Optional[Giveaway]:
    pool = await pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, guild_id, channel_id, "name",
                   user_ids, end_date, finished,
                   messege_id, host_id, winner_count
            FROM public.give
            WHERE id = $1
            """,
            give_id,
        )
        if not row:
            return None
        return giveaway_from_row(row)


async def pg_list_running(guild_id: int) -> List[Giveaway]:
    pool = await pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, guild_id, channel_id, "name",
                   user_ids, end_date, finished,
                   messege_id, host_id, winner_count
            FROM public.give
            WHERE guild_id = $1 AND finished = FALSE
            ORDER BY end_date ASC
            """,
            guild_id,
        )
        return [giveaway_from_row(r) for r in rows]


async def pg_due() -> List[Giveaway]:
    """
    Все розыгрыши, у которых пора подводить итоги.
    """
    pool = await pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, guild_id, channel_id, "name",
                   user_ids, end_date, finished,
                   messege_id, host_id, winner_count
            FROM public.give
            WHERE finished = FALSE AND end_date <= NOW()
            """
        )
        return [giveaway_from_row(r) for r in rows]


async def pg_set_finished(give_id: int, finished: bool) -> None:
    pool = await pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.give SET finished = $1 WHERE id = $2",
            finished,
            give_id,
        )


async def pg_mark_running(give_id: int) -> None:
    await (await pg_pool()).execute(
        "UPDATE public.give SET finished=FALSE,winner_ids=NULL,result_version=result_version+1 WHERE id=$1",
        give_id,
    )


async def pg_mark_ended(give_id: int) -> None:
    await pg_set_finished(give_id, True)


async def pg_get_user_ids(give_id: int) -> List[int]:
    pool = await pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_ids FROM public.give WHERE id = $1",
            give_id,
        )
        if not row or row["user_ids"] is None:
            return []
        parts = [p for p in str(row["user_ids"]).split(",") if p.strip()]
        return [int(p) for p in parts]


async def pg_set_user_ids(give_id: int, user_ids: List[int]) -> None:
    pool = await pg_pool()
    async with pool.acquire() as conn:
        user_ids_str = ",".join(str(uid) for uid in user_ids) if user_ids else None
        await conn.execute(
            "UPDATE public.give SET user_ids = $1 WHERE id = $2",
            user_ids_str,
            give_id,
        )


async def pg_toggle_entry(give_id: int, user_id: int) -> tuple[bool, List[int]]:
    """
    Добавляет или удаляет участника.
    Возвращает (joined, current_user_ids).
    joined = True  -> пользователь добавлен
    joined = False -> пользователь удалён
    """
    pool = await pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT user_ids,finished,end_date FROM public.give WHERE id = $1 FOR UPDATE",
                give_id,
            )
            if (
                row is None
                or row["finished"]
                or row["end_date"] <= dt.datetime.now(dt.timezone.utc)
            ):
                raise ValueError("Розыгрыш уже завершён.")
            current: set[int] = set()
            if row and row["user_ids"]:
                for p in str(row["user_ids"]).split(","):
                    p = p.strip()
                    if p:
                        current.add(int(p))

            joined: bool
            if user_id in current:
                current.remove(user_id)
                joined = False
            else:
                current.add(user_id)
                joined = True

            user_ids_list = sorted(current)
            user_ids_str = ",".join(str(uid) for uid in user_ids_list) if user_ids_list else None

            await conn.execute(
                "UPDATE public.give SET user_ids = $1 WHERE id = $2",
                user_ids_str,
                give_id,
            )

            return joined, user_ids_list


# === Postgres: guild_settings ===


async def get_guild_settings(guild_id: int) -> Tuple[int, str]:
    """
    Получить настройки гильдии (color_int, emoji) из Postgres.guild_settings.
    Если записи нет — создаём дефолт и возвращаем его.
    """
    pool = await pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT color_hex, emoji FROM public.guild_settings WHERE guild_id = $1",
            guild_id,
        )
        if row:
            color_hex = row["color_hex"] or DEFAULT_COLOR_HEX
            emoji = row["emoji"] or DEFAULT_EMOJI
            return int(color_hex, 16), emoji

        # Строки нет — создаём с дефолтами
        await conn.execute(
            """
            INSERT INTO public.guild_settings (guild_id)
            VALUES ($1)
            ON CONFLICT (guild_id) DO NOTHING
            """,
            guild_id,
        )
        return DEFAULT_COLOR_INT, DEFAULT_EMOJI


async def set_guild_color(guild_id: int, color_hex: str) -> None:
    color_hex = color_hex.strip().lstrip("#").upper()
    int(color_hex, 16)  # валидация

    pool = await pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.guild_settings (guild_id, color_hex)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE
            SET color_hex = EXCLUDED.color_hex
            """,
            guild_id,
            color_hex,
        )


async def set_guild_emoji(guild_id: int, emoji: str) -> None:
    emoji = emoji.strip()
    if not emoji:
        raise ValueError("Эмодзи не может быть пустым")

    pool = await pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.guild_settings (guild_id, emoji)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE
            SET emoji = EXCLUDED.emoji
            """,
            guild_id,
            emoji,
        )


async def pg_choose_winners(give_id):
    import random

    async with (await pg_pool()).acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT * FROM public.give WHERE id=$1 FOR UPDATE", give_id)
            if row is None:
                return [], 0
            winners = row["winner_ids"]
            if winners is None:
                participants = list(
                    dict.fromkeys(
                        int(value) for value in (row["user_ids"] or "").split(",") if value.strip()
                    )
                )
                winners = random.sample(participants, min(len(participants), row["winner_count"]))
                await conn.execute(
                    "UPDATE public.give SET winner_ids=$2 WHERE id=$1", give_id, winners
                )
            return winners, row["result_version"]
