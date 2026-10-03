import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from typing import Dict, List

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, tasks

from serenity.config import get_settings
from serenity.repositories.payouts import PayoutRepository
from serenity.services.access import high_staff
from serenity.services.settings import enabled, images, option
from serenity.services.settings import timezone as configured_timezone

settings = get_settings()

# Константы
COMMENT = "Недельная премия"

# Временная зона МСК

IMAGE_POOL = [
    "https://i.ibb.co/SwPXfHTY/payments1.png",
    "https://i.ibb.co/s9DyDxhb/payments2.png",
    "https://i.ibb.co/JR4rwxFK/payments3.png",
    "https://i.ibb.co/6JYw32Yj/payments4.png",
    "https://i.ibb.co/DqVNZGC/payments5.png",
    "https://i.ibb.co/PvCLYrBT/payments6.png",
    "https://i.ibb.co/LX7qDsBZ/payments7.png",
    "https://i.ibb.co/4RKpKb1R/payments8.png",
    "https://i.ibb.co/SDtTk7pR/payments9.png",
    "https://i.ibb.co/pjtm9y6x/1.png",
    "https://i.ibb.co/G4Jh0nh2/2.png",
]


def format_currency(value: float) -> str:
    return f"{value:,.0f}$".replace(",", ".")


def next_monday_date_msk(now_msk: datetime) -> str:
    days_until_monday = (7 - now_msk.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = (now_msk + timedelta(days=days_until_monday)).date()
    return next_monday.strftime("%d.%m.%Y")


def next_sunday_date_msk(now_msk: datetime) -> str:
    days_until_sunday = (6 - now_msk.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7
    next_sunday = (now_msk + timedelta(days=days_until_sunday)).date()
    return next_sunday.strftime("%d.%m.%Y")


class Payouts(commands.Cog):
    """Еженедельный расчёт премий из attendance (contracts) и report_db."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self._run_lock = asyncio.Lock()
        self.loop_task.start()

    async def cog_load(self):
        self.pool = self.bot.database.pool
        guild = discord.Object(id=settings.guild_id)
        self.bot.tree.add_command(self.manual_payout, guild=guild)

    async def cog_unload(self):
        self.loop_task.cancel()

    async def _get_meta(self, key: str) -> str | None:
        assert self.pool
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM public.payout_meta WHERE key = $1", key)
            return row["value"] if row else None

    async def _set_meta(self, key: str, value: str):
        assert self.pool
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.payout_meta (key, value)
                VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                key,
                value,
            )

    @tasks.loop(minutes=5)
    async def loop_task(self):
        if not enabled("payouts"):
            return
        now_msk = datetime.now(configured_timezone())
        payout_hour, payout_minute = map(int, option("payout_time", "23:30").split(":"))
        # воскресенье (6), 23:30
        if not (
            now_msk.weekday() == 6
            and (now_msk.hour, now_msk.minute) >= (payout_hour, payout_minute)
        ):
            return
        last_run = await self._get_meta("last_payout_date")
        if last_run == now_msk.date().isoformat():
            return
        try:
            await self._run_payout(scheduled=True)
            await self._set_meta("last_payout_date", now_msk.date().isoformat())
        except Exception:
            logging.getLogger(__name__).exception("Scheduled payout failed; will retry")

    @loop_task.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
        # ensure pool created in cog_load

    @app_commands.command(name="предрасчет", description="Ручной предрасчёт за текущую неделю")
    @high_staff()
    async def manual_payout(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        result = await self._run_payout()
        await interaction.followup.send(result, ephemeral=True)

    async def _run_payout(self, scheduled=False) -> str:
        async with self._run_lock:
            return await self._run_payout_locked(scheduled)

    async def _run_payout_locked(self, scheduled=False) -> str:
        if not self.pool:
            return "База данных недоступна."

        # Границы недели (понедельник 00:00 МСК -> понедельник 00:00 следующей)
        now_msk = datetime.now(configured_timezone())
        week_start_msk = now_msk - timedelta(days=now_msk.weekday())
        week_start_msk = week_start_msk.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end_msk = week_start_msk + timedelta(days=7)
        start_utc = week_start_msk.astimezone(timezone.utc)
        end_utc = week_end_msk.astimezone(timezone.utc)

        payouts = await self._collect_payouts(start_utc, end_utc)
        if not payouts:
            return "Данных за текущую неделю нет."

        run = None
        if scheduled:
            run = await PayoutRepository(self.pool).snapshot(
                settings.guild_id, week_start_msk.date(), payouts
            )
            if run["completed_at"]:
                return "Расчёт за эту неделю уже опубликован."
            payouts = [{**row, "amount": Decimal(row["amount"])} for row in run["payload"]]
        await self._send_results(payouts, week_end_msk, now_msk, run)
        if scheduled:
            await PayoutRepository(self.pool).finish(settings.guild_id, week_start_msk.date())
        return "Выплаты отправлены."

    async def _collect_payouts(self, start_utc: datetime, end_utc: datetime) -> List[Dict]:
        assert self.pool
        combined = await PayoutRepository(self.pool).totals(
            start_utc, end_utc, Decimal(option("attendance_reward", "40000"))
        )

        guild = self.bot.get_guild(settings.guild_id)
        payouts: List[Dict] = []
        for uid, amount in combined.items():
            member = guild.get_member(uid) if guild else None
            display = member.display_name if member else str(uid)
            static_id = self._extract_static_id(display) or str(uid)
            payouts.append(
                {
                    "user_id": uid,
                    "mention": member.mention if member else f"<@{uid}>",
                    "static_id": static_id,
                    "amount": amount,
                }
            )

        payouts.sort(key=lambda x: x["amount"], reverse=True)
        return payouts

    @staticmethod
    def _extract_static_id(name: str) -> str | None:
        digits = ""
        for ch in reversed(name.strip()):
            if ch.isdigit():
                digits = ch + digits
            else:
                if digits:
                    break
        return digits or None

    async def _send_results(
        self, payouts: List[Dict], week_end_msk: datetime, now_msk: datetime, run=None
    ):
        embed_channel = self.bot.get_channel(settings.payout_channel_id)
        file_channel = self.bot.get_channel(settings.payout_file_channel_id)
        if not isinstance(embed_channel, discord.TextChannel) or not isinstance(
            file_channel, discord.TextChannel
        ):
            raise RuntimeError("Payout channels are unavailable")

        # Файл
        lines = ["staticId;amount;comment"]
        lines.extend(
            f"{p['static_id']};{int(round(p['amount']))};{option('payout_comment', COMMENT)}"
            for p in payouts
        )
        file_buf = BytesIO("\n".join(lines).encode("utf-8"))
        file = discord.File(fp=file_buf, filename="weekly_payouts.txt")

        total_amount = sum(p["amount"] for p in payouts)
        next_date = next_sunday_date_msk(now_msk)

        description_lines = [
            f"{p['mention']} {p['static_id']} - {format_currency(p['amount'])}" for p in payouts
        ]
        description_lines.append("")
        description_lines.append(f"Общая сума выплат: **{format_currency(total_amount)}**")
        description_lines.append(f"Следующая премия - __**{next_date}**__")

        embed = discord.Embed(
            title="Недельная премия",
            description="\n".join(description_lines)[:4000],
            color=discord.Color.from_rgb(255, 255, 255),
            timestamp=week_end_msk.astimezone(timezone.utc),
        )
        embed.set_image(url=random.choice(images("payout_images", IMAGE_POOL)))
        marker = f"Расчёт Serenity: {settings.guild_id}:{run['week_start']}" if run else None
        if marker:
            embed.set_footer(text=marker)

        repo = PayoutRepository(self.pool)
        if run is None or not run["embed_message_id"]:
            message = None
            if run:
                async for candidate in embed_channel.history(limit=None, after=run["created_at"]):
                    if (
                        candidate.author.id == self.bot.user.id
                        and candidate.embeds
                        and candidate.embeds[0].footer.text == marker
                    ):
                        message = candidate
                        break
            if message is None:
                message = await embed_channel.send(embed=embed)
            if run:
                await repo.message_sent(settings.guild_id, run["week_start"], "embed", message.id)
        if run is None or not run["file_message_id"]:
            message = None
            if run:
                async for candidate in file_channel.history(limit=None, after=run["created_at"]):
                    if candidate.author.id == self.bot.user.id and candidate.content == marker:
                        message = candidate
                        break
            if message is None:
                message = await file_channel.send(
                    files=[file], content=marker or "Текстовый файл с выплатами"
                )
            if run:
                await repo.message_sent(settings.guild_id, run["week_start"], "file", message.id)
        file.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(Payouts(bot))
