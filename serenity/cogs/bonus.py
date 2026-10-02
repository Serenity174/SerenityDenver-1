import json

import discord
from discord.ext import commands
from discord.ui import Button, TextInput

from serenity.config import get_settings
from serenity.repositories.state import StateRepository
from serenity.services.workflows import submit_request
from serenity.ui.base import Modal, View

settings = get_settings()

# Путь к файлу для хранения ID сообщения с кнопкой
CACHE_FILE = settings.bonus_cache_path


# Модальное окно для ввода данных персонажа и доказательства
class PromoModal(Modal, title="Данные персонажа"):
    statik = TextInput(
        label="#StaticID",
        placeholder="Введите статический ID персонажа",
        style=discord.TextStyle.paragraph,
        required=True,
    )
    bank_account = TextInput(
        label="Номер банковского счёта",
        placeholder="Номер счёта можно посмотреть, открыв инвентарь и наведясь на банковскую карту",
        style=discord.TextStyle.paragraph,
        required=True,
    )
    proof = TextInput(
        label="Доказательство ввода промокода",
        placeholder="Вставьте ссылку на скриншот полного экрана, загруженного на Imgur/Yapix",
        style=discord.TextStyle.paragraph,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        target_channel_id = settings.bonus_channel_id

        embed = discord.Embed(title="📥 Новый ответ на бонусы", color=discord.Color.green())
        embed.add_field(name="Пользователь", value=interaction.user.mention, inline=False)
        embed.add_field(name="#StaticID", value=self.statik.value, inline=False)
        embed.add_field(name="Номер банковского счёта", value=self.bank_account.value, inline=False)
        embed.add_field(name="Доказательство ввода промокода", value=self.proof.value, inline=False)

        await submit_request(
            interaction,
            "bonus",
            {
                "static_id": self.statik.value,
                "bank_account": self.bank_account.value,
                "proof": self.proof.value,
            },
            target_channel_id,
            embed,
        )


# Кнопка для запуска модального окна
class PromoButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Получить бонусы",
        style=discord.ButtonStyle.primary,
        custom_id="promo:get_bonus",  # <-- обязательный параметр для persistent View
    )
    async def get_bonus(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PromoModal())


# Кэшированное сообщение с кнопкой
class PromoCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cached_message_id = None

    async def cog_load(self):
        state = StateRepository()
        self.cached_message_id = await state.get(settings.guild_id, "panels", "bonus")
        if self.cached_message_id is None and CACHE_FILE.exists():
            with CACHE_FILE.open(encoding="utf-8") as file:
                self.cached_message_id = json.load(file).get("message_id")
            if self.cached_message_id:
                await self.save_cached_message_id(self.cached_message_id)

    async def save_cached_message_id(self, message_id):
        await StateRepository().put(settings.guild_id, "panels", "bonus", message_id)

    async def send_embed_with_button(self, ctx):
        role_id = settings.high_staff_role_id
        support_role_id = settings.support_role_id
        if discord.utils.get(ctx.author.roles, id=role_id):
            embed = discord.Embed(
                title="Как получить бонусы за промокод?",
                description=(
                    "```1. Введите команду /promo SERENITY в игровой чат.\n"
                    "2. Сделайте полный скриншот с подтверждением ввода команды.\n"
                    "3. Отправьте скриншот в качестве доказательства активации.\n"
                    "4. Ожидайте уведомление о начислении бонуса.```\n"
                    f"<@&{support_role_id}> — выдаётся всем, кто использует промокод и поддерживает нашу семью "
                    "на сервере Seattle.\n"
                    "Также данная роль присваивается всем, кто оказал помощь семье. Это может быть финансовая помощь в развитии семьи, организация и участие в мероприятиях, предоставление ресурсов или любая иная значимая помощь, направленная на укрепление и развитие нашей семьи. Список не является исчерпывающим."
                ),
                color=discord.Color.from_rgb(255, 255, 255),
            )
            embed.set_image(url="https://i.imgur.com/46TDn4m.png")
            embed.set_footer(text="Регистрируйтесь и присоединяйтесь — мы ждём вас на Seattle!")

            channel = self.bot.get_channel(settings.bonus_channel_id)
            if channel:
                if self.cached_message_id:
                    try:
                        cached_message = await channel.fetch_message(self.cached_message_id)
                        await cached_message.edit(embed=embed, view=PromoButton())
                    except discord.NotFound:
                        message = await channel.send(embed=embed, view=PromoButton())
                        await self.save_cached_message_id(message.id)
                        self.cached_message_id = message.id
                else:
                    message = await channel.send(embed=embed, view=PromoButton())
                    await self.save_cached_message_id(message.id)
                    self.cached_message_id = message.id
        else:
            msg = await ctx.send("❌ У вас нет прав на использование этой команды.")
            await msg.delete(delay=5)

    @commands.command(name="madam")
    async def madam_command(self, ctx):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

        await self.send_embed_with_button(ctx)


# Асинхронная регистрация когы
async def setup(bot: commands.Bot):
    await bot.add_cog(PromoCommand(bot))
    bot.add_view(PromoButton())  # Регистрация persistent кнопки
