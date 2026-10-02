from datetime import datetime

import asyncpg
import discord
from discord import app_commands, ui
from discord.ext import commands

from serenity.config import get_settings
from serenity.repositories.reports import ReportRepository

# Reuse the same categories/prices and config from the existing report cog
from serenity.services.reporting import report_total
from serenity.ui.base import Modal, View

settings = get_settings()
ROLE_ID = settings.high_staff_role_id
OUTPUT_CHANNEL_ID = settings.report_output_channel_id
INTERFACE_CHANNEL_ID = settings.report_interface_channel_id
GUILD_ID = settings.guild_id

DATABASE_URL = settings.database_url


class DBReportModal(Modal, title="Подача отчёта в БД"):
    category: str
    quantity = ui.TextInput(label="Количество", placeholder="Введите число")
    proof = ui.TextInput(label="Доказательство", placeholder="Ссылка на скриншот")

    def __init__(self, category: str, db_pool: asyncpg.Pool | None):
        super().__init__(title="Подача отчёта в БД")
        self.category = category
        self.db_pool = db_pool

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self.quantity.value.isdigit():
            return await interaction.followup.send(
                "⚠️ Введите целое число в поле количества.", ephemeral=True
            )

        if not self.db_pool:
            return await interaction.followup.send(
                "⚠️ Подключение к базе данных не готово.", ephemeral=True
            )

        qty = int(self.quantity.value)
        static_id = interaction.user.id
        nickname = interaction.user.display_name
        try:
            total = report_total(self.category, qty)
        except ValueError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)

        ts = int(datetime.now().timestamp())
        embed = discord.Embed(
            title="Новый отчёт по складу (DB)!",
            color=discord.Color.from_rgb(255, 255, 255),
            description=(
                f"**Игрок:** {nickname}\n"
                f"**Профиль:** <@{static_id}>\n"
                f"**Категория:** {self.category}\n"
                f"**Количество:** {qty}\n"
                f"**Сумма:** {total}$\n"
                f"**Доказательство:** [Скрин]({self.proof.value})\n"
                f"**Время:** <t:{ts}:R>"
            ),
        )

        record_id = await ReportRepository(self.db_pool).create(
            interaction_id=interaction.id,
            nickname=nickname,
            static_id=static_id,
            category=self.category,
            quantity=qty,
            total=total,
            proof=self.proof.value,
            user_id=interaction.user.id,
            username=interaction.user.name,
        )
        if record_id is None:
            return await interaction.followup.send("Этот отчёт уже сохранён.", ephemeral=True)

        if record_id is not None:
            embed.set_footer(text=f"ID записи: {record_id}")

        await interaction.client.get_channel(OUTPUT_CHANNEL_ID).send(embed=embed)
        await interaction.followup.send("✅ Отчёт сохранён в базе данных.", ephemeral=True)

        # Обновить кнопки выбора
        iface = interaction.client.get_channel(INTERFACE_CHANNEL_ID)
        async for msg in iface.history(limit=50):
            if msg.author.id == interaction.client.user.id and msg.components:
                await msg.delete()
        view = DBReportView(db_pool=self.db_pool, move_button=True)
        new_embed = discord.Embed(color=discord.Color.from_rgb(255, 255, 255))
        new_embed.set_image(url="https://i.ibb.co/8DYKVC1k/Get-Back-To-Work.png")
        await iface.send(embed=new_embed, view=view)


