import io
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from justice.cogs.contracts import ContractOpenView
from justice.config import get_settings
from justice.repositories.jobs import JobRepository
from justice.services.contract_rules import active_slots
from justice.services.settings import enabled, images, option
from justice.services.settings import timezone as configured_timezone

settings = get_settings()

REMINDER_TEXT = (
    f"{settings.reminder_emoji}Через 10 минут сбор на семейном доме на контракты! Не забудь!"
)

IMAGE_URLS = [
    "https://i.imgur.com/pXkrhvF.png",
    "https://i.imgur.com/iyemRDR.png",
    "https://i.imgur.com/cvtVraa.png",
    "https://i.imgur.com/hAmsK59.png",
    "https://i.imgur.com/gnKKAv8.png",
    "https://i.imgur.com/AibZSaY.png",
    "https://i.imgur.com/bqGVF2q.png",
    "https://i.imgur.com/g8LTjn8.png",
    "https://i.imgur.com/OUUKW9J.png",
    "https://i.imgur.com/YveFtxx.png",
    "https://i.imgur.com/qwMPQGZ.png",
    "https://i.imgur.com/69tq1gV.png",
    "https://i.imgur.com/tu2IQt0.png",
    "https://i.imgur.com/G0XQKEr.png",
    "https://i.imgur.com/GJJnhgw.png",
]


class News(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _download_image(self, url: str) -> Optional[discord.File]:
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as response:
                    if response.status != 200:
                        return None
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type.startswith("image/"):
                        return None
                    data = await response.read()
        except Exception:
            return None

        return discord.File(io.BytesIO(data), filename="news.png")

    @app_commands.command(name="сбор", description="Создать сбор: укажи время")
    @app_commands.describe(time="Время сбора (например 22:30)")
    async def sbor(self, interaction: discord.Interaction, time: str):
        if settings.high_staff_role_id not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message(
                "У вас нет прав для запуска сбора.", ephemeral=True
            )
            return

        time_value = time.strip()
        if not time_value:
            await interaction.response.send_message("Укажите время: /сбор <время>.", ephemeral=True)
            return

        try:
            hour, minute = map(int, time_value.split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Укажите время в формате ЧЧ:ММ, например 22:30.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        image = random.choice(images("news_images", IMAGE_URLS))
        image_file = await self._download_image(image)
        embed = discord.Embed(
            title=f"Сбор из {active_slots()} человек для выполнения контракта к {time_value} ({configured_timezone().key}).",
            description=(
                "Те кто явятся жмут на плюс.\n"
                "Приоритет всегда у меньших рангов и у тех, кто за неделю меньше всего был на контрактах!"
            ),
            color=0xFFFAFA,
        )
        if image_file is not None:
            embed.set_image(url=f"attachment://{image_file.filename}")
        else:
            embed.set_image(url=image)

        channel = interaction.client.get_channel(settings.news_channel_id)
        if channel is None:
            await interaction.followup.send("Канал для сборов не найден.", ephemeral=True)
            return

        if image_file is not None:
            await channel.send(
                content=f"## Сбор <@&{settings.family_role_id}>!",
                embed=embed,
                file=image_file,
            )
        else:
            await channel.send(
                content=f"## Сбор <@&{settings.family_role_id}>!",
                embed=embed,
            )

        contract_created = False
        contract_id: Optional[int] = None
        contracts_cog = interaction.client.get_cog("ContractsCog")
        if not enabled("contracts"):
            contracts_cog = None
        if contracts_cog is not None:
            await contracts_cog.db.connect()
            await contracts_cog.db.upsert_user(
                interaction.user.id, contracts_cog._get_rank_from_member(interaction.user)
            )

            contract_embed = contracts_cog._build_embed(
                contract={
                    "host_id": interaction.user.id,
                    "closed": False,
                    "attendance_marked": False,
                    "created_at": datetime.now(timezone.utc),
                },
                signups=[],
            )
            contract_view = ContractOpenView(contracts_cog)
            contract_msg = await channel.send(embed=contract_embed, view=contract_view)
            contract_id = await contracts_cog.db.create_contract(
                channel.id, contract_msg.id, interaction.user.id
            )
            await contracts_cog.db.add_signup(contract_id, interaction.user.id)
            contract_created = True

        if contract_created and contract_id is not None:
            try:
                hours_str, minutes_str = time_value.split(":")
                event_time = datetime.now(configured_timezone()).replace(
                    hour=int(hours_str),
                    minute=int(minutes_str),
                    second=0,
                    microsecond=0,
                )
                if event_time <= datetime.now(configured_timezone()):
                    event_time += timedelta(days=1)
                remind_at = event_time - timedelta(minutes=option("reminder_minutes", 10))
                await JobRepository().schedule(
                    "contract_reminder",
                    str(contract_id),
                    {
                        "contract_id": contract_id,
                        "content": option("reminder_text", REMINDER_TEXT).replace(
                            "{minutes}", str(option("reminder_minutes", 10))
                        ),
                    },
                    remind_at,
                    event_time,
                )
            except ValueError:
                pass

        status = "Сбор опубликован!"
        if contract_created:
            status += " Создана карточка контракта."
        else:
            status += " (модуль контрактов недоступен)."
        await interaction.followup.send(status, ephemeral=True)

    async def cog_load(self):
        guild = discord.Object(id=settings.guild_id)
        self.bot.tree.add_command(self.sbor, guild=guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(News(bot))
