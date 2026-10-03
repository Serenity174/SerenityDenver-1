import discord
from discord import app_commands
from discord.ext import commands

from serenity.config import get_settings
from serenity.services.access import staff
from serenity.ui.base import Modal, View

settings = get_settings()


class EmbedModal(Modal, title="Создание эмбеда"):
    def __init__(self):
        super().__init__()

        self.content_input = discord.ui.TextInput(
            label="Тэги и оглавление (над эмбедом)",
            placeholder=f"Тэги вводить в формате <@&ID-роли>. Как пример: ## Сбор <@&{settings.family_role_id}>! ",
            style=discord.TextStyle.long,
            max_length=500,
            required=False,
        )
        self.title_input = discord.ui.TextInput(
            label="Заголовок эмбеда",
            placeholder="Введите заголовок. Как пример: Изменения в семье!",
            max_length=256,
            required=False,
        )
        self.description_input = discord.ui.TextInput(
            label="Описание эмбеда",
            placeholder="Тут основной текст.",
            style=discord.TextStyle.long,
            max_length=4000,
            required=False,
        )
        self.image_input = discord.ui.TextInput(
            label="Ссылка на изображение (.png, .jpg и т.п.)",
            placeholder="https://example.com/image.png",
            max_length=500,
            required=False,
        )

        self.add_item(self.content_input)
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        content = self.content_input.value or None
        title = self.title_input.value or None
        description = self.description_input.value or None
        image_url = self.image_input.value or None

        embed = discord.Embed(
            title=title, description=description, color=discord.Color.from_rgb(255, 255, 255)
        )
        if image_url:
            embed.set_image(url=image_url)

        channel = interaction.channel
        await channel.send(content=content, embed=embed)
        await interaction.response.send_message("✅ Эмбед опубликован.", ephemeral=True)


class EmbedButtonView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Открыть окно", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedModal())


class EmbedCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="эмбед", description="Создать кастомный эмбед")
    @staff()
    async def эмбед(self, interaction: discord.Interaction):
        view = EmbedButtonView()
        await interaction.response.send_message(
            "Нажмите кнопку ниже, чтобы открыть окно эмбеда:", view=view, ephemeral=True
        )

    @эмбед.error
    async def эмбед_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.errors.MissingAnyRole):
            await interaction.response.send_message(
                "❌ У вас нет доступа к этой команде.", ephemeral=True
            )

    async def cog_load(self):
        self.bot.tree.add_command(self.эмбед, guild=discord.Object(id=settings.guild_id))


async def setup(bot):
    await bot.add_cog(EmbedCommand(bot))
