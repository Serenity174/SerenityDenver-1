import discord
from discord import app_commands
from discord.ext import commands

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from serenity.config import get_settings

settings = get_settings()

# === НАСТРОЙКИ ===
GUILD_ID = settings.guild_id  # твой сервер
ROLE_ID = settings.high_staff_role_id  # кто может ставить явку
JSON_PATH = str(settings.google_credentials_path)  # тот же json, что и в report.py
SPREADSHEET_ID = settings.google_spreadsheet_id

SHEET_NAME = settings.attendance_sheet_name
COLUMN_NAME_METALL = "Металл"
COLUMN_NAME_GOODS = "Самолёт"  # колонка для "Товаров"
ID_COLUMN_NAME = "Discord"  # столбец с discord ID (числа / <@ID>)
NICKNAME_COLUMN_NAME = "Nickname"
ID_NUM_COLUMN_NAME = "ID"
RANK_COLUMN_NAME = "Ранг"

LOG_CHANNEL_ID = settings.attendance_log_channel_id  # канал логов явки

# маппинг: ID роли -> числовой ранг из таблицы
ROLE_RANK_MAP = {
    role_id: rank for rank, role_id in enumerate(settings.rank_role_ids, start=1) if rank >= 2
}


# ======== Работа с Google Sheets =========


def get_worksheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_PATH, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)


def find_row_by_discord_id(ws, discord_id: int):
    """Находим строку игрока по Discord ID в колонке ID_COLUMN_NAME."""
    header = ws.row_values(1)

    try:
        id_col_index = header.index(ID_COLUMN_NAME) + 1
    except ValueError:
        raise RuntimeError(f"В листе '{SHEET_NAME}' не найден столбец '{ID_COLUMN_NAME}'")

    col_values = ws.col_values(id_col_index)

    for row_index, value in enumerate(col_values, start=1):
        if row_index == 1:
            continue  # заголовок
        if not value:
            continue

        value = value.strip()

        # если в столбце просто число
        if value == str(discord_id):
            return row_index

        # если вдруг там <@1234567890> или <@!1234567890>
        if value.startswith("<@") and value.endswith(">"):
            inner = value[2:-1].lstrip("!")
            if inner == str(discord_id):
                return row_index

    return None


def get_column_index_by_name(ws, column_name: str) -> int:
    header = ws.row_values(1)
    try:
        return header.index(column_name) + 1
    except ValueError:
        raise RuntimeError(f"В листе '{SHEET_NAME}' не найден столбец '{column_name}'")


def increment_cell(ws, row: int, col: int):
    cell = ws.cell(row, col)
    try:
        current = int(cell.value) if cell.value else 0
    except ValueError:
        current = 0
    ws.update_cell(row, col, str(current + 1))


# ======== Общие вспомогательные функции =========


async def _check_permissions(interaction: discord.Interaction) -> bool:
    """Разрешаем только роли ROLE_ID."""
    member = interaction.user
    if isinstance(member, discord.Member) and any(r.id == ROLE_ID for r in member.roles):
        return True
    await interaction.response.send_message(
        "❌ У тебя нет прав выполнять это действие.", ephemeral=True
    )
    return False


def _parse_name_and_id_from_member(member: discord.Member) -> tuple[str, str]:
    """
    Парсим Имя Фамилия ID из ника.
    Ожидаемый формат: 'Имя Фамилия 12345'.
    Берём приоритетно guild nickname, иначе username.
    """
    display_name = member.nick or member.name
    parts = display_name.split()

    if len(parts) < 3 or not parts[-1].isdigit():
        # Если формат неправильный — пусть вызывающий код сам решит, что делать
        raise ValueError(
            f"Невозможно выделить Имя Фамилия и ID из ника '{display_name}'. "
            f"Ожидаемый формат: 'Имя Фамилия 12345'."
        )

    id_part = parts[-1]
    name_part = " ".join(parts[:-1])
    return name_part, id_part


def _get_rank_from_roles(member: discord.Member) -> int | None:
    """
    Определяем ранг по ролям участника.
    Берём максимальный ранг из ROLE_RANK_MAP, если несколько ролей совпадают.
    """
    ranks = []
    for role in member.roles:
        rank = ROLE_RANK_MAP.get(role.id)
        if rank is not None:
            ranks.append(rank)
    return max(ranks) if ranks else None


async def _log_attendance(
    interaction: discord.Interaction,
    target: discord.Member,
    label: str,
    both: bool = False,
):
    """
    Лог в канал LOG_CHANNEL_ID.
    В embed остаются теги сотрудников и игрока,
    в content — просто информативный текст без упоминаний.
    """
    guild = interaction.guild
    if guild is None:
        return

    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return

    staff = interaction.user

    if both:
        contracts_text = "на оба контракта (**Металлургия** и **Товары**)."
        title = "Явка по двум контрактам"
        content = "Засчитана явка по двум контрактам."
    else:
        contracts_text = f"на контракт: **{label}**."
        title = f"Явка по контракту: {label}"
        content = f"Засчитана явка по контракту «{label}»."

    description = (
        f"{staff.mention} подтвердил(а) явку пользователя {target.mention} {contracts_text}"
    )

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.from_rgb(255, 255, 255),  # белый FFFFFF
    )

    await channel.send(content=content, embed=embed)


# ======== Обработка явок =========


