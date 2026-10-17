import asyncio
import logging
import random
from typing import Dict

import discord
from discord.ext import commands

from justice.config import get_settings
from justice.repositories.state import StateRepository
from justice.services.settings import enabled, images, option

settings = get_settings()


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_cache: Dict[int, Dict[str, int]] = {}
        self._lock = asyncio.Lock()
        self.images = [
            "https://i.imgur.com/g5tNLY5.png",
            "https://i.imgur.com/pxIJf8W.png",
            "https://i.imgur.com/SsVtjXc.png",
            "https://i.imgur.com/J6Pd5ui.png",
            "https://i.imgur.com/5bXFrmr.png",
            "https://i.imgur.com/Giv1rhA.png",
            "https://i.imgur.com/2IEzQ8a.png",
            "https://i.imgur.com/4XLAYiu.png",
            "https://i.imgur.com/aJNnYUf.png",
            "https://i.imgur.com/zhesQKA.png",
            "https://i.imgur.com/nV1NP8W.png",
            "https://i.imgur.com/flLjtEL.png",
            "https://i.imgur.com/DqWjGkM.png",
            "https://i.imgur.com/od2Xpug.png",
            "https://i.imgur.com/n060Rxl.png",
            "https://i.imgur.com/Dyzd6Pf.png",
            "https://i.imgur.com/SZD7qiu.png",
            "https://i.imgur.com/ZvRXpHl.png",
            "https://i.imgur.com/hA3gAE8.png",
            "https://i.imgur.com/vsMl5CC.png",
            "https://i.imgur.com/6JmIt5a.png",
            "https://i.imgur.com/2zBwZvG.png",
            "https://i.imgur.com/5DssVBV.png",
        ]

    async def cog_load(self):
        saved = await StateRepository().get(settings.guild_id, "invites", "counts", {})
        self.invite_cache[settings.guild_id] = saved

    async def _refresh_invites(self):
        async with self._lock:
            for guild in self.bot.guilds:
                try:
                    invites = await guild.invites()
                except Exception:
                    continue
                self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in invites}
                await StateRepository().put(
                    guild.id, "invites", "counts", self.invite_cache[guild.id]
                )

    @commands.Cog.listener()
    async def on_ready(self):
        # Обновляем кэш инвайтов при старте.
        await self._refresh_invites()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        async with self._lock:
            await self._member_join_locked(member)

    async def _member_join_locked(self, member: discord.Member):
        if member.bot or member.guild.id != settings.guild_id:
            return

        guild = member.guild
        inviter = None

        try:
            invites_before = self.invite_cache.get(guild.id, {})
            invites_now = await guild.invites()
            for inv in invites_now:
                before_count = invites_before.get(inv.code, 0)
                now_count = inv.uses or 0
                if now_count > before_count:
                    inviter = inv.inviter
                    break
            # Обновляем кэш
            self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in invites_now}
            await StateRepository().put(guild.id, "invites", "counts", self.invite_cache[guild.id])
        except Exception:
            logging.getLogger(__name__).exception("Optional Discord action failed")

        await self.bot.database.pool.execute(
            "INSERT INTO public.invite_events(guild_id,user_id,inviter_id) VALUES($1,$2,$3)",
            guild.id,
            member.id,
            inviter.id if inviter else None,
        )

        if not enabled("welcome"):
            return

        channel = guild.get_channel(settings.welcome_channel_id) or self.bot.get_channel(
            settings.welcome_channel_id
        )
        if channel is None:
            return

        inviter_text = inviter.mention if inviter else "неизвестно"
        content = f"{member.mention} присоединяется к нам по приглашению {inviter_text}"

        description = (
            f"Для подачи заявки в нашу семью переходите в канал <#{settings.submit_channel_id}>.\n"
            "Для получения роли **Family Friends/Best Friend** обращайтесь к старшему составу семьи предварительно изменив ник по форме.\n"
            "`Пример: Friend Milo | Имя Static`\n\n"
            f"В канале <#{settings.bonus_channel_id}> Вы сможете получить приятный бонус за введённый промокод `/JUSTICE`.\n"
            "В разделе Guides собраны разного рода памятки, гайды и ссылки на полезные ресурсы.\n"
            "**Ждём именно твою заявку!**"
        )

        embed = discord.Embed(
            title=option("welcome_title", f"{settings.welcome_emoji} Добро пожаловать в Justice!"),
            description=option("welcome_text", description),
            color=discord.Color.from_rgb(255, 255, 255),
        )
        embed.set_image(url=random.choice(images("welcome_images", self.images)))

        try:
            await channel.send(content=content, embed=embed)
        except Exception:
            logging.getLogger(__name__).exception("Optional Discord action failed")


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
