import discord
from discord.ext import commands
from discord import app_commands

from serenity.config import get_settings

settings = get_settings()

# ID твоего сервера для регистрации slash-команд
GUILD_ID = settings.guild_id  # <-- Замени на свой

# Временное хранилище заявок
user_applications = {}


class Page1Modal(discord.ui.Modal, title="Заявка - Страница 1"):
    name = discord.ui.TextInput(label="Ваше имя (ИРЛ)", placeholder="Иван Иванов")
    age = discord.ui.TextInput(label="Ваш возраст (ИРЛ)", placeholder="27 лет")
    hobby = discord.ui.TextInput(label="Хобби помимо GTA", placeholder="Пашу на заводе")
    online = discord.ui.TextInput(label="Средний онлайн в день", placeholder="от 2 часов")
    nickname = discord.ui.TextInput(label="Готовы сменить ник в игре?", placeholder="Да / Нет")

    async def on_submit(self, interaction: discord.Interaction):
        user_applications[interaction.user.id] = {
            "Имя": self.name.value,
            "Возраст": self.age.value,
            "Хобби": self.hobby.value,
            "Онлайн": self.online.value,
            "Сменить ник": self.nickname.value,
        }
        await interaction.response.send_message(
            "**⚡ Страница 1 из 3 заполнена.** Нажмите кнопку ниже для продолжения. У вас есть 1 минута.",
            view=NextStepView(),
            ephemeral=True,
        )


class Page2Modal(discord.ui.Modal, title="Заявка - Страница 2"):
    current_nick = discord.ui.TextInput(label="Какой ник сейчас в игре?", placeholder="Blake Stone")
    families = discord.ui.TextInput(
        label="В каких семьях были ранее?", placeholder="DiWhite, Margiella"
    )
    shooting = discord.ui.TextInput(label="Процент стрельбы", placeholder="100%")
    donate = discord.ui.TextInput(label="Готовы вкладывать в семью?", placeholder="Да, почему нет")
    war = discord.ui.TextInput(label="Желаете участвовать в каптах?", placeholder="Нет, я фармила")

    async def on_submit(self, interaction: discord.Interaction):
        data = user_applications.get(interaction.user.id, {})
        data.update(
            {
                "Ник в игре": self.current_nick.value,
                "Семьи": self.families.value,
                "Стрельба": self.shooting.value,
                "Донат": self.donate.value,
                "Капты": self.war.value,
            }
        )
        user_applications[interaction.user.id] = data
        await interaction.response.send_message(
            "**⚡ Страница 2 из 3 заполнена.** Нажмите кнопку ниже для продолжения. У вас есть 1 минута.",
            view=FinalStepView(),
            ephemeral=True,
        )


class Page3Modal(discord.ui.Modal, title="Заявка - Страница 3"):
    server = discord.ui.TextInput(label="Любимый сервер", placeholder="Seattle")
    other = discord.ui.TextInput(label="Где ещё играли?", placeholder="GTA 5 RP")

    async def on_submit(self, interaction: discord.Interaction):
        data = user_applications.get(interaction.user.id, {})
        data.update({"Любимый сервер": self.server.value, "Где ещё играли": self.other.value})

        embed = discord.Embed(title="📥 Новая заявка", color=discord.Color.blue())
        for key, value in data.items():
            embed.add_field(name=key, value=value, inline=False)
        embed.set_footer(text=f"Отправитель: {interaction.user}")

        # Канал для заявок: замени на свой
        log_channel = interaction.guild.get_channel(settings.application_channel_id)
        if log_channel:
            await log_channel.send(embed=embed)

        await interaction.response.send_message(
            "✅ Ваша заявка успешно отправлена!", ephemeral=True
        )
        user_applications.pop(interaction.user.id, None)


class StartView(discord.ui.View):
    @discord.ui.button(label="Начать заявку", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(Page1Modal())


class NextStepView(discord.ui.View):
    @discord.ui.button(label="НАЧАТЬ ЗАНОВО", style=discord.ButtonStyle.danger)
    async def restart(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_applications.pop(interaction.user.id, None)
        await interaction.response.send_modal(Page1Modal())

    @discord.ui.button(label=">> СЛЕДУЮЩАЯ", style=discord.ButtonStyle.success)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(Page2Modal())


class FinalStepView(discord.ui.View):
    @discord.ui.button(label="НАЧАТЬ ЗАНОВО", style=discord.ButtonStyle.danger)
    async def restart(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_applications.pop(interaction.user.id, None)
        await interaction.response.send_modal(Page1Modal())

    @discord.ui.button(label=">> СЛЕДУЮЩАЯ", style=discord.ButtonStyle.success)
    async def final(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(Page3Modal())


class Zayavki(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="заявка", description="Открывает меню подачи заявки")
    async def заявка_slash(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Нажмите на кнопку ниже, чтобы начать подачу заявки", view=StartView()
        )

    async def cog_load(self):
        guild = discord.Object(id=GUILD_ID)
        # Добавляем application command (sync происходит в main.py)
        self.bot.tree.add_command(self.заявка_slash, guild=guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(Zayavki(bot))
