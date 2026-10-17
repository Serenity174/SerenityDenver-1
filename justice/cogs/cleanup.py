import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from justice.ui.base import reply

log = logging.getLogger(__name__)


class Cleanup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.locks = {}

    @app_commands.command(
        name="очистить",
        description="Удалить сообщения от указанного ID включительно до момента вызова команды",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(
        manage_messages=True, read_message_history=True, view_channel=True
    )
    @app_commands.describe(сообщение="ID сообщения в текущем канале, с которого начать удаление")
    async def clear(self, interaction: discord.Interaction, сообщение: str):
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await reply(interaction, "Команда доступна в текстовых каналах и ветках.")
            return
        raw_id = сообщение.strip()
        if not raw_id.isascii() or not raw_id.isdecimal() or not 0 < int(raw_id) < interaction.id:
            await reply(interaction, "Укажите корректный ID сообщения, отправленного до команды.")
            return
        message_id = int(raw_id)
        lock = self.locks.setdefault(channel.id, asyncio.Lock())
        if lock.locked():
            await reply(interaction, "В этом канале уже выполняется очистка.")
            return
        async with lock:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                await channel.fetch_message(message_id)
            except discord.NotFound:
                await reply(interaction, "Сообщение не найдено в текущем канале. Проверьте ID.")
                return
            except discord.Forbidden:
                await reply(interaction, "У бота нет доступа к сообщению или истории канала.")
                return
            try:
                deleted = await channel.purge(
                    limit=None,
                    after=discord.Object(id=message_id - 1),
                    before=discord.Object(id=interaction.id),
                    oldest_first=False,
                    reason=f"Cleanup requested by {interaction.user.id}; boundary {message_id}",
                )
            except discord.HTTPException:
                log.exception("Cleanup failed channel=%s boundary=%s", channel.id, message_id)
                await reply(
                    interaction,
                    "Не удалось завершить очистку. Часть сообщений могла быть удалена. "
                    "Проверьте права бота и повторите команду.",
                )
                return
        log.info(
            "Cleanup channel=%s actor=%s boundary=%s deleted=%s",
            channel.id,
            interaction.user.id,
            message_id,
            len(deleted),
        )
        await reply(interaction, f"Удалено сообщений: {len(deleted)}.")

    async def cog_load(self):
        self.bot.tree.add_command(self.clear, guild=discord.Object(id=self.bot.settings.guild_id))


async def setup(bot):
    await bot.add_cog(Cleanup(bot))
