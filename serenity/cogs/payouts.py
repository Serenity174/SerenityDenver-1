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

settings = get_settings()

# Константы
GUILD_ID = settings.guild_id
HIGH_STAFF_ROLE_ID = settings.high_staff_role_id
PAYOUT_CHANNEL_ID = settings.payout_channel_id
PAYOUT_FILE_CHANNEL_ID = settings.payout_file_channel_id
ATTENDANCE_REWARD = 40_000
COMMENT = "Недельная премия"

# Временная зона МСК
MSK = timezone(timedelta(hours=3))

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
        guild = discord.Object(id=GUILD_ID)
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
        now_msk = datetime.now(MSK)
        # воскресенье (6), 23:30
        if not (now_msk.weekday() == 6 and now_msk.hour == 23 and now_msk.minute >= 30):
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

    @app_commands.command(
        name="предрасчет", description="Ручной предрасчёт за текущую неделю (МСК)"
    )
    @app_commands.checks.has_role(HIGH_STAFF_ROLE_ID)
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
        now_msk = datetime.now(MSK)
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
                GUILD_ID, week_start_msk.date(), payouts
            )
            if run["completed_at"]:
                return "Расчёт за эту неделю уже опубликован."
            payouts = [{**row, "amount": Decimal(row["amount"])} for row in run["payload"]]
        await self._send_results(payouts, week_end_msk, now_msk, run)
        if scheduled:
            await PayoutRepository(self.pool).finish(GUILD_ID, week_start_msk.date())
        return "Выплаты отправлены."

    async def _collect_payouts(self, start_utc: datetime, end_utc: datetime) -> List[Dict]:
        assert self.pool
        combined = await PayoutRepository(self.pool).totals(start_utc, end_utc, ATTENDANCE_REWARD)

        guild = self.bot.get_guild(GUILD_ID)
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
        embed_channel = self.bot.get_channel(PAYOUT_CHANNEL_ID)
        file_channel = self.bot.get_channel(PAYOUT_FILE_CHANNEL_ID)
        if not isinstance(embed_channel, discord.TextChannel) or not isinstance(
            file_channel, discord.TextChannel
        ):
            raise RuntimeError("Payout channels are unavailable")

        # Файл
        lines = ["staticId;amount;comment"]
        lines.extend(f"{p['static_id']};{int(round(p['amount']))};{COMMENT}" for p in payouts)
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
        embed.set_image(url=random.choice(IMAGE_POOL))

        repo = PayoutRepository(self.pool)
        if run is None or not run["embed_message_id"]:
            message = await embed_channel.send(embed=embed)
            if run:
                await repo.message_sent(GUILD_ID, run["week_start"], "embed", message.id)
        if run is None or not run["file_message_id"]:
            message = await file_channel.send(files=[file], content="Текстовый файл с выплатами")
            if run:
                await repo.message_sent(GUILD_ID, run["week_start"], "file", message.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Payouts(bot))
