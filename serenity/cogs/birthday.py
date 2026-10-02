import logging
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from serenity.config import get_settings
from serenity.database import get_database
from serenity.repositories.jobs import JobRepository
from serenity.repositories.state import StateRepository
from serenity.ui.base import Modal, View

settings = get_settings()
log = logging.getLogger(__name__)
MSK = ZoneInfo("Europe/Moscow")


def parse_birthday(value):
    if not re.fullmatch(r"\d{1,2}\.\d{1,2}", value.strip()):
        raise ValueError("Укажите дату в формате ДД.ММ.")
    day, month = map(int, value.strip().split("."))
    try:
        datetime(2000, month, day)
    except ValueError:
        raise ValueError("Такой даты не существует.") from None
    return day, month


class BirthdayModal(Modal, title="Укажите свою дату рождения"):
    birthday = discord.ui.TextInput(label="День рождения", placeholder="12.07", max_length=5)
    wish = discord.ui.TextInput(label="Пожелания", required=False, max_length=1000)

    async def on_submit(self, interaction):
        try:
            day, month = parse_birthday(self.birthday.value)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await get_database().pool.execute(
            """INSERT INTO public.birthdays(guild_id,user_id,day,month,wish)
            VALUES($1,$2,$3,$4,$5) ON CONFLICT(guild_id,user_id)
            DO UPDATE SET day=excluded.day,month=excluded.month,wish=excluded.wish,updated_at=now()""",
            interaction.guild_id,
            interaction.user.id,
            day,
            month,
            self.wish.value,
        )
        channel = interaction.client.get_channel(settings.birthday_channel_id)
        embed = discord.Embed(
            title="Новый день рождения!",
            description=(
                f"{settings.birthday_emoji} {interaction.user.mention} {day:02}.{month:02} празднует свой день рождения!\n"
                f"**Пожелания:** {self.wish.value or '—'}"
            ),
        )
        await channel.send(embed=embed)
        await interaction.followup.send("Дата сохранена.", ephemeral=True)


class BirthdayView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Указать дату", style=discord.ButtonStyle.primary, custom_id="birthday_button"
    )
    async def submit(self, interaction, button):
        await interaction.response.send_modal(BirthdayModal())


class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(BirthdayView())
        self.bot.tree.add_command(self.birthday_command, guild=discord.Object(id=settings.guild_id))
        self.check_birthdays.start()

    def cog_unload(self):
        self.check_birthdays.cancel()

    async def import_history(self):
        state = StateRepository()
        if await state.get(settings.guild_id, "imports", "birthdays"):
            return
        channel = self.bot.get_channel(settings.birthday_channel_id)
        if channel is None:
            raise RuntimeError("Birthday channel unavailable")
        count = 0
        async for message in channel.history(limit=None):
            if message.author.id != self.bot.user.id or not message.embeds:
                continue
            embed = message.embeds[0]
            if embed.title != "Новый день рождения!":
                continue
            match = re.search(
                r"<@!?(\d+)>\s+(\d{1,2}\.\d{1,2})\s+празднует", embed.description or ""
            )
            if not match:
                continue
            try:
                day, month = parse_birthday(match[2])
            except ValueError:
                continue
            wish = (embed.description or "").partition("**Пожелания:**")[2].strip()
            await self.bot.database.pool.execute(
                """INSERT INTO public.birthdays(guild_id,user_id,day,month,wish)
                VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING""",
                settings.guild_id,
                int(match[1]),
                day,
                month,
                wish,
            )
            count += 1
        await state.put(settings.guild_id, "imports", "birthdays", True)
        log.info("Birthday history imported: %s messages", count)

    @tasks.loop(minutes=5)
    async def check_birthdays(self):
        try:
            await self.import_history()
            now = datetime.now(MSK)
            rows = await self.bot.database.pool.fetch(
                "SELECT user_id FROM public.birthdays WHERE guild_id=$1 AND day=$2 AND month=$3",
                settings.guild_id,
                now.day,
                now.month,
            )
            expires = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            for row in rows:
                await JobRepository().schedule(
                    "channel_message",
                    f"birthday:{settings.guild_id}:{row['user_id']}:{now.date()}",
                    {
                        "channel_id": settings.birthday_channel_id,
                        "content": f"Сегодня <@{row['user_id']}> празднует день рождения! "
                        + random.choice(
                            [
                                "Желаем счастья, здоровья и радости!",
                                "Пусть сбудется всё, о чём мечтаешь!",
                            ]
                        ),
                    },
                    now,
                    expires,
                )
        except Exception:
            log.exception("Birthday scan failed; will retry")

    @check_birthdays.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="др", description="Отправить форму дней рождения")
    @app_commands.checks.has_role(settings.high_staff_role_id)
    async def birthday_command(self, interaction):
        channel = self.bot.get_channel(settings.birthday_channel_id)
        await channel.send(
            embed=discord.Embed(title="Укажите дату рождения! 🎂"), view=BirthdayView()
        )
        await interaction.response.send_message("Форма отправлена.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Birthday(bot))
