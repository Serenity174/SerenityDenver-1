"""Private Discord control panel; every write rechecks authorization."""

import copy

import discord
from discord import app_commands, ui
from discord.ext import commands

from serenity.services.access import can_manage
from serenity.services.settings import SettingSpec, validate
from serenity.ui.base import Modal, View, reply


def display(key, value):
    if key.endswith("_category_id") and value == 0:
        return "Без категории"
    if key.endswith("_channel_id") or key.endswith("_category_id"):
        return f"<#{value}>"
    if key.endswith("_role_id"):
        return f"<@&{value}>"
    if key.endswith("_role_ids"):
        return " → ".join(f"<@&{item}>" for item in value)
    if isinstance(value, bool):
        return "Включено" if value else "Отключено"
    if isinstance(value, dict):
        return "\n".join(f"{name}: {price}" for name, price in value.items())
    return str(value)


class AdminView(View):
    def __init__(self, bot, owner):
        super().__init__(timeout=600)
        self.bot = bot
        self.owner = owner

    async def interaction_check(self, interaction):
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id != self.owner or not can_manage(interaction.user):
            await reply(
                interaction,
                "Управление доступно администратору и старшему составу. Откройте /настройки самостоятельно.",
            )
            return False
        return True

    def home_button(self):
        button = ui.Button(label="Главное меню", row=4)

        async def callback(interaction):
            await interaction.response.edit_message(
                content="Выберите раздел. Изменения применяются после сохранения.",
                embed=None,
                view=Home(self.bot, self.owner),
            )

        button.callback = callback
        self.add_item(button)


