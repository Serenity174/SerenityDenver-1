import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Tuple

import asyncpg
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from serenity.config import get_settings
from serenity.services.access import high_staff
from serenity.services.settings import timezone as configured_timezone
from serenity.ui.base import View

settings = get_settings()

logger = logging.getLogger(__name__)


def week_bounds_msk(now: datetime) -> Tuple[datetime, datetime, date]:
    """Return (week_start_msk, week_end_msk, week_start_date). Week starts Monday 00:00 MSK."""
    start = now - timedelta(days=now.weekday())
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return start, end, start.date()


class RefreshView(View):
    def __init__(self, cog: "AttendanceStatsCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @ui.button(
        label="Обновить",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        custom_id="attendance_refresh",
    )
    async def refresh(self, interaction: discord.Interaction, button: ui.Button):
        if not any(r.id == settings.high_staff_role_id for r in interaction.user.roles):
            return await interaction.response.send_message("⚠️ Нет доступа.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.cog.refresh_and_edit_message()
        await interaction.followup.send("✅ Обновлено.", ephemeral=True)


class AttendanceStatsCog(commands.Cog):
    """Отчёт по явкам за текущую неделю с кнопкой обновления и автorefresh."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self.message_info: Dict[str, int] = {}  # channel_id, message_id, week_start
        self.auto_refresh.start()

    async def cog_load(self):
        self.pool = self.bot.database.pool
        await self._load_message_meta()
        guild = discord.Object(id=settings.guild_id)
        self.bot.tree.add_command(self.active_command, guild=guild)
        # Keep refresh button alive across restarts
        self.bot.add_view(RefreshView(self))

    async def cog_unload(self):
        self.auto_refresh.cancel()

    async def _get_meta(self, key: str) -> str | None:
        assert self.pool
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM public.attendance_stats_meta WHERE key = $1", key
            )
            return row["value"] if row else None

    async def _set_meta(self, key: str, value: str):
        assert self.pool
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.attendance_stats_meta (key, value)
                VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                key,
                value,
            )

    async def _load_message_meta(self):
        msg_id = await self._get_meta("message_id")
        ch_id = await self._get_meta("channel_id")
        week = await self._get_meta("week_start")
        if msg_id and ch_id and week:
            self.message_info = {
                "message_id": int(msg_id),
                "channel_id": int(ch_id),
                "week_start": week,
            }

    @tasks.loop(minutes=5)
    async def auto_refresh(self):
        try:
            if not self.message_info:
                logger.debug("attendance auto_refresh skipped: message_info is empty")
                return
            await self.refresh_and_edit_message()
        except Exception:
            logger.exception("attendance auto_refresh failed")

    @auto_refresh.before_loop
    async def before_auto_refresh(self):
        await self.bot.wait_until_ready()

    @auto_refresh.error
    async def auto_refresh_error(self, error: Exception):
        logger.exception("attendance auto_refresh loop crashed", exc_info=error)

    @app_commands.command(name="актив", description="Показать явку за текущую неделю (Пн-Пн)")
    @high_staff()
    async def active_command(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=False)
        embed = await self._build_embed()
        view = RefreshView(self)
        msg = await interaction.followup.send(embed=embed, view=view)
        start_msk, _, _ = week_bounds_msk(datetime.now(configured_timezone()))
        await self._set_meta("message_id", str(msg.id))
        await self._set_meta("channel_id", str(msg.channel.id))
        await self._set_meta("week_start", start_msk.date().isoformat())
        self.message_info = {
            "message_id": msg.id,
            "channel_id": msg.channel.id,
            "week_start": start_msk.date().isoformat(),
        }

    async def refresh_and_edit_message(self):
        if not self.message_info:
            return
        channel = self.bot.get_channel(self.message_info["channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.message_info["channel_id"])
            except Exception:
                logger.exception(
                    "attendance refresh failed to fetch channel",
                    extra={"channel_id": self.message_info["channel_id"]},
                )
                return
        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "attendance refresh skipped: channel is not a text channel",
                extra={"channel_id": self.message_info["channel_id"]},
            )
            return
        now = datetime.now(configured_timezone())
        start_msk, _, _ = week_bounds_msk(now)
        current_week = start_msk.date().isoformat()

        if self.message_info.get("week_start") != current_week:
            try:
                embed = await self._build_embed()
                view = RefreshView(self)
                msg = await channel.send(embed=embed, view=view)
                await self._set_meta("message_id", str(msg.id))
                await self._set_meta("channel_id", str(msg.channel.id))
                await self._set_meta("week_start", current_week)
                self.message_info = {
                    "message_id": msg.id,
                    "channel_id": msg.channel.id,
                    "week_start": current_week,
                }
            except Exception:
                logger.exception(
                    "attendance refresh failed while rotating weekly message",
                    extra={"channel_id": channel.id, "current_week": current_week},
                )
            return

        try:
            msg = await channel.fetch_message(self.message_info["message_id"])
        except Exception:
            logger.exception(
                "attendance refresh failed to fetch tracked message, creating a new one",
                extra={
                    "channel_id": channel.id,
                    "message_id": self.message_info["message_id"],
                    "current_week": current_week,
                },
            )
            try:
                embed = await self._build_embed()
                view = RefreshView(self)
                msg = await channel.send(embed=embed, view=view)
                await self._set_meta("message_id", str(msg.id))
                await self._set_meta("channel_id", str(msg.channel.id))
                await self._set_meta("week_start", current_week)
                self.message_info = {
                    "message_id": msg.id,
                    "channel_id": msg.channel.id,
                    "week_start": current_week,
                }
            except Exception:
                logger.exception(
                    "attendance refresh failed while recreating missing message",
                    extra={"channel_id": channel.id, "current_week": current_week},
                )
            return
        try:
            embed = await self._build_embed()
            view = RefreshView(self)
            await msg.edit(embed=embed, view=view)
        except Exception:
            logger.exception(
                "attendance refresh failed while editing tracked message",
                extra={"channel_id": channel.id, "message_id": msg.id},
            )

    async def _build_embed(self) -> discord.Embed:
        now = datetime.now(configured_timezone())
        start_msk, end_msk, week_date = week_bounds_msk(now)
        start_utc = start_msk.astimezone(timezone.utc)
        end_utc = end_msk.astimezone(timezone.utc)
        rows = await self._fetch_week_data(start_utc, end_utc, week_date)
        title = f"Явка за неделю {start_msk.strftime('%d.%m')} - {end_msk.strftime('%d.%m')}"
        embed = discord.Embed(title=title, color=discord.Color.from_rgb(255, 255, 255))
        if not rows:
            embed.description = "Данных за неделю пока нет."
            return embed

        place_lines = []
        name_lines = []
        count_lines = []
        for idx, row in enumerate(rows, start=1):
            place_lines.append(f"{idx}")
            name_lines.append(f"{row['mention']}")
            count_lines.append(f"{row['count']}")

        embed.add_field(name="Место", value="\n".join(place_lines), inline=True)
        embed.add_field(name="Участник", value="\n".join(name_lines), inline=True)
        embed.add_field(name="Явок", value="\n".join(count_lines), inline=True)
        embed.set_footer(text="Обновление каждые 5 минут или по кнопке 🔄")
        return embed

    async def _fetch_week_data(
        self, start_utc: datetime, end_utc: datetime, week_date: date
    ) -> List[Dict]:
        assert self.pool
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH weekly AS (
                    SELECT user_id, COUNT(*) AS cnt
                    FROM public.attendance_events
                    WHERE created_at >= $1 AND created_at < $2
                    GROUP BY user_id
                )
                INSERT INTO public.attendance_weekly_snapshots (week_start, user_id, count, updated_at)
                SELECT $3::date, user_id, cnt, now() FROM weekly
                ON CONFLICT (week_start, user_id) DO UPDATE SET count = EXCLUDED.count, updated_at = now()
                RETURNING user_id, count;
                """,
                start_utc,
                end_utc,
                week_date,
            )

        # Если events таблицу очистят, всё равно останется последняя запись в snapshots.
        if not rows:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT user_id, count FROM public.attendance_weekly_snapshots
                    WHERE week_start = $1
                    """,
                    week_date,
                )

        guild = self.bot.get_guild(settings.guild_id)
        data = []
        for r in rows:
            uid = int(r["user_id"])
            member = guild.get_member(uid) if guild else None
            data.append(
                {
                    "user_id": uid,
                    "mention": member.mention if member else f"<@{uid}>",
                    "count": int(r["count"]),
                }
            )
        data = [d for d in data if d["count"] > 0]
        data.sort(key=lambda x: x["count"], reverse=True)
        return data


async def setup(bot: commands.Bot):
    await bot.add_cog(AttendanceStatsCog(bot))
