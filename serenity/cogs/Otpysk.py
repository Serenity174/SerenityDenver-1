import discord
from discord import app_commands
from discord.ext import commands

from serenity.config import get_settings
from serenity.repositories.requests import RequestRepository
from serenity.ui.base import Modal, View

settings = get_settings()


class VacationModal(Modal, title="Оформление отпуска"):
    period = discord.ui.TextInput(
        label="Период отпуска", placeholder="С 01.01 по 12.01", max_length=100
    )
    reason = discord.ui.TextInput(
        label="Причина отсутствия", style=discord.TextStyle.paragraph, max_length=300
    )

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        role = interaction.guild.get_role(settings.vacation_role_id)
        if role is None:
            return await interaction.followup.send("Роль отпуска не найдена.", ephemeral=True)
        repo = RequestRepository()
        row, created = await repo.create(
            interaction.guild_id,
            interaction.user.id,
            "vacation",
            {"period": self.period.value, "reason": self.reason.value},
            interaction.id,
        )
        async with repo.locked(row["id"]) as (_, current):
            if current["status"] != "pending":
                return await interaction.followup.send("Этот отпуск уже завершён.", ephemeral=True)
            await interaction.user.add_roles(role, reason=f"Отпуск #{row['id']}")
        if created:
            channel = interaction.client.get_channel(settings.vacation_channel_id)
            message = await channel.send(
                embed=discord.Embed(
                    title="🛫 Новый отпуск",
                    description=(
                        f"{interaction.user.mention}\nПериод: {self.period.value}\nПричина: {self.reason.value}"
                    ),
                )
            )
            await repo.attach_message(row["id"], channel.id, message.id)
        await interaction.followup.send("Отпуск сохранён, роль выдана.", ephemeral=True)


class VacationButtons(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Отпуск", style=discord.ButtonStyle.secondary, custom_id="vacation_request"
    )
    async def request(self, interaction, button):
        await interaction.response.send_modal(VacationModal())

    @discord.ui.button(
        label="Вернулся/лась", style=discord.ButtonStyle.secondary, custom_id="vacation_return"
    )
    async def returned(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        repo = RequestRepository()
        rows = await repo.pool.fetch(
            "SELECT id FROM public.requests WHERE guild_id=$1 AND user_id=$2 AND kind='vacation' AND status='pending'",
            interaction.guild_id,
            interaction.user.id,
        )
        role = interaction.guild.get_role(settings.vacation_role_id)
        for row in rows:
            async with repo.locked(row["id"]) as (conn, current):
                if current["status"] == "pending":
                    if role:
                        await interaction.user.remove_roles(role, reason="Возвращение из отпуска")
                    await repo.finish(conn, row["id"], "returned", interaction.user.id)
        if not rows and role and role in interaction.user.roles:
            # Supports vacations granted before the database migration.
            await interaction.user.remove_roles(role, reason="Возвращение из отпуска")
            row, _ = await repo.create(
                interaction.guild_id,
                interaction.user.id,
                "vacation",
                {"legacy": True},
                interaction.id,
            )
            async with repo.locked(row["id"]) as (conn, _):
                await repo.finish(conn, row["id"], "returned", interaction.user.id)
        await interaction.followup.send("Добро пожаловать обратно!", ephemeral=True)


class Otpysk(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(VacationButtons())
        self.bot.tree.add_command(self.otpysk, guild=discord.Object(id=settings.guild_id))

    @app_commands.command(name="отпуск", description="Опубликовать форму отпуска")
    @app_commands.checks.has_role(settings.high_staff_role_id)
    async def otpysk(self, interaction):
        channel = self.bot.get_channel(settings.vacation_channel_id)
        await channel.send(
            embed=discord.Embed(
                title="Оформление отпуска",
                description="Укажите период и причину. По возвращении снимите роль кнопкой ниже.",
            ),
            view=VacationButtons(),
        )
        await interaction.response.send_message("Форма отправлена.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Otpysk(bot))
