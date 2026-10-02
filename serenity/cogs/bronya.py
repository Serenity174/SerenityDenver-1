import re

import discord
from discord import app_commands
from discord.ext import commands

from serenity.config import get_settings
from serenity.repositories.state import StateRepository
from serenity.services.serialization import signup_mutation
from serenity.ui.base import Modal, View

settings = get_settings()

ROLE_ID = settings.high_staff_role_id
GUILD_ID = settings.guild_id
CHANNEL_ID = settings.bronya_channel_id

EMBED_TITLE = "Запись участников"
CLOSE_MARKER = "Запись закрыта."


class SignUpModal(Modal, title="Открыть запись на контракт"):
    title_input = discord.ui.TextInput(label="Название контракта:", max_length=100)
    max_participants = discord.ui.TextInput(
        label="Максимальное количество участников:",
        style=discord.TextStyle.short,
    )

    def __init__(self, interaction: discord.Interaction, bot: commands.Bot):
        super().__init__()
        self.interaction = interaction
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_count = int(self.max_participants.value)
            if not 1 <= max_count <= 25:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Укажи число участников от 1 до 25.",
                ephemeral=True,
            )
            return

        content = (
            f"Открыта запись на контракт: {self.title_input.value}\n"
            f"Запись открыта: {interaction.user.mention}\n"
            f"Максимальное количество участников: {max_count}"
        )

        view = SignUpView(interaction.user, max_count, content)
        embed = view.build_embed()

        channel = interaction.guild.get_channel(CHANNEL_ID)
        if not channel:
            await interaction.response.send_message(
                "Не удалось найти канал для записи.", ephemeral=True
            )
            return

        message = await channel.send(content=content, embed=embed, view=view)
        view.message = message
        await view.persist()
        await interaction.response.send_message("Запись открыта!", ephemeral=True)


