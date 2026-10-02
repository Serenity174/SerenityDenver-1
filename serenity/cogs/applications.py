import discord
from discord.ext import commands

from serenity.config import get_settings
from serenity.repositories.requests import RequestRepository
from serenity.services.workflows import can_review, submit_request
from serenity.ui.base import Modal, View
from serenity.ui.requests import RequestView

settings = get_settings()


class ApplicationModal(Modal, title="Подача заявки в Serenity"):
    nickname = discord.ui.TextInput(
        label="RP имя, StaticID, имя и возраст IRL",
        max_length=1000,
        style=discord.TextStyle.paragraph,
    )
    experience = discord.ui.TextInput(
        label="Был ли опыт в государственных семьях?",
        max_length=1000,
        style=discord.TextStyle.paragraph,
    )
    reasons = discord.ui.TextInput(
        label="Почему выбрали нашу семью?", max_length=1000, style=discord.TextStyle.paragraph
    )
    discovery = discord.ui.TextInput(
        label="Как узнали о нашей семье?", max_length=1000, style=discord.TextStyle.paragraph
    )
    expectations = discord.ui.TextInput(
        label="Какие ожидания от семьи?", max_length=1000, style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction):
        if interaction.guild_id != settings.guild_id:
            return await interaction.response.send_message(
                "Форма доступна на сервере семьи.", ephemeral=True
            )
        payload = {
            name: getattr(self, name).value
            for name in ("nickname", "experience", "reasons", "discovery", "expectations")
        }
        embed = discord.Embed(
            title="Новая заявка на вступление в Serenity",
            color=discord.Color.from_rgb(255, 255, 255),
        )
        for name in payload:
            embed.add_field(name=getattr(self, name).label, value=payload[name], inline=False)
        embed.add_field(name="Пользователь", value=interaction.user.mention)
        await submit_request(
            interaction, "application", payload, settings.application_channel_id, embed
        )


class ApplicationView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Подать заявку", style=discord.ButtonStyle.primary, custom_id="submit_application"
    )
    async def submit(self, interaction, button):
        await interaction.response.send_modal(ApplicationModal())


class Applications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ApplicationView())
        for row in await RequestRepository().pending(
            ["application", "promotion", "name_change", "bonus"]
        ):
            self.bot.add_view(RequestView(row["id"]), message_id=row["message_id"])
        self.bot.spawn(self.restore_history(), name="restore-requests")

    async def restore_history(self):
        import asyncio
        import logging

        from serenity.services.history_import import (
            import_pending_requests,
            recover_request_messages,
        )

        while not self.bot.is_closed():
            try:
                await recover_request_messages(self.bot)
                await import_pending_requests(self.bot)
                return
            except Exception:
                logging.getLogger(__name__).exception("Request restoration failed; retrying")
                await asyncio.sleep(60)

    @commands.command(name="new")
    async def new(self, ctx):
        if not can_review(ctx.author):
            return await ctx.send("Нет прав для публикации формы.")
        channel = self.bot.get_channel(settings.submit_channel_id)
        embed = discord.Embed(
            title="Заявка на вступление в семью Serenity",
            description="Ответьте на вопросы и ожидайте рассмотрения старшим составом.",
            color=discord.Color.from_rgb(255, 255, 255),
        )
        embed.set_image(url="https://i.ibb.co/nNTmPtQK/image.png")
        await channel.send(embed=embed, view=ApplicationView())


async def setup(bot):
    await bot.add_cog(Applications(bot))