async def _handle_mark(
    interaction: discord.Interaction, target: discord.Member, column_name: str, human_name: str
):
    """Проставить явку в один столбец и залогировать это."""
    if not await _check_permissions(interaction):
        return

    await interaction.response.defer(ephemeral=True)

    try:
        ws = get_worksheet()
        row = find_row_by_discord_id(ws, target.id)
        if row is None:
            return await interaction.followup.send(
                f"⚠ Не нашёл {target.mention} в листе '{SHEET_NAME}'.", ephemeral=True
            )

        col = get_column_index_by_name(ws, column_name)
        increment_cell(ws, row, col)

        await interaction.followup.send(
            f"✅ Для {target.mention} проставлена явка: **{human_name}**.", ephemeral=True
        )

        # Логирование
        await _log_attendance(interaction=interaction, target=target, label=human_name, both=False)

    except Exception as e:
        print("Ошибка при работе с таблицей (одна явка):", e)
        await interaction.followup.send(
            "❌ Произошла ошибка при работе с Google Sheets. Сообщи разработчику.", ephemeral=True
        )


async def _handle_mark_both(interaction: discord.Interaction, target: discord.Member):
    """Проставить обе явки за один заход и залогировать это."""
    if not await _check_permissions(interaction):
        return

    await interaction.response.defer(ephemeral=True)

    try:
        ws = get_worksheet()
        row = find_row_by_discord_id(ws, target.id)
        if row is None:
            return await interaction.followup.send(
                f"⚠ Не нашёл {target.mention} в листе '{SHEET_NAME}'.", ephemeral=True
            )

        col_metall = get_column_index_by_name(ws, COLUMN_NAME_METALL)
        col_goods = get_column_index_by_name(ws, COLUMN_NAME_GOODS)

        increment_cell(ws, row, col_metall)
        increment_cell(ws, row, col_goods)

        await interaction.followup.send(
            f"✅ Для {target.mention} проставлены обе явки: **Металлургия** и **Товары**.",
            ephemeral=True,
        )

        # Логирование "оба контракта"
        await _log_attendance(
            interaction=interaction, target=target, label="Металлургия и Товары", both=True
        )

    except Exception as e:
        print("Ошибка при работе с таблицей (обе явки):", e)
        await interaction.followup.send(
            "❌ Произошла ошибка при работе с Google Sheets. Сообщи разработчику.", ephemeral=True
        )


# ======== Добавление в таблицу =========


async def _handle_add_to_sheet(interaction: discord.Interaction, target: discord.Member):
    """
    Добавить участника в таблицу:
    - Ранг (по ролям)
    - Nickname (Имя Фамилия)
    - Discord (<@ID>)
    - ID (число из ника)
    """
    if not await _check_permissions(interaction):
        return

    await interaction.response.defer(ephemeral=True)

    try:
        ws = get_worksheet()
        header = ws.row_values(1)

        # Проверяем, нет ли уже этого Discord в таблице
        existing_row = find_row_by_discord_id(ws, target.id)
        if existing_row is not None:
            return await interaction.followup.send(
                f"⚠ {target.mention} уже есть в таблице (строка {existing_row}).", ephemeral=True
            )

        # Парсим Имя Фамилия и ID из ника
        try:
            nickname_value, id_num_value = _parse_name_and_id_from_member(target)
        except ValueError as e:
            return await interaction.followup.send(f"❌ {e}", ephemeral=True)

        # Определяем ранг по ролям
        rank_value = _get_rank_from_roles(target)
        if rank_value is None:
            return await interaction.followup.send(
                "⚠ Не удалось определить ранг по ролям. "
                "Для старшего состава и особых случаев добавь строку вручную.",
                ephemeral=True,
            )

        # Формируем строку под длину header
        row_values = ["" for _ in range(len(header))]

        def set_if_exists(column_name: str, value: str):
            if column_name in header:
                idx = header.index(column_name)
                row_values[idx] = value

        # Заполняем нужные поля
        set_if_exists(RANK_COLUMN_NAME, str(rank_value))
        set_if_exists(NICKNAME_COLUMN_NAME, nickname_value)
        set_if_exists(ID_COLUMN_NAME, f"<@{target.id}>")  # колонка Discord
        set_if_exists(ID_NUM_COLUMN_NAME, id_num_value)  # колонка ID (число)

        # Добавляем строку в конец
        ws.append_row(row_values, value_input_option="USER_ENTERED")

        await interaction.followup.send(
            f"✅ {target.mention} добавлен в таблицу: ранг **{rank_value}**, "
            f"Nickname: **{nickname_value}**, ID: **{id_num_value}**.",
            ephemeral=True,
        )

    except Exception as e:
        print("Ошибка при добавлении в таблицу:", e)
        await interaction.followup.send(
            "❌ Произошла ошибка при работе с Google Sheets при добавлении игрока. Сообщи разработчику.",
            ephemeral=True,
        )


# ======== Контекстные меню =========


@app_commands.context_menu(name="Проставить явку на Металлургию")
async def mark_metallurgy(interaction: discord.Interaction, member: discord.Member):
    await _handle_mark(interaction, member, COLUMN_NAME_METALL, "Металлургия")


@app_commands.context_menu(name="Проставить явку на Товары")
async def mark_goods(interaction: discord.Interaction, member: discord.Member):
    await _handle_mark(interaction, member, COLUMN_NAME_GOODS, "Товары")


@app_commands.context_menu(name="Проставить все явки")
async def mark_both(interaction: discord.Interaction, member: discord.Member):
    await _handle_mark_both(interaction, member)


@app_commands.context_menu(name="Добавить в таблицу явки")
async def add_to_sheet(interaction: discord.Interaction, member: discord.Member):
    await _handle_add_to_sheet(interaction, member)


# ======== setup для discord.ext.commands extension =========


async def setup(bot: commands.Bot):
    guild = discord.Object(id=GUILD_ID)
    bot.tree.add_command(mark_metallurgy, guild=guild)
    bot.tree.add_command(mark_goods, guild=guild)
    bot.tree.add_command(mark_both, guild=guild)
    bot.tree.add_command(add_to_sheet, guild=guild)
    # sync не делаем — у тебя уже есть глобальный sync
