import asyncio
import contextlib
from typing import Literal

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

from serenity.config import get_settings
from serenity.repositories.cars import CarsRepository
from serenity.services.access import high_staff
from serenity.ui.base import Modal, View

settings = get_settings()


FAMILY = "family"
CARGO = "cargo"
CatalogType = Literal["family", "cargo"]

FAMILY_FIRST_PAGE_CONTENT = (
    "**Тут представлен полный список автомобилей нашей семьи с сортировкой по скорости:**"
)
FAMILY_CONT_PAGE_CONTENT = "Продолжение списка автомобилей (страница {page}/{total})"
CARGO_FIRST_PAGE_CONTENT = (
    "**Ниже представлен список транспорта для работы дальнобойщиком с информацией "
    "о грузоподъёмности и также отсортированный по скорости:**"
)
CARGO_CONT_PAGE_CONTENT = "Продолжение списка грузового транспорта (страница {page}/{total})"


def _chunked(items: list[asyncpg.Record], size: int) -> list[list[asyncpg.Record]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _format_float(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


class AddFamilyStep1Modal(Modal, title="Добавление семейного авто (1/2)"):
    def __init__(self, cog: "CarsCog"):
        super().__init__()
        self.cog = cog
        self.title_input = discord.ui.TextInput(label="Название", max_length=120)
        self.speed_input = discord.ui.TextInput(label="Максимальная скорость (км/ч)", max_length=8)
        self.accel_input = discord.ui.TextInput(label="Разгон 0-100 (сек)", max_length=8)
        self.trunk_input = discord.ui.TextInput(label="Багажник (кг)", max_length=8)
        self.url_input = discord.ui.TextInput(label="URL на вики", max_length=500)

        self.add_item(self.title_input)
        self.add_item(self.speed_input)
        self.add_item(self.accel_input)
        self.add_item(self.trunk_input)
        self.add_item(self.url_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return
        try:
            title = str(self.title_input.value).strip()
            max_speed_kmh = int(str(self.speed_input.value).strip())
            accel_0_100 = float(str(self.accel_input.value).replace(",", ".").strip())
            trunk_kg = int(str(self.trunk_input.value).strip())
            url = str(self.url_input.value).strip()
            if max_speed_kmh <= 0 or accel_0_100 <= 0 or trunk_kg < 0:
                raise ValueError
            if not url.lower().startswith(("http://", "https://")):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Проверьте поля: числа должны быть корректными, URL должен начинаться с http:// или https://",
                ephemeral=True,
            )
            return

        payload = {
            "title": title,
            "max_speed_kmh": max_speed_kmh,
            "accel_0_100": accel_0_100,
            "trunk_kg": trunk_kg,
            "url": url,
        }
        view = CompleteAddFamilyView(self.cog, interaction.user.id, payload)
        await interaction.response.send_message(
            "Шаг 1 сохранён. Нажмите кнопку ниже, чтобы указать URL картинки.",
            ephemeral=True,
            view=view,
        )


class AddFamilyStep2Modal(Modal, title="Добавление семейного авто (2/2)"):
    def __init__(self, cog: "CarsCog", payload: dict[str, object]):
        super().__init__()
        self.cog = cog
        self.payload = payload
        self.image_input = discord.ui.TextInput(label="URL картинки", max_length=500)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return
        image_url = str(self.image_input.value).strip()
        if not image_url.lower().startswith(("http://", "https://")):
            await interaction.response.send_message(
                "URL картинки должен начинаться с http:// или https://",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog.repo.add_car(
                guild_id=interaction.guild.id,
                category=FAMILY,
                title=str(self.payload["title"]),
                max_speed_kmh=int(self.payload["max_speed_kmh"]),
                accel_0_100=float(self.payload["accel_0_100"]),
                trunk_kg=int(self.payload["trunk_kg"]),
                payload_tons_text=None,
                url=str(self.payload["url"]),
                image_url=image_url,
            )
        except asyncpg.UniqueViolationError:
            await interaction.followup.send(
                f"Авто `{self.payload['title']}` уже существует в семейном каталоге.",
                ephemeral=True,
            )
            return

        page_count = await self.cog.refresh_catalog_messages(interaction.guild, FAMILY)
        await interaction.followup.send(
            f"Авто `{self.payload['title']}` добавлено. Семейный каталог обновлён ({page_count} стр.).",
            ephemeral=True,
        )


class CompleteAddFamilyView(View):
    def __init__(self, cog: "CarsCog", owner_id: int, payload: dict[str, object]):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id
        self.payload = payload

    @discord.ui.button(label="Продолжить (шаг 2)", style=discord.ButtonStyle.primary)
    async def continue_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Эта форма не для вас.", ephemeral=True)
            return
        await interaction.response.send_modal(AddFamilyStep2Modal(self.cog, self.payload))


class AddCargoStep1Modal(Modal, title="Добавление грузового авто (1/2)"):
    def __init__(self, cog: "CarsCog"):
        super().__init__()
        self.cog = cog
        self.title_input = discord.ui.TextInput(label="Название", max_length=120)
        self.speed_input = discord.ui.TextInput(label="Максимальная скорость (км/ч)", max_length=8)
        self.accel_input = discord.ui.TextInput(label="Разгон 0-100 (сек)", max_length=8)
        self.trunk_input = discord.ui.TextInput(label="Багажник (кг)", max_length=8)
        self.payload_input = discord.ui.TextInput(label="Грузоподъемность (т)", max_length=16)

        self.add_item(self.title_input)
        self.add_item(self.speed_input)
        self.add_item(self.accel_input)
        self.add_item(self.trunk_input)
        self.add_item(self.payload_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        try:
            title = str(self.title_input.value).strip()
            max_speed_kmh = int(str(self.speed_input.value).strip())
            accel_0_100 = float(str(self.accel_input.value).replace(",", ".").strip())
            trunk_kg = int(str(self.trunk_input.value).strip())
            payload_raw = str(self.payload_input.value).replace(",", ".").strip()
            payload_val = float(payload_raw)
            if max_speed_kmh <= 0 or accel_0_100 <= 0 or trunk_kg < 0 or payload_val <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Проверьте поля: скорость/разгон/багажник/грузоподъемность должны быть корректными числами.",
                ephemeral=True,
            )
            return

        payload = {
            "title": title,
            "max_speed_kmh": max_speed_kmh,
            "accel_0_100": accel_0_100,
            "trunk_kg": trunk_kg,
            "payload_tons_text": payload_raw,
        }
        view = CompleteAddCargoView(self.cog, interaction.user.id, payload)
        await interaction.response.send_message(
            "Шаг 1 сохранён. Нажмите кнопку ниже, чтобы указать URL на вики и картинку.",
            ephemeral=True,
            view=view,
        )


class AddCargoStep2Modal(Modal, title="Добавление грузового авто (2/2)"):
    def __init__(self, cog: "CarsCog", payload: dict[str, object]):
        super().__init__()
        self.cog = cog
        self.payload = payload
        self.url_input = discord.ui.TextInput(label="URL на вики", max_length=500)
        self.image_input = discord.ui.TextInput(label="URL картинки", max_length=500)
        self.add_item(self.url_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        url = str(self.url_input.value).strip()
        image_url = str(self.image_input.value).strip()
        if not url.lower().startswith(("http://", "https://")) or not image_url.lower().startswith(
            ("http://", "https://")
        ):
            await interaction.response.send_message(
                "URL на вики и URL картинки должны начинаться с http:// или https://",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog.repo.add_car(
                guild_id=interaction.guild.id,
                category=CARGO,
                title=str(self.payload["title"]),
                max_speed_kmh=int(self.payload["max_speed_kmh"]),
                accel_0_100=float(self.payload["accel_0_100"]),
                trunk_kg=int(self.payload["trunk_kg"]),
                payload_tons_text=str(self.payload["payload_tons_text"]),
                url=url,
                image_url=image_url,
            )
        except asyncpg.UniqueViolationError:
            await interaction.followup.send(
                f"Авто `{self.payload['title']}` уже существует в грузовом каталоге.",
                ephemeral=True,
            )
            return

        page_count = await self.cog.refresh_catalog_messages(interaction.guild, CARGO)
        await interaction.followup.send(
            f"Авто `{self.payload['title']}` добавлено. Грузовой каталог обновлён ({page_count} стр.).",
            ephemeral=True,
        )


class CompleteAddCargoView(View):
    def __init__(self, cog: "CarsCog", owner_id: int, payload: dict[str, object]):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id
        self.payload = payload

    @discord.ui.button(label="Продолжить (шаг 2)", style=discord.ButtonStyle.primary)
    async def continue_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Эта форма не для вас.", ephemeral=True)
            return
        await interaction.response.send_modal(AddCargoStep2Modal(self.cog, self.payload))


class DeleteCarSelect(discord.ui.Select):
    def __init__(self, view: "DeleteCarsView"):
        self.delete_view = view
        start = view.page * view.page_size
        end = start + view.page_size
        chunk = view.cars[start:end]

        options: list[discord.SelectOption] = []
        for row in chunk:
            label = str(row["title"])[:100]
            description = f"{int(row['max_speed_kmh'])} км/ч | 0-100: {_format_float(float(row['accel_0_100']))} сек"[
                :100
            ]
            options.append(
                discord.SelectOption(
                    label=label, description=description, value=str(int(row["id"]))
                )
            )

        super().__init__(
            placeholder="Выберите авто для удаления",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.delete_view.handle_delete(interaction, int(self.values[0]))


class DeleteCarsView(View):
    def __init__(
        self,
        cog: "CarsCog",
        owner_id: int,
        guild_id: int,
        category: CatalogType,
        cars: list[asyncpg.Record],
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.category = category
        self.cars = cars
        self.page_size = 25
        self.page = 0

        self.prev_btn = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=1)
        self.next_btn = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, row=1)
        self.close_btn = discord.ui.Button(label="Закрыть", style=discord.ButtonStyle.danger, row=1)

        self.prev_btn.callback = self._prev
        self.next_btn.callback = self._next
        self.close_btn.callback = self._close

        self._rebuild_items()

    def _total_pages(self) -> int:
        if not self.cars:
            return 1
        return ((len(self.cars) - 1) // self.page_size) + 1

    def _rebuild_items(self) -> None:
        self.clear_items()
        if self.cars:
            self.add_item(DeleteCarSelect(self))

        total_pages = self._total_pages()
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= total_pages - 1

        self.add_item(self.prev_btn)
        self.add_item(self.next_btn)
        self.add_item(self.close_btn)

    async def _deny_other_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            if interaction.response.is_done():
                await interaction.followup.send("Эта панель не для вас.", ephemeral=True)
            else:
                await interaction.response.send_message("Эта панель не для вас.", ephemeral=True)
            return True
        return False

    async def _prev(self, interaction: discord.Interaction) -> None:
        if await self._deny_other_user(interaction):
            return
        self.page = max(0, self.page - 1)
        self._rebuild_items()
        await interaction.response.edit_message(
            content=self._panel_text(),
            view=self,
        )

    async def _next(self, interaction: discord.Interaction) -> None:
        if await self._deny_other_user(interaction):
            return
        self.page = min(self._total_pages() - 1, self.page + 1)
        self._rebuild_items()
        await interaction.response.edit_message(
            content=self._panel_text(),
            view=self,
        )

    async def _close(self, interaction: discord.Interaction) -> None:
        if await self._deny_other_user(interaction):
            return
        await interaction.response.edit_message(content="Панель удаления закрыта.", view=None)
        self.stop()

    def _panel_text(self) -> str:
        label = "семейных" if self.category == FAMILY else "грузовых"
        return (
            f"Выберите авто для удаления ({label}). Страница {self.page + 1}/{self._total_pages()}"
        )

    async def handle_delete(self, interaction: discord.Interaction, car_id: int) -> None:
        if await self._deny_other_user(interaction):
            return

        await interaction.response.defer(ephemeral=True)
        deleted = await self.cog.repo.delete_car(self.guild_id, car_id, self.category)
        if not deleted:
            await interaction.followup.send("Авто уже удалено или не найдено.", ephemeral=True)
            return

        page_count = await self.cog.refresh_catalog_messages(interaction.guild, self.category)
        await interaction.followup.send(
            f"Авто удалено. Каталог обновлён ({page_count} стр.).", ephemeral=True
        )

        self.cars = await self.cog.repo.list_cars(self.guild_id, self.category)
        if not self.cars:
            with contextlib.suppress(discord.HTTPException):
                await interaction.edit_original_response(
                    content="В этом каталоге больше нет авто.", view=None
                )
            self.stop()
            return

        self.page = min(self.page, self._total_pages() - 1)
        self._rebuild_items()
        with contextlib.suppress(discord.HTTPException):
            await interaction.edit_original_response(content=self._panel_text(), view=self)


class CarsPanelView(View):
    def __init__(self, cog: "CarsCog"):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="Добавить семейное авто", style=discord.ButtonStyle.success, row=0)
    async def add_family(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(AddFamilyStep1Modal(self.cog))

    @discord.ui.button(label="Удалить семейное авто", style=discord.ButtonStyle.danger, row=0)
    async def delete_family(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._open_delete_panel(interaction, FAMILY)

    @discord.ui.button(label="Добавить грузовое авто", style=discord.ButtonStyle.success, row=1)
    async def add_cargo(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(AddCargoStep1Modal(self.cog))

    @discord.ui.button(label="Удалить грузовое авто", style=discord.ButtonStyle.danger, row=1)
    async def delete_cargo(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._open_delete_panel(interaction, CARGO)

    async def _open_delete_panel(
        self, interaction: discord.Interaction, category: CatalogType
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        cars = await self.cog.repo.list_cars(interaction.guild.id, category)
        if not cars:
            title = "семейных" if category == FAMILY else "грузовых"
            await interaction.response.send_message(
                f"В каталоге {title} авто пока пусто.", ephemeral=True
            )
            return

        delete_view = DeleteCarsView(
            self.cog, interaction.user.id, interaction.guild.id, category, cars
        )
        await interaction.response.send_message(
            delete_view._panel_text(), ephemeral=True, view=delete_view
        )


class CarsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.repo = CarsRepository(bot.database.pool)
        self._guild_refresh_locks: dict[int, asyncio.Lock] = {}

    async def cog_load(self):
        await self.repo.init()
        self.bot.tree.add_command(self.cars_panel, guild=discord.Object(id=settings.guild_id))
        self.bot.tree.add_command(self.cars_refresh, guild=discord.Object(id=settings.guild_id))

    def _guild_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._guild_refresh_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._guild_refresh_locks[guild_id] = lock
        return lock

    @staticmethod
    def _build_embed(row: asyncpg.Record, category: CatalogType) -> discord.Embed:
        description = (
            "**Основная информация:**\n\n"
            f"Максимальная скорость(FT) - {int(row['max_speed_kmh'])} км/ч\n"
            f"Разгон до 100 км/ч - {_format_float(float(row['accel_0_100']))} сек\n"
            f"Багажник - {int(row['trunk_kg'])} кг"
        )
        if category == CARGO:
            payload = str(row["payload_tons_text"] or "0")
            description += f"\nГрузоподъемность - {payload} т"

        embed = discord.Embed(
            title=str(row["title"]),
            description=description,
            url=str(row["url"]),
            color=discord.Color.from_rgb(255, 255, 255),
        )
        embed.set_image(url=str(row["image_url"]))
        return embed

    async def refresh_catalog_messages(self, guild: discord.Guild, category: CatalogType) -> int:
        lock = self._guild_lock(guild.id)
        async with lock:
            await self.repo.ensure_guild_settings(guild.id, settings.car_catalog_channel_id)
            channel_id = await self.repo.get_catalog_channel_id(guild.id)
            if channel_id is None:
                raise RuntimeError("Не задан канал каталога.")

            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                fetched = await self.bot.fetch_channel(channel_id)
                if not isinstance(fetched, discord.TextChannel):
                    raise RuntimeError("Канал каталога должен быть текстовым.")
                channel = fetched

            me = guild.me or guild.get_member(self.bot.user.id if self.bot.user else 0)
            if me is None:
                raise RuntimeError("Не удалось проверить права бота в канале каталога.")

            perms = channel.permissions_for(me)
            if not perms.send_messages or not perms.embed_links:
                raise RuntimeError("У бота нет прав send_messages/embed_links в канале каталога.")

            cars = await self.repo.list_cars(guild.id, category)
            pages = _chunked(cars, 10)

            stored_rows = await self.repo.get_catalog_messages(guild.id, category)
            stored_by_page = {int(r["page_index"]): r for r in stored_rows}

            total_pages = len(pages)
            for page_index, page_items in enumerate(pages):
                if page_index == 0:
                    content = (
                        FAMILY_FIRST_PAGE_CONTENT
                        if category == FAMILY
                        else CARGO_FIRST_PAGE_CONTENT
                    )
                else:
                    template = (
                        FAMILY_CONT_PAGE_CONTENT if category == FAMILY else CARGO_CONT_PAGE_CONTENT
                    )
                    content = template.format(page=page_index + 1, total=total_pages)

                embeds = [self._build_embed(row, category) for row in page_items]

                existing = stored_by_page.get(page_index)
                if existing:
                    message_id = int(existing["message_id"])
                    try:
                        msg = await channel.fetch_message(message_id)
                        await msg.edit(content=content, embeds=embeds)
                        await self.repo.upsert_catalog_message(
                            guild.id, category, page_index, channel.id, msg.id
                        )
                        continue
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass

                msg = await channel.send(content=content, embeds=embeds)
                await self.repo.upsert_catalog_message(
                    guild.id, category, page_index, channel.id, msg.id
                )

            stale_pages = [p for p in stored_by_page.keys() if p >= total_pages]
            for page_index in stale_pages:
                row = stored_by_page[page_index]
                message_id = int(row["message_id"])
                with contextlib.suppress(discord.HTTPException):
                    msg = await channel.fetch_message(message_id)
                    await msg.delete()
                await self.repo.delete_catalog_message(guild.id, category, page_index)

            return total_pages

    @app_commands.command(name="cars_panel", description="Панель управления автокаталогом")
    @high_staff()
    async def cars_panel(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        await self.repo.ensure_guild_settings(interaction.guild.id, settings.car_catalog_channel_id)
        view = CarsPanelView(self)
        await interaction.response.send_message(
            "Панель управления автопарком:",
            ephemeral=True,
            view=view,
        )

    @app_commands.command(name="cars_refresh", description="Обновить сообщения каталога")
    @high_staff()
    async def cars_refresh(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        family_pages = await self.refresh_catalog_messages(interaction.guild, FAMILY)
        cargo_pages = await self.refresh_catalog_messages(interaction.guild, CARGO)

        await interaction.followup.send(
            (f"Каталоги обновлены. Семейные: {family_pages} стр., грузовые: {cargo_pages} стр."),
            ephemeral=True,
        )

    @cars_panel.error
    @cars_refresh.error
    async def _cars_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.errors.MissingAnyRole):
            message = "У вас нет доступа к этой команде."
        else:
            message = f"Ошибка: {error}"

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CarsCog(bot))