class SignUpView(View):
    def __init__(
        self,
        creator: discord.User,
        max_participants: int,
        content: str,
        participants: list[discord.abc.User] | None = None,
        closed: bool = False,
        message: discord.Message | None = None,
    ):
        super().__init__(timeout=None)
        self.creator = creator
        self.max_participants = max_participants
        self.participants: list[discord.abc.User] = participants or []
        self.message: discord.Message | None = message
        self.closed = closed
        self.content = content
        self.refresh_buttons()

    async def persist(self, no_buttons=False):
        if self.message:
            await StateRepository().put(
                self.message.guild.id,
                "bronya",
                self.message.id,
                {
                    "channel_id": self.message.channel.id,
                    "creator_id": self.creator.id,
                    "max_participants": self.max_participants,
                    "content": self.content,
                    "participants": [user.id for user in self.participants],
                    "closed": self.closed,
                    "no_buttons": no_buttons,
                },
            )

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title=EMBED_TITLE, color=discord.Color.from_rgb(255, 255, 255))
        if self.participants:
            description = "\n".join(
                f"{i + 1}. {getattr(user, 'mention', f'<@{user.id}>')}"
                for i, user in enumerate(self.participants)
            )
        else:
            description = "Нет записанных участников."
        embed.add_field(name="**Участники:**", value=description[:1024], inline=False)
        if self.closed:
            embed.set_footer(text=CLOSE_MARKER)
        return embed

    def is_creator_or_role(self, user: discord.Member) -> bool:
        return user.id == self.creator.id or any(role.id == ROLE_ID for role in user.roles)

    def refresh_buttons(self) -> None:
        self.clear_items()
        self.add_item(self.join)
        self.add_item(self.leave)
        if self.closed:
            self.add_item(self.open)
        else:
            self.add_item(self.close)
        self.add_item(self.silent_close)

    @discord.ui.button(label="➕", style=discord.ButtonStyle.secondary, custom_id="signup_join")
    @signup_mutation
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.closed:
            await interaction.response.send_message("Запись закрыта.", ephemeral=True)
            return

        if any(user.id == interaction.user.id for user in self.participants):
            await interaction.response.send_message("Ты уже записан.", ephemeral=True)
            return

        if len(self.participants) >= self.max_participants:
            await interaction.response.send_message(
                "Достигнуто максимальное число участников.", ephemeral=True
            )
            return

        self.participants.append(interaction.user)
        await self.persist()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="➖", style=discord.ButtonStyle.secondary, custom_id="signup_leave")
    @signup_mutation
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.closed:
            await interaction.response.send_message(
                "Запись закрыта. Напиши ведущему, если нужно выйти.", ephemeral=True
            )
            return

        if not any(user.id == interaction.user.id for user in self.participants):
            await interaction.response.send_message("Ты не в списке.", ephemeral=True)
            return

        self.participants = [user for user in self.participants if user.id != interaction.user.id]
        await self.persist()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔒", style=discord.ButtonStyle.secondary, custom_id="close")
    @signup_mutation
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_creator_or_role(interaction.user):
            await interaction.response.send_message(
                "Нет прав закрывать эту запись.", ephemeral=True
            )
            return

        self.closed = True
        await self.persist()
        self.refresh_buttons()
        await self.message.edit(
            content=self.content + f"\n⚠️ {CLOSE_MARKER}", embed=self.build_embed(), view=self
        )
        await interaction.response.send_message("Запись закрыта.", ephemeral=True)

    @discord.ui.button(label="🔓", style=discord.ButtonStyle.secondary, custom_id="open")
    @signup_mutation
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_creator_or_role(interaction.user):
            await interaction.response.send_message(
                "Нет прав открывать эту запись.", ephemeral=True
            )
            return

        self.closed = False
        await self.persist()
        self.refresh_buttons()
        await self.message.edit(content=self.content, embed=self.build_embed(), view=self)
        await interaction.response.send_message("Запись открыта заново.", ephemeral=True)

    @discord.ui.button(
        label="✖️",
        style=discord.ButtonStyle.secondary,
        custom_id="silent_close",
    )
    async def silent_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_creator_or_role(interaction.user):
            await interaction.response.send_message("Нет прав удалять кнопки.", ephemeral=True)
            return

        confirm_view = ConfirmDeleteView(self)
        warning_embed = discord.Embed(
            description=(
                "Внимание! Вы закрываете запись!\n"
                "Кнопки будут удалены. Записаться вновь будет невозможно.\n"
                "Участники более не смогут покинуть запись."
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(
            embed=warning_embed, view=confirm_view, ephemeral=True
        )


class ConfirmDeleteView(View):
    def __init__(self, signup_view: SignUpView):
        super().__init__(timeout=60)
        self.signup_view = signup_view

    @discord.ui.button(label="Да. Я понимаю.", style=discord.ButtonStyle.secondary)
    @signup_mutation
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.signup_view.is_creator_or_role(interaction.user):
            await interaction.response.send_message("Нет прав удалять кнопки.", ephemeral=True)
            return

        self.signup_view.closed = True
        await self.signup_view.persist(no_buttons=True)
        await self.signup_view.message.edit(
            content=self.signup_view.content + f"\n⚠️ {CLOSE_MARKER}",
            embed=self.signup_view.build_embed(),
            view=None,
        )
        await interaction.response.edit_message(
            content="Кнопки удалены. Запись закрыта.", embed=None, view=None
        )

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Отменено.", embed=None, view=None)


class Bronya(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="броня", description="Открыть запись на контракт")
    async def броня(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild and not any(
            role.id == ROLE_ID for role in interaction.user.roles
        ):
            await interaction.response.send_message(
                "У тебя нет прав открывать запись.", ephemeral=True
            )
            return

        await interaction.response.send_modal(SignUpModal(interaction, self.bot))

    async def cog_load(self):
        guild = discord.Object(id=GUILD_ID)
        self.bot.tree.add_command(self.броня, guild=guild)
        self.restore_task = self.bot.spawn(self.restore_signups(), name="restore-bronya")

    async def restore_signups(self):
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(CHANNEL_ID)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        state = StateRepository()
        imported = await state.get(GUILD_ID, "imports", "bronya")
        saved = await state.all("bronya")
        for row in saved:
            if row["guild_id"] != GUILD_ID or row["value"].get("no_buttons"):
                continue
            data = row["value"]
            try:
                message = await channel.fetch_message(int(row["key"]))
            except discord.NotFound:
                continue
            view = SignUpView(
                creator=discord.Object(id=data["creator_id"]),
                max_participants=data["max_participants"],
                content=data["content"],
                participants=[
                    message.guild.get_member(uid) or discord.Object(id=uid)
                    for uid in data["participants"]
                ],
                closed=data["closed"],
                message=message,
            )
            self.bot.add_view(view, message_id=message.id)
        if imported:
            return
        async for message in channel.history(limit=None):
            if message.author.id != self.bot.user.id:
                continue
            if await state.get(GUILD_ID, "bronya", message.id):
                continue
            if (
                not message.components
                or not message.embeds
                or message.embeds[0].title != EMBED_TITLE
            ):
                continue

            max_participants = self._parse_max_participants(message.content)
            creator = self._parse_creator(message)
            participants = self._parse_participants(message)
            closed = CLOSE_MARKER in message.content or (
                message.embeds[0].footer and message.embeds[0].footer.text == CLOSE_MARKER
            )

            view = SignUpView(
                creator=creator or message.author,
                max_participants=max_participants or max(len(participants), 1),
                content=message.content,
                participants=participants,
                closed=closed,
                message=message,
            )

            await view.persist()
            self.bot.add_view(view, message_id=message.id)
        await state.put(GUILD_ID, "imports", "bronya", True)

    def _parse_max_participants(self, content: str) -> int | None:
        match = re.search(r"Максимальное количество участников:\s*(\d+)", content)
        return int(match.group(1)) if match else None

    def _parse_creator(self, message: discord.Message) -> discord.abc.User | None:
        match = re.search(r"<@!?(\d+)>", message.content)
        if not match:
            return None
        user_id = int(match.group(1))
        if message.guild:
            member = message.guild.get_member(user_id)
            if member:
                return member
        return self.bot.get_user(user_id) or discord.Object(id=user_id)

    def _parse_participants(self, message: discord.Message) -> list[discord.abc.User]:
        if not message.embeds or not message.embeds[0].fields:
            return []
        field = message.embeds[0].fields[0]
        ids = re.findall(r"<@!?(\d+)>", field.value or "")
        participants: list[discord.abc.User] = []
        for user_id in ids:
            uid = int(user_id)
            member = message.guild.get_member(uid) if message.guild else None
            participants.append(member or self.bot.get_user(uid) or discord.Object(id=uid))
        return participants


async def setup(bot: commands.Bot):
    await bot.add_cog(Bronya(bot))
