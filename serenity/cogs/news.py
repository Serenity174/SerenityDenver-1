import io
import random
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from serenity.cogs.contracts import ContractOpenView
from serenity.config import get_settings
from serenity.repositories.jobs import JobRepository

settings = get_settings()

ROLE_ID = settings.high_staff_role_id
CHANNEL_ID = settings.news_channel_id  # Канал для публикации
GUILD_ID = settings.guild_id  # Твой сервер
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
REMINDER_TEXT = (
    f"{settings.reminder_emoji}Через 10 минут сбор на семейном доме на контракты! Не забудь!"
)

IMAGE_URLS = [
    "https://i.ibb.co/tMxChfNL/Group-1.png",
    "https://i.ibb.co/j9PfYpGD/Group-2.png",
    "https://i.ibb.co/sd9yGfhP/Group-3.png",
    "https://i.ibb.co/GfjZHLcx/Group-4.png",
    "https://i.ibb.co/x8B3cC4X/Group-5.png",
    "https://i.ibb.co/zVMHCnQv/Group-6.png",
    "https://i.ibb.co/NntD7Ygj/Group-7.png",
    "https://i.ibb.co/tMcvTT3s/Group-8.png",
    "https://i.ibb.co/xWP44K3/Group-9.png",
    "https://i.ibb.co/ycvPfkp0/Group-10.png",
    "https://i.ibb.co/fVPYwct1/Group-12.png",
    "https://i.ibb.co/hRKb767H/Group-13.png",
    "https://i.ibb.co/Fq73vV6K/Group-14.png",
    "https://i.ibb.co/zLkd5ms/Group-15.png",
    "https://i.ibb.co/mVNXS0Mt/Group-16.png",
    "https://i.ibb.co/fVQJsJYD/Group-17.png",
    "https://i.ibb.co/JjggdDDT/Group-18.png",
    "https://i.ibb.co/GDRpBPx/Group-19.png",
    "https://i.ibb.co/cc5d8HDS/Group-20.png",
    "https://i.ibb.co/xSCDgbTC/Group-21.png",
    "https://i.ibb.co/wrFcHsFs/Group-22.png",
    "https://i.ibb.co/B25tyfjs/Group-23.png",
    "https://i.ibb.co/PvR8Dk77/Group-24.png",
    "https://i.ibb.co/xSDdBbgN/Group-25.png",
    "https://i.ibb.co/fY6MckQ4/Group-26.png",
    "https://i.ibb.co/WNZr3KBp/Group-27.png",
    "https://i.ibb.co/sSbn6C3/Group-28.png",
    "https://i.ibb.co/s9jQYBnd/Group-29.png",
    "https://i.ibb.co/TBb0JyPv/Group-30.png",
    "https://i.ibb.co/1t9G782y/Group-31.png",
    "https://i.ibb.co/4Ry9J53P/Group-32.png",
    "https://i.ibb.co/jkY9gzyG/Group-33.png",
    "https://i.ibb.co/jvGj0SNf/Group-34.png",
    "https://i.ibb.co/vxPw6FZQ/Group-36.png",
    "https://i.ibb.co/Q7HPfKMd/Group-37.png",
    "https://i.ibb.co/S71Mv4DC/Group-38.png",
    "https://i.ibb.co/zhYT0j7D/Group-39.png",
    "https://i.ibb.co/n8w4tGyd/Group-40.png",
    "https://i.ibb.co/fj5XBvG/Group-41.png",
    "https://i.ibb.co/qL9WHXRB/Group-42.png",
    "https://i.ibb.co/JjzvLxpT/Group-43.png",
    "https://i.ibb.co/WvYDbQyt/Group-44.png",
    "https://i.ibb.co/vxPrPLBG/Group-45.png",
    "https://i.ibb.co/TMQPHW8N/Group-46.png",
    "https://i.ibb.co/XxzDzMft/Group-47.png",
    "https://i.ibb.co/39ydV4TF/Group-48.png",
    "https://i.ibb.co/s9dLJsjQ/Group-49.png",
    "https://i.ibb.co/99pqcMbH/Group-50.png",
    "https://i.ibb.co/jkfVF4yY/Group-51.png",
    "https://i.ibb.co/pjPQ4L8m/Group-52.png",
    "https://i.ibb.co/0RcbwVcX/Group-53.png",
    "https://i.ibb.co/S7nKZN2b/Group-54.png",
    "https://i.ibb.co/9k28Y4wr/Group-55.png",
    "https://i.ibb.co/C56qv255/Group-56.png",
    "https://i.ibb.co/hxbd0dfm/Group-57.png",
    "https://i.ibb.co/Kz8zC2N6/Group-58.png",
    "https://i.ibb.co/xtbYn78r/Group-59.png",
    "https://i.ibb.co/HTVNffkJ/Group-60.png",
    "https://i.ibb.co/zW2P34vN/Group-61.png",
    "https://i.ibb.co/Zpgc8xtQ/Group-62.png",
    "https://i.ibb.co/9S7MZVT/Group-63.png",
    "https://i.ibb.co/M5WyMpbv/Group-64.png",
    "https://i.ibb.co/bgXqG1mZ/Group-65.png",
    "https://i.ibb.co/KxnfjF7q/Group-66.png",
    "https://i.ibb.co/fzK5XLL1/Group-67.png",
    "https://i.ibb.co/4nxhZJ5c/Group-68.png",
    "https://i.ibb.co/hksN0LD/Group-69.png",
    "https://i.ibb.co/pjpFd6zV/Group-70.png",
    "https://i.ibb.co/pBcb2pGG/Group-71.png",
    "https://i.ibb.co/gMzRM2YN/Group-72.png",
    "https://i.ibb.co/Zp9wzBBz/Group-73.png",
    "https://i.ibb.co/QFCkFfLD/Group-74.png",
    "https://i.ibb.co/LhsHsF5W/Group-75.png",
    "https://i.ibb.co/7NdjYjSc/Group-76.png",
    "https://i.ibb.co/hJ77P65x/Group-77.png",
    "https://i.ibb.co/NntvShF7/Group-78.png",
    "https://i.ibb.co/s9RZTtGB/Group-79.png",
    "https://i.ibb.co/Hf9m6tvQ/Group-80.png",
    "https://i.ibb.co/v6ZN92xX/Group-81.png",
    "https://i.ibb.co/23CB3dzC/Group-82.png",
    "https://i.ibb.co/SCZ4xP2/Group-83.png",
    "https://i.ibb.co/qMWpdXtd/Group-84.png",
    "https://i.ibb.co/p91j1K5/Group-85.png",
    "https://i.ibb.co/m5TgJ5hy/Group-86.png",
    "https://i.ibb.co/VWb6gy0j/Group-87.png",
    "https://i.ibb.co/WWW8HZjL/Group-88.png",
    "https://i.ibb.co/jKPmPhD/Group-89.png",
    "https://i.ibb.co/NnkVQ1jd/Group-90.png",
    "https://i.ibb.co/Nn9wX28S/Group-91.png",
    "https://i.ibb.co/tpn70ttv/Group-92.png",
    "https://i.ibb.co/hRcjDsHY/Group-93.png",
    "https://i.ibb.co/mLR31Lp/Group-94.png",
    "https://i.ibb.co/277BSc9m/Group-95.png",
    "https://i.ibb.co/rGBtL1L9/Group-96.png",
    "https://i.ibb.co/qMjXcC75/Group-97.png",
    "https://i.ibb.co/GfLrJg53/Group-98.png",
    "https://i.ibb.co/BVgmvVNX/Group-99.png",
    "https://i.ibb.co/RGskZZ1p/Group-100.png",
    "https://i.ibb.co/k7NBH58/Group-101.png",
    "https://i.ibb.co/fVKBxtx6/Group-102.png",
    "https://i.ibb.co/9m61mVCT/Group-103.png",
    "https://i.ibb.co/YvcfsCr/Group-104.png",
    "https://i.ibb.co/x8dwZTjd/Group-105.png",
    "https://i.ibb.co/xqdZFQkw/Group-106.png",
    "https://i.ibb.co/ycWkFdqT/Group-107.png",
    "https://i.ibb.co/q373Mc2J/Group-108.png",
    "https://i.ibb.co/KxPGSQBP/Group-109.png",
    "https://i.ibb.co/tw7mNvN0/Group-110.png",
    "https://i.ibb.co/Y4DywY3H/Group-111.png",
    "https://i.ibb.co/LdSVsyQ5/Group-112.png",
    "https://i.ibb.co/wZB8ypGq/Group-113.png",
    "https://i.ibb.co/qM7hhRSB/Group-114.png",
    "https://i.ibb.co/WWSpbhkH/Group-115.png",
    "https://i.ibb.co/S7yj0sc9/Group-116.png",
    "https://i.ibb.co/FLzDJvjW/Group-117.png",
    "https://i.ibb.co/GQXJ1cRL/Group-118.png",
    "https://i.ibb.co/XkZynjtW/Group-119.png",
    "https://i.ibb.co/JWxBVHzB/Group-120.png",
    "https://i.ibb.co/fzWW75wc/Group-121.png",
    "https://i.ibb.co/fVt6tDC6/Group-122.png",
    "https://i.ibb.co/tPBfFdSd/Group-123.png",
    "https://i.ibb.co/pvMMtQ1C/Group-124.png",
    "https://i.ibb.co/7JF6Sjp7/Group-125.png",
    "https://i.ibb.co/MxprJMhL/Group-126.png",
    "https://i.ibb.co/wZf2GGh7/Group-127.png",
    "https://i.ibb.co/SX3691fN/Group-128.png",
    "https://i.ibb.co/M5j5pCzp/Group-129.png",
    "https://i.ibb.co/0RZsRsCN/Group-130.png",
    "https://i.ibb.co/KxLDg7kz/Group-131.png",
    "https://i.ibb.co/Z7Jzp4h/Group-132.png",
    "https://i.ibb.co/B2ZqG3sc/Group-133.png",
    "https://i.ibb.co/BKZTVR4z/Group-134.png",
    "https://i.ibb.co/DD5CqLJc/Group-135.png",
    "https://i.ibb.co/QFfWyvTZ/Group-136.png",
    "https://i.ibb.co/Wv2tWgnW/Group-137.png",
    "https://i.ibb.co/kgHLKYC2/Group-138.png",
    "https://i.ibb.co/pj3PmtJ9/Group-139.png",
    "https://i.ibb.co/ynyhKNG9/Group-140.png",
    "https://i.ibb.co/d4S10GYz/Group-141.png",
    "https://i.ibb.co/3yYBdm45/Group-142.png",
    "https://i.ibb.co/chc5Bs1Z/Group-143.png",
    "https://i.ibb.co/R8QK13R/Group-144.png",
    "https://i.ibb.co/SDnyqkvC/Group-145.png",
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
        if ROLE_ID not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message(
                "У вас нет прав для запуска сбора.", ephemeral=True
            )
            return

        time_value = time.strip()
        if not time_value:
            await interaction.response.send_message("Укажите время: /сбор <время>.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        image = random.choice(IMAGE_URLS)
        image_file = await self._download_image(image)
        embed = discord.Embed(
            title=f"Сбор из 5 человек для выполнения контракта к {time_value} по московскому времени.",
            description=(
                "Те кто явятся жмут на плюс.\n"
                "Приоритет всегда у меньших рангов и у тех, кто за неделю меньше всего был на контрактах!"
            ),
            color=discord.Color.from_rgb(255, 255, 255),
        )
        if image_file is not None:
            embed.set_image(url=f"attachment://{image_file.filename}")
        else:
            embed.set_image(url=image)

        channel = interaction.client.get_channel(CHANNEL_ID)
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
                event_time = datetime.now(MOSCOW_TZ).replace(
                    hour=int(hours_str),
                    minute=int(minutes_str),
                    second=0,
                    microsecond=0,
                )
                if event_time <= datetime.now(MOSCOW_TZ):
                    event_time += timedelta(days=1)
                remind_at = event_time - timedelta(minutes=10)
                await JobRepository().schedule(
                    "contract_reminder",
                    str(contract_id),
                    {"contract_id": contract_id, "content": REMINDER_TEXT},
                    remind_at,
                    event_time,
                )
            except ValueError:
                pass

        status = "Сбор опубликован!"
        if contract_created:
            status += " Создана карточка заявки в contracts."
        else:
            status += " (contracts не созданы: cog не найден)."
        await interaction.followup.send(status, ephemeral=True)

    async def cog_load(self):
        guild = discord.Object(id=GUILD_ID)
        self.bot.tree.add_command(self.sbor, guild=guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(News(bot))