class Home(AdminView):
    def __init__(self, bot, owner):
        super().__init__(bot, owner)
        groups = list(dict.fromkeys(spec.group for spec in bot.live_settings.specs.values()))
        select = ui.Select(
            placeholder="Что хотите изменить?",
            options=[discord.SelectOption(label=group) for group in groups],
        )

        async def callback(interaction):
            await interaction.response.edit_message(
                content=select.values[0],
                embed=None,
                view=SettingsList(bot, owner, select.values[0]),
            )

        select.callback = callback
        self.add_item(select)

    @ui.button(label="Проверить работу", style=discord.ButtonStyle.primary)
    async def diagnose(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        await self.bot.database.pool.fetchval("SELECT 1")
        issues = []
        guild = interaction.guild
        for key, spec in self.bot.live_settings.specs.items():
            if spec.kind in ("channel", "category"):
                if spec.kind == "category" and self.bot.live_settings.values[key] == 0:
                    continue
                channel = guild.get_channel(self.bot.live_settings.values[key])
                if channel is None:
                    issues.append(f"{spec.label}: канал не найден")
                elif spec.kind == "channel":
                    permissions = channel.permissions_for(guild.me)
                    if not permissions.view_channel:
                        issues.append(f"{spec.label}: нет доступа")
                    if isinstance(channel, discord.TextChannel) and not all(
                        (
                            permissions.send_messages,
                            permissions.read_message_history,
                            permissions.embed_links,
                            permissions.attach_files,
                        )
                    ):
                        issues.append(
                            f"{spec.label}: нужны отправка сообщений, история, ссылки и файлы"
                        )
            elif spec.kind in ("role", "roles", "ranks"):
                value = self.bot.live_settings.values[key]
                for role_id in value if isinstance(value, list) else [value]:
                    role = guild.get_role(role_id)
                    if role is None:
                        issues.append(f"{spec.label}: роль не найдена")
                    elif key in (
                        "application_role_ids",
                        "rank_role_ids",
                        "vacation_role_id",
                        "verified_role_id",
                    ) and (role.managed or role >= guild.me.top_role):
                        issues.append(f"{spec.label}: бот не может выдать роль {role.name}")
        if not guild.me.guild_permissions.manage_roles:
            issues.append("Боту нужно право управления ролями")
        if not guild.me.guild_permissions.manage_channels:
            issues.append("Боту нужно право управления каналами для голосовых комнат")
        count = await self.bot.database.pool.fetchval(
            "SELECT count(*) FROM public.jobs WHERE completed_at IS NULL AND expires_at>now()"
        )
        await interaction.followup.send(
            (
                f"База данных доступна. Задач в очереди: {count}.\n"
                + ("\n".join(issues) if issues else "Проверенные каналы и роли доступны.")
            )[:1900],
            ephemeral=True,
        )

    @ui.button(label="История изменений")
    async def history(self, interaction, button):
        await interaction.response.defer()
        rows = await self.bot.live_settings.repo.history(interaction.guild_id)
        await interaction.edit_original_response(
            content="Последние изменения. Выберите запись, чтобы вернуть предыдущее значение.",
            embed=None,
            view=History(self.bot, self.owner, rows),
        )

    @ui.button(label="Восстановить панели")
    async def panels(self, interaction, button):
        from serenity.services.panels import PANEL_LABELS

        view = AdminView(self.bot, self.owner)
        select = ui.Select(
            placeholder="Выберите панель",
            options=[
                discord.SelectOption(label=label, value=key) for key, label in PANEL_LABELS.items()
            ],
        )

        async def callback(event):
            from serenity.services.panels import publish_panel

            await event.response.defer(ephemeral=True)
            await publish_panel(self.bot, select.values[0])
            await event.followup.send(
                "Панель опубликована или обновлена в настроенном канале.", ephemeral=True
            )

        select.callback = callback
        view.add_item(select)
        view.home_button()
        await interaction.response.edit_message(
            content="Проверьте канал в разделе «Каналы», затем выберите панель.",
            embed=None,
            view=view,
        )


class SettingsList(AdminView):
    def __init__(self, bot, owner, group, page=0):
        super().__init__(bot, owner)
        keys = [key for key, spec in bot.live_settings.specs.items() if spec.group == group]
        batch = keys[page * 25 : (page + 1) * 25]
        select = ui.Select(
            placeholder="Выберите настройку",
            options=[
                discord.SelectOption(label=bot.live_settings.specs[key].label[:100], value=key)
                for key in batch
            ],
        )

        async def callback(interaction):
            key = select.values[0]
            value = bot.live_settings.values[key]
            spec = bot.live_settings.specs[key]
            if spec.kind == "prices":
                await interaction.response.edit_message(
                    content="Цены применяются к новым отчётам. Старые суммы сохраняются.",
                    embed=None,
                    view=Prices(bot, owner),
                )
            elif spec.kind == "urls":
                await interaction.response.edit_message(
                    content="Выберите изображение для замены или удаления.",
                    embed=None,
                    view=Images(bot, owner, key),
                )
            else:
                embed = discord.Embed(title=spec.label, description=display(key, value)[:4000])
                await interaction.response.edit_message(
                    content="Текущее значение. Выберите действие.",
                    embed=embed,
                    view=EditSetting(bot, owner, key),
                )

        select.callback = callback
        self.add_item(select)
        for label, destination in (("Назад", page - 1), ("Далее", page + 1)):
            if 0 <= destination < (len(keys) + 24) // 25:
                button = ui.Button(label=label, row=2)

                async def navigate(interaction, target=destination):
                    await interaction.response.edit_message(
                        view=SettingsList(bot, owner, group, target)
                    )

                button.callback = navigate
                self.add_item(button)
        self.home_button()


class EditSetting(AdminView):
    def __init__(self, bot, owner, key):
        super().__init__(bot, owner)
        self.key = key
        self.expected = copy.deepcopy(bot.live_settings.values[key])
        spec = bot.live_settings.specs[key]
        if spec.kind != "category":
            self.remove_item(self.no_category)
        selector = None
        if spec.kind in ("channel", "category"):
            channel_type = (
                discord.ChannelType.category
                if spec.kind == "category"
                else discord.ChannelType.voice
                if key == "temp_voice_trigger_channel_id"
                else discord.ChannelType.text
            )
            selector = ui.ChannelSelect(placeholder="Выберите канал", channel_types=[channel_type])
        elif spec.kind in ("role", "roles", "ranks"):
            selector = ui.RoleSelect(
                placeholder="Выберите роли" if spec.kind != "role" else "Выберите роль",
                min_values=2 if spec.kind == "ranks" else 1,
                max_values=1 if spec.kind == "role" else 25,
            )
        elif spec.kind == "bool":
            selector = ui.Select(
                options=[
                    discord.SelectOption(label="Включить", value="yes"),
                    discord.SelectOption(label="Отключить", value="no"),
                ]
            )
        elif spec.kind == "timezone":
            selector = ui.Select(
                placeholder="Выберите часовой пояс",
                options=[
                    discord.SelectOption(label=label, value=zone)
                    for label, zone in (
                        ("Москва", "Europe/Moscow"),
                        ("Екатеринбург", "Asia/Yekaterinburg"),
                        ("Калининград", "Europe/Kaliningrad"),
                        ("Новосибирск", "Asia/Novosibirsk"),
                        ("Владивосток", "Asia/Vladivostok"),
                    )
                ],
            )
        if selector:

            async def callback(interaction):
                if spec.kind == "timezone":
                    value = selector.values[0]
                elif spec.kind == "bool":
                    value = selector.values[0] == "yes"
                elif spec.kind in ("roles", "ranks"):
                    selected = [interaction.guild.get_role(role.id) for role in selector.values]
                    # Discord's role order makes rank ordering explicit and repeatable.
                    if spec.kind == "ranks":
                        selected.sort(key=lambda role: role.position)
                    value = [role.id for role in selected]
                else:
                    value = selector.values[0].id
                if spec.kind in ("channel", "category"):
                    channel = interaction.guild.get_channel(value)
                    if (
                        channel is None
                        or not channel.permissions_for(interaction.guild.me).view_channel
                    ):
                        return await reply(interaction, "Боту нужен доступ к выбранному каналу.")
                await preview(interaction, bot, owner, key, value, self.expected)

            selector.callback = callback
            self.add_item(selector)
            if spec.kind != "timezone":
                self.remove_item(self.edit)
        self.home_button()

    @ui.button(label="Без категории", row=2)
    async def no_category(self, interaction, button):
        if self.bot.live_settings.specs[self.key].kind != "category":
            return await reply(interaction, "Эта настройка не относится к категориям.")
        await preview(interaction, self.bot, self.owner, self.key, 0, self.expected)

    @ui.button(label="Изменить", style=discord.ButtonStyle.primary)
    async def edit(self, interaction, button):
        await interaction.response.send_modal(
            ValueModal(self.bot, self.owner, self.key, self.expected)
        )


class ValueModal(Modal):
    def __init__(self, bot, owner, key, expected):
        spec = bot.live_settings.specs[key]
        super().__init__(title=spec.label[:45])
        self.bot, self.owner, self.key, self.expected = bot, owner, key, expected
        self.value = ui.TextInput(
            label="Новое значение",
            style=discord.TextStyle.paragraph,
            default=str(expected),
            max_length=min(spec.maximum, 4000) if spec.kind == "text" else 4000,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction):
        if interaction.user.id != self.owner or not can_manage(interaction.user):
            return await reply(interaction, "Нет доступа к настройкам.")
        await preview(interaction, self.bot, self.owner, self.key, self.value.value, self.expected)


async def preview(interaction, bot, owner, key, value, expected):
    try:
        value = validate(bot.live_settings.specs[key], value)
    except ValueError as exc:
        return await reply(interaction, str(exc))
    embed = discord.Embed(
        title=bot.live_settings.specs[key].label, description=display(key, value)[:4000]
    )
    if bot.live_settings.specs[key].kind == "url":
        embed.set_image(url=value)
    if key == "rank_role_ids":
        embed.set_footer(
            text="Порядок рангов: от младшего к старшему, по расположению ролей Discord."
        )
    await interaction.response.send_message(
        "Предпросмотр. Настройка ещё не сохранена.",
        embed=embed,
        view=Confirm(bot, owner, key, value, expected),
        ephemeral=True,
    )


class Confirm(AdminView):
    def __init__(self, bot, owner, key, value, expected):
        super().__init__(bot, owner)
        self.key, self.value, self.expected = key, value, expected
        self.used = False

    @ui.button(label="Сохранить", style=discord.ButtonStyle.success)
    async def save(self, interaction, button):
        if self.used:
            return await reply(interaction, "Это изменение уже обработано.")
        self.used = True
        await interaction.response.defer()
        try:
            spec = self.bot.live_settings.specs[self.key]
            if spec.kind in ("role", "roles", "ranks"):
                ids = self.value if isinstance(self.value, list) else [self.value]
                for role_id in ids:
                    role = interaction.guild.get_role(role_id)
                    if role is None:
                        raise ValueError("Роль больше не существует. Выберите другую.")
                    if self.key in (
                        "application_role_ids",
                        "rank_role_ids",
                        "vacation_role_id",
                        "verified_role_id",
                    ) and (role.managed or role >= interaction.guild.me.top_role):
                        raise ValueError(
                            "Бот не может выдать эту роль. Поместите его роль выше выбранной."
                        )
            if spec.kind in ("channel", "category") and self.value:
                channel = interaction.guild.get_channel(self.value)
                if (
                    channel is None
                    or not channel.permissions_for(interaction.guild.me).view_channel
                ):
                    raise ValueError("Канал больше недоступен боту. Выберите другой.")
            if self.key == "payout_comment" and any(
                character in str(self.value) for character in (";", "\n", "\r")
            ):
                raise ValueError(
                    "Комментарий к выплате должен быть одной строкой без точки с запятой."
                )
            await self.bot.live_settings.save(
                self.key, self.value, interaction.user.id, self.expected
            )
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc), embed=None, view=None)
            return
        await interaction.edit_original_response(
            content="Сохранено. Изменение применяется сразу. Можно выбрать следующий раздел. Для опубликованных панелей используйте «Восстановить панели».",
            embed=None,
            view=Home(self.bot, self.owner),
        )
        self.stop()

    @ui.button(label="Отмена")
    async def cancel(self, interaction, button):
        self.used = True
        await interaction.response.edit_message(
            content="Изменение отменено.", embed=None, view=None
        )
        self.stop()


