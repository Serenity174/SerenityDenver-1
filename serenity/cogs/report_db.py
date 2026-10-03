from datetime import datetime

import asyncpg
import discord
from discord import app_commands, ui
from discord.ext import commands

from serenity.config import get_settings
from serenity.repositories.reports import ReportRepository

# Reuse the same categories/prices and config from the existing report cog
from serenity.services.reporting import report_total
from serenity.services.settings import prices
from serenity.ui.base import Modal, View

settings = get_settings()


class DBReportModal(Modal, title="Подача отчёта"):
    category: str
    quantity = ui.TextInput(label="Количество", placeholder="Введите число")
    proof = ui.TextInput(label="Доказательство", placeholder="Ссылка на скриншот")

    def __init__(self, category: str, db_pool: asyncpg.Pool | None):
        super().__init__(title="Подача отчёта")
        self.category = category
        self.db_pool = db_pool

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self.quantity.value.isascii() or not self.quantity.value.isdigit():
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
            title="Новый отчёт по складу",
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
            publication={"channel_id": settings.report_output_channel_id, "embed": embed.to_dict()},
        )
        if record_id is None:
            return await interaction.followup.send("Этот отчёт уже сохранён.", ephemeral=True)

        if record_id is not None:
            embed.set_footer(text=f"ID записи: {record_id}")

        await interaction.followup.send(
            "✅ Отчёт сохранён. Сообщение появится в канале в течение нескольких секунд.",
            ephemeral=True,
        )


class DeleteReportModal(Modal, title="Удалить отчёт"):
    report_id = ui.TextInput(
        label="ID записи", placeholder="Номер из сообщения с отчётом", max_length=20
    )

    def __init__(self, db_pool: asyncpg.Pool | None):
        super().__init__(title="Удалить отчёт")
        self.db_pool = db_pool

    async def on_submit(self, interaction: discord.Interaction):
        if not any(r.id == settings.high_staff_role_id for r in interaction.user.roles):
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
        category_list = [name for name in category_list if name in prices()]
        if not category_list:
            view = ui.View(timeout=180)
            view.add_item(ui.Button(label="В этой группе нет категорий", disabled=True))
            return view
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

    @ui.button(
        label="Все категории",
        style=discord.ButtonStyle.primary,
        custom_id="report_all_categories",
        row=1,
    )
    async def all_categories(self, interaction, button):
        await interaction.response.send_message(
            "Выберите категорию:", view=CategoryPicker(self.db_pool), ephemeral=True
        )

    @ui.button(label="🛠️", style=discord.ButtonStyle.secondary, custom_id="db_tools_button")
    async def manage_reports(self, interaction: discord.Interaction, button: ui.Button):
        if not any(r.id == settings.high_staff_role_id for r in interaction.user.roles):
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
        if not any(r.id == settings.high_staff_role_id for r in interaction.user.roles):
            return await interaction.response.send_message("⚠️ Нет доступа.", ephemeral=True)
        if not self.db_pool:
            return await interaction.response.send_message(
                "⚠️ Подключение к базе данных не готово.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("TRUNCATE TABLE public.reports")
            await interaction.followup.send("✅ Все отчёты удалены.", ephemeral=True)
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
        if not any(r.id == settings.high_staff_role_id for r in interaction.user.roles):
            return await interaction.response.send_message(
                "Нет прав удалять записи.", ephemeral=True
            )
        if not self.db_pool:
            return await interaction.response.send_message("База недоступна.", ephemeral=True)
        await interaction.response.send_modal(DeleteReportModal(self.db_pool))
        self.stop()

    @ui.button(label="🗑️ Очистить всё", style=discord.ButtonStyle.secondary)
    async def clear_reports(self, interaction: discord.Interaction, button: ui.Button):
        if not any(r.id == settings.high_staff_role_id for r in interaction.user.roles):
            return await interaction.response.send_message("Нет прав.", ephemeral=True)
        if not self.db_pool:
            return await interaction.response.send_message("База недоступна.", ephemeral=True)

        embed = discord.Embed(
            title="Подтвердите очистку",
            description=(
                "Удалить все отчёты?\n"
                "Удаление приведёт к полной очистке отчётов для всех пользователей!"
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
        guild = discord.Object(id=settings.guild_id)
        self.bot.tree.add_command(self.report_db, guild=guild)
        self.bot.add_view(DBReportView(db_pool=self.db_pool))

    @app_commands.command(
        name="report_db", description="Отчёт по складу с сохранением в базу данных"
    )
    async def report_db(self, interaction: discord.Interaction):
        if not any(r.id == settings.high_staff_role_id for r in interaction.user.roles):
            return await interaction.response.send_message("⚠️ Нет доступа.", ephemeral=True)
        from serenity.services.panels import publish_panel

        await interaction.response.defer(ephemeral=True)
        await publish_panel(interaction.client, "reports")
        await interaction.followup.send(
            "Панель отчётов обновлена в настроенном канале.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ReportDB(bot))


class CategoryPicker(View):
    def __init__(self, pool, page=0):
        super().__init__(timeout=180)
        categories = list(prices())
        select = ui.Select(
            placeholder="Категория",
            options=[
                discord.SelectOption(label=name, value=name)
                for name in categories[page * 25 : (page + 1) * 25]
            ],
        )

        async def callback(interaction):
            await interaction.response.send_modal(DBReportModal(select.values[0], pool))

        select.callback = callback
        self.add_item(select)
        for label, destination in (("Назад", page - 1), ("Далее", page + 1)):
            if 0 <= destination < (len(categories) + 24) // 25:
                button = ui.Button(label=label)

                async def navigate(interaction, target=destination):
                    await interaction.response.edit_message(view=CategoryPicker(pool, target))

                button.callback = navigate
                self.add_item(button)
