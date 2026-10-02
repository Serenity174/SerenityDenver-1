import discord
from discord import app_commands
from discord.ext import commands

from serenity.config import get_settings
from serenity.repositories.state import StateRepository
from serenity.services.workflows import promotion_target, submit_request
from serenity.ui.base import Modal, View

settings = get_settings()


class PromotionModal(Modal, title="Подать отчёт на повышение"):
    goods_and_metallurgy = discord.ui.TextInput(
        label="Явка на товары и Металлургию", required=False, max_length=1000
    )
    family_balance_top_up = discord.ui.TextInput(
        label="Пополнение баланса семьи", required=False, max_length=1000
    )
    time_in_family = discord.ui.TextInput(label="Как давно в семье?", max_length=1000)

    async def on_submit(self, interaction):
        try:
            target = promotion_target(interaction.user, settings.rank_role_ids)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        payload = {
            name: getattr(self, name).value
            for name in ("goods_and_metallurgy", "family_balance_top_up", "time_in_family")
        }
        payload["target_role_id"] = target
        embed = discord.Embed(title=f"{settings.promotion_emoji} Отчёт на Повышение")
        for name in ("goods_and_metallurgy", "family_balance_top_up", "time_in_family"):
            embed.add_field(
                name=getattr(self, name).label, value=payload[name] or "Не указано", inline=False
            )
        embed.add_field(name="Пользователь", value=interaction.user.mention)
        await submit_request(
            interaction, "promotion", payload, settings.promotion_channel_id, embed
        )


class NameChangeModal(Modal, title="Смена фамилии"):
    proof = discord.ui.TextInput(label="Доказательства смены фамилии", max_length=1000)

    async def on_submit(self, interaction):
        try:
            target = promotion_target(interaction.user, settings.rank_role_ids)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        embed = discord.Embed(
            title=f"{settings.promotion_emoji} Смена Фамилии", description=interaction.user.mention
        )
        embed.add_field(name="Доказательства", value=self.proof.value)
        await submit_request(
            interaction,
            "name_change",
            {"proof": self.proof.value, "target_role_id": target},
            settings.promotion_channel_id,
            embed,
        )


class PromotionView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Повыситься", style=discord.ButtonStyle.success, custom_id="submit_report_button"
    )
    async def promote(self, interaction, button):
        await interaction.response.send_modal(PromotionModal())

    @discord.ui.button(
        label="Сменил фамилию", style=discord.ButtonStyle.primary, custom_id="name_change_button"
    )
    async def name_change(self, interaction, button):
        await interaction.response.send_modal(NameChangeModal())


class Promotion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PromotionView())
        self.bot.tree.add_command(self.promotion, guild=discord.Object(id=settings.guild_id))

    @app_commands.command(name="повышение", description="Отправить форму на повышение")
    @app_commands.checks.has_role(settings.high_staff_role_id)
    async def promotion(self, interaction):
        channel = self.bot.get_channel(settings.promotion_channel_id)
        state = StateRepository()
        message_id = await state.get(settings.guild_id, "panels", "promotion")
        embed = discord.Embed(
            title="Подача отчёта на повышение",
            description="Проверьте выполнение условий и приложите доказательства.",
        )
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=PromotionView())
                return await interaction.response.send_message("Форма обновлена.", ephemeral=True)
            except discord.NotFound:
                pass
        message = await channel.send(embed=embed, view=PromotionView())
        await state.put(settings.guild_id, "panels", "promotion", message.id)
        await interaction.response.send_message("Форма отправлена.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Promotion(bot))