class Prices(AdminView):
    def __init__(self, bot, owner, page=0):
        super().__init__(bot, owner)
        values = bot.live_settings.values["prices"]
        keys = list(values)
        select = ui.Select(
            placeholder="Выберите категорию",
            options=[
                discord.SelectOption(label=key[:100], value=key, description=f"Цена: {values[key]}")
                for key in keys[page * 25 : (page + 1) * 25]
            ],
        )

        async def callback(interaction):
            await interaction.response.send_modal(PriceModal(bot, owner, select.values[0]))

        select.callback = callback
        self.add_item(select)
        for label, destination in (("Назад", page - 1), ("Далее", page + 1)):
            if 0 <= destination < (len(keys) + 24) // 25:
                button = ui.Button(label=label, row=2)

                async def navigate(interaction, target=destination):
                    await interaction.response.edit_message(view=Prices(bot, owner, target))

                button.callback = navigate
                self.add_item(button)
        self.home_button()

    @ui.button(label="Добавить категорию", style=discord.ButtonStyle.primary, row=1)
    async def add(self, interaction, button):
        await interaction.response.send_modal(PriceModal(self.bot, self.owner))


class PriceModal(Modal):
    def __init__(self, bot, owner, category=None):
        super().__init__(title="Категория отчёта")
        self.bot, self.owner, self.category = bot, owner, category
        self.expected = copy.deepcopy(bot.live_settings.values["prices"])
        self.name = ui.TextInput(label="Название", default=category, max_length=80)
        self.price = ui.TextInput(
            label="Цена за единицу", default=self.expected.get(category, "0"), max_length=30
        )
        self.action = ui.TextInput(
            label="Для удаления введите УДАЛИТЬ", required=False, max_length=7
        )
        for item in (self.name, self.price, self.action):
            self.add_item(item)

    async def on_submit(self, interaction):
        if interaction.user.id != self.owner or not can_manage(interaction.user):
            return await reply(interaction, "Нет доступа.")
        values = copy.deepcopy(self.expected)
        name = self.name.value.strip()
        if self.action.value.strip():
            if self.action.value.strip() != "УДАЛИТЬ" or not self.category:
                return await reply(
                    interaction, "Для удаления существующей категории введите УДАЛИТЬ."
                )
            values.pop(self.category)
        else:
            if name != self.category and name in values:
                return await reply(interaction, "Категория с таким названием уже существует.")
            if self.category:
                values.pop(self.category)
            values[name] = self.price.value
        await preview(interaction, self.bot, self.owner, "prices", values, self.expected)


