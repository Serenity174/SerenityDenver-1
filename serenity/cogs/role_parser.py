import io

import discord
from discord import app_commands
from discord.ext import commands

from serenity.config import get_settings

settings = get_settings()


GUILD_ID = settings.guild_id


class RoleParser(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="участники",
        description="Получить список участников с выбранной ролью",
    )
    @app_commands.describe(role="Роль, чьих участников нужно вывести")
    async def participants(self, interaction: discord.Interaction, role: discord.Role):
        if interaction.guild is None or interaction.guild.id != GUILD_ID:
            await interaction.response.send_message(
                "Команда доступна только на сервере Serenity.", ephemeral=True
            )
            return

        members = [member for member in role.members if not member.bot]
        members.sort(key=lambda m: m.display_name.lower())

        if not members:
            await interaction.response.send_message(
                f"У роли {role.mention} нет участников.", ephemeral=True
            )
            return

        lines = [f"{member.display_name} ({member.id})" for member in members]
        output = "\n".join(lines)

        if len(output) < 1800:
            await interaction.response.send_message(
                f"Участники роли {role.mention}:\n```\n{output}\n```",
                ephemeral=True,
            )
        else:
            buffer = io.StringIO(output)
            file = discord.File(buffer, filename=f"{role.name}_members.txt")
            await interaction.response.send_message(
                content=f"Участники роли {role.mention}:", file=file, ephemeral=True
            )

    async def cog_load(self):
        guild = discord.Object(id=GUILD_ID)
        self.bot.tree.add_command(self.participants, guild=guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleParser(bot))
