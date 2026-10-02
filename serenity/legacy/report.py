import discord
from discord import app_commands, ui
from discord.ext import commands
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

from serenity.config import get_settings

settings = get_settings()

# === НАСТРОЙКИ ===
GUILD_ID = settings.guild_id
ROLE_ID = settings.high_staff_role_id
OUTPUT_CHANNEL_ID = settings.report_output_channel_id
INTERFACE_CHANNEL_ID = settings.report_interface_channel_id
SPREADSHEET_ID = settings.google_spreadsheet_id
SHEET_NAME = settings.report_sheet_name
JSON_PATH = str(settings.google_credentials_path)

ITEM_PRICES = {
    "Марлин": 0.858,
    "Красный горбыль": 0.858,
    "Тёмный горбыль": 0.793,
    "Железо": 61,
    "Серебро": 130,
    "Медь": 250,
    "Олово": 265,
    "Золото": 398,
    "Рубашки": 1400,
    "Апельсины": 44,
    "Шампиньоны": 82,
    "Гипсизикусы": 112,
    "Вешенки": 95,
    "Сосновые брёвна": 190,
    "Дубовые бревна": 231,
    "Пшеница": 364,
    "Мухоморы": 124,
    "Подболотники": 150,
    "Подберёзовики": 173,
    "Берёза": 280,
    "Клён": 337,
    "Картофель": 480,
    "Капуста": 641,
    "Кукуруза": 971,
    "Тыквы": 1208,
    "Бананы": 1882,
}


# === Google Sheets Авторизация ===
def get_worksheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_PATH, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)


# === Модальное окно ===
class ReportModal(ui.Modal, title="Подача отчёта"):
    nickname = ui.TextInput(label="Игровой никнейм", placeholder="Имя Фамилия")
    static_id = ui.TextInput(label="Статический ID")
    category: str
    quantity = ui.TextInput(label="Количество", placeholder="Введите число")
    proof = ui.TextInput(label="Доказательство", placeholder="Ссылка на скриншот")

    def __init__(self, category: str):
        super().__init__(title="Подача отчёта")
        self.category = category

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self.quantity.value.isdigit():
            return await interaction.followup.send(
                "❌ Введите целое число в поле количества.", ephemeral=True
            )

        if not self.static_id.value.isdigit():
            return await interaction.followup.send(
                "❌ Введите только цифры в поле статического ID.", ephemeral=True
            )

        qty = int(self.quantity.value)
        static_id = int(self.static_id.value)
        total = round(qty * ITEM_PRICES.get(self.category, 0), 2)

        ws = get_worksheet()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([now, self.nickname.value, static_id, self.category, qty, self.proof.value])

        ts = int(datetime.now().timestamp())
        embed = discord.Embed(
            title="Новый отчёт по складу!",
            color=discord.Color.from_rgb(255, 255, 255),
            description=(
                f"**Игрок:** {self.nickname.value}\n"
                f"**ID:** {static_id}\n"
                f"**Категория:** {self.category}\n"
                f"**Количество:** {qty}\n"
                f"**Сумма:** {total}$\n"
                f"**Доказательство:** [Скрин]({self.proof.value})\n"
                f"**Время:** <t:{ts}:R>"
            ),
        )
        await interaction.client.get_channel(OUTPUT_CHANNEL_ID).send(embed=embed)
        await interaction.followup.send("✅ Отчёт успешно отправлен!", ephemeral=True)

        iface = interaction.client.get_channel(INTERFACE_CHANNEL_ID)
        async for msg in iface.history(limit=50):
            if msg.author.id == interaction.client.user.id and msg.components:
                await msg.delete()
        view = ReportView(move_button=True)
        new_embed = discord.Embed(color=discord.Color.from_rgb(255, 255, 255))
        new_embed.set_image(url="https://i.ibb.co/8DYKVC1k/Get-Back-To-Work.png")
        await iface.send(embed=new_embed, view=view)


# === View с кнопками ===
class ReportView(ui.View):
    def __init__(self, move_button: bool = False):
        super().__init__(timeout=None)
        self.move_button = move_button

    @staticmethod
    def get_select_view(category_list):
        select = ui.Select(
            placeholder="Выберите категорию",
            options=[discord.SelectOption(label=item) for item in category_list],
        )

        async def select_callback(interaction: discord.Interaction):
            cat = select.values[0]
            await interaction.response.send_modal(ReportModal(cat))

        select.callback = select_callback
        view = ui.View(timeout=180)
        view.add_item(select)
        return view

    @ui.button(label="Основное", style=discord.ButtonStyle.green, custom_id="main_button")
    async def main(self, interaction: discord.Interaction, button: ui.Button):
        categories = [
            "Круглый Трахинот",
            "Полосатый Лаврак",
            "Барракуда",
            "Прибережный басс",
            "Снук",
            "Альбула",
            "Жерех",
            "Судак",
            "Голавль",
            "Железо",
            "Серебро",
            "Медь",
            "Олово",
            "Золото",
            "Рубашки",
        ]
        view = self.get_select_view(categories)
        await interaction.response.send_message("Выберите категорию:", view=view, ephemeral=True)

    @ui.button(label="Грибы", style=discord.ButtonStyle.blurple, custom_id="mushrooms_button")
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

    @ui.button(label="Брёвна", style=discord.ButtonStyle.blurple, custom_id="logs_button")
    async def logs(self, interaction: discord.Interaction, button: ui.Button):
        categories = ["Сосновые брёвна", "Дубовые бревна", "Берёза", "Клён"]
        view = self.get_select_view(categories)
        await interaction.response.send_message("Выберите категорию:", view=view, ephemeral=True)

    @ui.button(label="Ферма", style=discord.ButtonStyle.blurple, custom_id="farm_button")
    async def farm(self, interaction: discord.Interaction, button: ui.Button):
        categories = ["Апельсины", "Пшеница", "Картофель", "Капуста", "Кукуруза", "Тыквы", "Бананы"]
        view = self.get_select_view(categories)
        await interaction.response.send_message("Выберите категорию:", view=view, ephemeral=True)


# === Cog и регистрация ===
class Report(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="отчёт", description="Создаёт сообщение с кнопками подачи отчётов")
    async def report(self, interaction: discord.Interaction):
        if not any(r.id == ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message("❌ У тебя нет прав.", ephemeral=True)
        await interaction.response.send_message("Интерфейс создан", ephemeral=True)
        embed = discord.Embed(color=discord.Color.from_rgb(255, 255, 255))
        embed.set_image(url="https://i.ibb.co/8DYKVC1k/Get-Back-To-Work.png")
        await interaction.client.get_channel(INTERFACE_CHANNEL_ID).send(
            embed=embed, view=ReportView()
        )

    async def cog_load(self):
        guild = discord.Object(id=GUILD_ID)
        self.bot.tree.add_command(self.report, guild=guild)
        self.bot.add_view(ReportView())


async def setup(bot: commands.Bot):
    await bot.add_cog(Report(bot))