class DeleteReportModal(Modal, title="Удалить запись из БД"):
    report_id = ui.TextInput(
        label="ID записи", placeholder="Число из таблицы reports", max_length=20
    )

    def __init__(self, db_pool: asyncpg.Pool | None):
        super().__init__(title="Удалить запись из БД")
        self.db_pool = db_pool

    async def on_submit(self, interaction: discord.Interaction):
        if not any(r.id == ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message(
                "Нет прав удалять записи.", ephemeral=True
            )
        if not self.db_pool:
            return await interaction.response.send_message("База недоступна.", ephemeral=True)

        try:
            report_id = int(self.report_id.value)
        except ValueError:
            return await interaction.response.send_message("ID должен быть числом.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    DELETE FROM public.reports
                    WHERE id = $1
                    RETURNING id, nickname, static_id, category, quantity, total
                    """,
                    report_id,
                )
        except Exception as e:
            await interaction.followup.send(f"Ошибка при удалении: {e}", ephemeral=True)
            return

        if not row:
            await interaction.followup.send("Запись с таким ID не найдена.", ephemeral=True)
            return

        await interaction.followup.send(
            f"Запись #{row['id']} ({row['nickname']}, {row['category']}, {row['quantity']} шт., {row['total']}$) удалена.",
            ephemeral=True,
        )


class DBReportView(View):
    def __init__(self, db_pool: asyncpg.Pool | None, move_button: bool = False):
        super().__init__(timeout=None)
        self.db_pool = db_pool
        self.move_button = move_button

    def get_select_view(self, category_list):
        select = ui.Select(
            placeholder="Выберите категорию",
            options=[discord.SelectOption(label=item) for item in category_list],
        )

        async def select_callback(interaction: discord.Interaction):
            cat = select.values[0]
            await interaction.response.send_modal(DBReportModal(cat, self.db_pool))

        select.callback = select_callback
        view = ui.View(timeout=180)
        view.add_item(select)
        return view

    @ui.button(label="Основное", style=discord.ButtonStyle.green, custom_id="db_main_button")
    async def main(self, interaction: discord.Interaction, button: ui.Button):
        categories = [
            "Марлин",
            "Красный горбыль",
            "Тёмный горбыль",
            "Железо",
            "Серебро",
            "Медь",
            "Олово",
            "Золото",
            "Рубашки",
        ]
        view = self.get_select_view(categories)
        await interaction.response.send_message("Выберите категорию:", view=view, ephemeral=True)

    @ui.button(label="Грибы", style=discord.ButtonStyle.blurple, custom_id="db_mushrooms_button")
    async def mushrooms(self, interaction: discord.Interaction, button: ui.Button):
        categories = [
            "Шампиньоны",
            "Вешенки",
            "Гипсизикусы",
            "Мухоморы",
            "Подболотники",
            "Подберёзовики",
        ]
        view = self.get_select_view(categories)
        await interaction.response.send_message("Выберите категорию:", view=view, ephemeral=True)

    @ui.button(label="Брёвна", style=discord.ButtonStyle.blurple, custom_id="db_logs_button")
    async def logs(self, interaction: discord.Interaction, button: ui.Button):
        categories = ["Сосновые брёвна", "Дубовые бревна", "Берёза", "Клён"]
        view = self.get_select_view(categories)
        await interaction.response.send_message("Выберите категорию:", view=view, ephemeral=True)

    @ui.button(label="Ферма", style=discord.ButtonStyle.blurple, custom_id="db_farm_button")
    async def farm(self, interaction: discord.Interaction, button: ui.Button):
        categories = ["Апельсины", "Пшеница", "Картофель", "Капуста", "Кукуруза", "Тыквы", "Бананы"]
        view = self.get_select_view(categories)
        await interaction.response.send_message("Выберите категорию:", view=view, ephemeral=True)

    @ui.button(label="🛠️", style=discord.ButtonStyle.secondary, custom_id="db_tools_button")
    async def manage_reports(self, interaction: discord.Interaction, button: ui.Button):
        if not any(r.id == ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message("Нет прав.", ephemeral=True)
        if not self.db_pool:
            return await interaction.response.send_message("База недоступна.", ephemeral=True)

        view = ManageReportsView(db_pool=self.db_pool)
        await interaction.response.send_message("Выберите действие:", view=view, ephemeral=True)


class ClearConfirmView(View):
    def __init__(self, db_pool: asyncpg.Pool | None):
        super().__init__(timeout=60)
        self.db_pool = db_pool

    @ui.button(label="Да, удалить", style=discord.ButtonStyle.danger, custom_id="db_clear_confirm")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if not any(r.id == ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message("⚠️ Нет доступа.", ephemeral=True)
        if not self.db_pool:
            return await interaction.response.send_message(
                "⚠️ Подключение к базе данных не готово.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("TRUNCATE TABLE public.reports")
            await interaction.followup.send("✅ Таблица `reports` очищена.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Ошибка очистки: {e}", ephemeral=True)
        finally:
            self.stop()

    @ui.button(label="Отмена", style=discord.ButtonStyle.secondary, custom_id="db_clear_cancel")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("❎ Отменено.", ephemeral=True)
        self.stop()


class ManageReportsView(View):
    def __init__(self, db_pool: asyncpg.Pool | None):
        super().__init__(timeout=60)
        self.db_pool = db_pool

    @ui.button(label="📂 Удалить запись", style=discord.ButtonStyle.secondary)
    async def delete_one(self, interaction: discord.Interaction, button: ui.Button):
        if not any(r.id == ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message(
                "Нет прав удалять записи.", ephemeral=True
            )
        if not self.db_pool:
            return await interaction.response.send_message("База недоступна.", ephemeral=True)
        await interaction.response.send_modal(DeleteReportModal(self.db_pool))
        self.stop()

    @ui.button(label="🗑️ Очистить всё", style=discord.ButtonStyle.secondary)
    async def clear_reports(self, interaction: discord.Interaction, button: ui.Button):
        if not any(r.id == ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message("Нет прав.", ephemeral=True)
        if not self.db_pool:
            return await interaction.response.send_message("База недоступна.", ephemeral=True)

        embed = discord.Embed(
            title="Подтвердите очистку",
            description=(
                "Вы точно хотите удалить данные Database?\n"
                "Удаление приведёт к полной отчистке отчётов для всех пользователей!"
            ),
            color=discord.Color.from_rgb(255, 255, 255),
        )
        await interaction.response.edit_message(
            embed=embed, content=None, view=ClearConfirmView(db_pool=self.db_pool)
        )


class ReportDB(commands.Cog):
    """Отдельный ког для отправки отчётов в базу данных (без Google Sheets)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_pool: asyncpg.Pool | None = None

    async def cog_load(self):
        self.db_pool = self.bot.database.pool
        guild = discord.Object(id=GUILD_ID)
        self.bot.tree.add_command(self.report_db, guild=guild)
        self.bot.add_view(DBReportView(db_pool=self.db_pool))

    @app_commands.command(
        name="report_db", description="Отчёт по складу с сохранением в базу данных"
    )
    async def report_db(self, interaction: discord.Interaction):
        if not any(r.id == ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message("⚠️ Нет доступа.", ephemeral=True)
        await interaction.response.send_message("Форма отправлена вам в ЛС.", ephemeral=True)
        embed = discord.Embed(color=discord.Color.from_rgb(255, 255, 255))
        embed.set_image(url="https://i.ibb.co/8DYKVC1k/Get-Back-To-Work.png")
        await interaction.client.get_channel(INTERFACE_CHANNEL_ID).send(
            embed=embed, view=DBReportView(db_pool=self.db_pool)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ReportDB(bot))