class Images(AdminView):
    def __init__(self, bot, owner, key, page=0):
        super().__init__(bot, owner)
        self.key = key
        urls = bot.live_settings.values[key].splitlines()
        select = ui.Select(
            placeholder="Выберите изображение",
            options=[
                discord.SelectOption(
                    label=f"Изображение {index + 1}", value=str(index), description=url[:100]
                )
                for index, url in list(enumerate(urls))[page * 25 : (page + 1) * 25]
            ],
        )

        async def callback(interaction):
            await interaction.response.send_modal(
                ImageModal(bot, owner, key, int(select.values[0]))
            )

        select.callback = callback
        self.add_item(select)
        for label, destination in (("Назад", page - 1), ("Далее", page + 1)):
            if 0 <= destination < (len(urls) + 24) // 25:
                button = ui.Button(label=label, row=2)

                async def navigate(interaction, target=destination):
                    await interaction.response.edit_message(view=Images(bot, owner, key, target))

                button.callback = navigate
                self.add_item(button)
        self.home_button()

    @ui.button(label="Добавить изображение", row=1)
    async def add(self, interaction, button):
        await interaction.response.send_modal(ImageModal(self.bot, self.owner, self.key))


class ImageModal(Modal):
    def __init__(self, bot, owner, key, index=None):
        super().__init__(title="Изображение")
        self.bot, self.owner, self.key, self.index = bot, owner, key, index
        self.expected = bot.live_settings.values[key]
        self.url = ui.TextInput(
            label="HTTPS-ссылка или УДАЛИТЬ",
            default=self.expected.splitlines()[index] if index is not None else None,
            max_length=1000,
        )
        self.add_item(self.url)

    async def on_submit(self, interaction):
        if interaction.user.id != self.owner or not can_manage(interaction.user):
            return await reply(interaction, "Нет доступа.")
        urls = self.expected.splitlines()
        if self.url.value.strip() == "УДАЛИТЬ" and self.index is not None:
            urls.pop(self.index)
        else:
            try:
                url = validate(SettingSpec("", "", "url"), self.url.value)
            except ValueError as exc:
                return await reply(interaction, str(exc))
            if self.index is None:
                urls.append(url)
            else:
                urls[self.index] = url
        await preview(interaction, self.bot, self.owner, self.key, "\n".join(urls), self.expected)


class History(AdminView):
    def __init__(self, bot, owner, rows):
        super().__init__(bot, owner)
        rows = [row for row in rows if row["key"] in bot.live_settings.specs]
        if rows:
            select = ui.Select(
                placeholder="Изменение для отката",
                options=[
                    discord.SelectOption(
                        label=f"#{row['id']} {bot.live_settings.specs[row['key']].label}"[:100],
                        value=str(index),
                        description=f"{row['created_at']:%d.%m %H:%M UTC}; автор {row['actor_id']}",
                    )
                    for index, row in enumerate(rows)
                ],
            )

            async def callback(interaction):
                row = rows[int(select.values[0])]
                key = row["key"]
                await preview(
                    interaction,
                    bot,
                    owner,
                    key,
                    row["old_value"],
                    copy.deepcopy(bot.live_settings.values[key]),
                )

            select.callback = callback
            self.add_item(select)
        self.home_button()


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.tree.add_command(
            self.settings_command, guild=discord.Object(id=self.bot.settings.guild_id)
        )

    @app_commands.command(
        name="настройки",
        description="Управление ботом: каналы, роли, цены, сообщения и диагностика",
    )
    async def settings_command(self, interaction):
        if not can_manage(interaction.user):
            return await reply(interaction, "Настройки доступны администратору и старшему составу.")
        await interaction.response.send_message(
            "Выберите раздел. Перед сохранением будет предпросмотр. Ранги упорядочиваются по расположению ролей Discord: от младшего к старшему.",
            view=Home(self.bot, interaction.user.id),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Admin(bot))
