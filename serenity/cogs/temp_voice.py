import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

import discord
from discord import app_commands
from discord.ext import commands, tasks

from serenity.config import get_settings
from serenity.repositories.state import StateRepository
from serenity.services.serialization import channel_mutation
from serenity.services.voice_state import load_channels, reconcile_channels, save_channel
from serenity.ui.base import Modal, View

settings = get_settings()

TEMP_VOICE_TRIGGER_CHANNEL_ID = settings.temp_voice_trigger_channel_id  # ID триггер-канала
TEMP_VOICE_CATEGORY_ID = (
    settings.temp_voice_category_id
)  # ID категории для временных каналов (0 = без категории)
TEMP_VOICE_ALLOWED_ROLE_ID = (
    settings.temp_voice_allowed_role_id
)  # Allowed role for default temp voice access
TEMP_VOICE_DEFAULT_NAME = settings.temp_voice_default_name
TEMP_VOICE_DEFAULT_LIMIT = (
    settings.temp_voice_default_limit or None
)  # например 5, или None для без лимита
TEMP_VOICE_GUILD_ID = settings.temp_voice_guild_id  # ID сервера (0 = без ограничения)

logger = logging.getLogger("temp_voice")


def _log_exception(message: str, error: Exception) -> None:
    logger.exception("%s: %s", message, error)
    logging.getLogger(__name__).info(str(f"[temp_voice] {message}: {error}"))


@dataclass
class TempVoiceChannelInfo:
    owner_id: int
    blocked_users: Set[int] = field(default_factory=set)
    allowed_users: Set[int] = field(default_factory=set)
    user_limit: Optional[int] = None
    is_locked: bool = False
    is_hidden: bool = False


active_channels: Dict[int, TempVoiceChannelInfo] = {}


def is_trigger(guild_id: int, channel_id: Optional[int]) -> bool:
    if not TEMP_VOICE_TRIGGER_CHANNEL_ID or channel_id is None:
        return False
    if TEMP_VOICE_GUILD_ID and guild_id != TEMP_VOICE_GUILD_ID:
        return False
    return TEMP_VOICE_TRIGGER_CHANNEL_ID == channel_id


async def create_temp_voice_channel(
    member: discord.Member,
    trigger_channel_id: int,
) -> Optional[discord.VoiceChannel]:
    if not is_trigger(member.guild.id, trigger_channel_id):
        return None

    category = None
    if TEMP_VOICE_CATEGORY_ID:
        channel = member.guild.get_channel(TEMP_VOICE_CATEGORY_ID)
        if isinstance(channel, discord.CategoryChannel):
            category = channel

    channel_name = TEMP_VOICE_DEFAULT_NAME.replace("{user}", member.display_name)
    overwrites = {
        member: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            manage_channels=True,
            move_members=True,
            mute_members=True,
            deafen_members=True,
        ),
        member.guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            connect=False,
        ),
    }
    allowed_role = member.guild.get_role(TEMP_VOICE_ALLOWED_ROLE_ID)
    if allowed_role is not None:
        overwrites[allowed_role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
        )

    channel = await member.guild.create_voice_channel(
        name=channel_name,
        category=category,
        user_limit=TEMP_VOICE_DEFAULT_LIMIT or 0,
        overwrites=overwrites,
    )

    active_channels[channel.id] = TempVoiceChannelInfo(
        owner_id=member.id,
        user_limit=TEMP_VOICE_DEFAULT_LIMIT,
        is_locked=False,
        is_hidden=False,
    )
    await save_channel(channel, active_channels[channel.id])
    return channel


def get_channel_info(channel_id: int) -> Optional[TempVoiceChannelInfo]:
    return active_channels.get(channel_id)


def is_channel_owner(channel_id: int, user_id: int) -> bool:
    info = active_channels.get(channel_id)
    return info is not None and info.owner_id == user_id


def _can_manage_channel(member: discord.Member, info: TempVoiceChannelInfo) -> bool:
    return member.guild_permissions.manage_channels or member.id == info.owner_id


def _get_member_voice_channel(member: discord.Member) -> Optional[discord.VoiceChannel]:
    channel = member.voice.channel if member.voice else None
    return channel if isinstance(channel, discord.VoiceChannel) else None


async def _resolve_user_channel(
    interaction: discord.Interaction,
) -> Optional[Tuple[discord.VoiceChannel, TempVoiceChannelInfo]]:
    if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
        await interaction.response.send_message(
            "Команда доступна только на сервере.", ephemeral=True
        )
        return None

    channel = _get_member_voice_channel(interaction.user)
    if channel is None:
        await interaction.response.send_message(
            "Сначала зайди в свой временный голосовой канал.",
            ephemeral=True,
        )
        return None

    info = active_channels.get(channel.id)
    if not info:
        await interaction.response.send_message(
            "Это не временный голосовой канал.",
            ephemeral=True,
        )
        return None

    if not _can_manage_channel(interaction.user, info):
        await interaction.response.send_message(
            "У тебя нет прав управлять этим каналом.",
            ephemeral=True,
        )
        return None

    return channel, info


class RenameTempVoiceModal(Modal, title="Переименовать канал"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id
        self.new_name = discord.ui.TextInput(
            label="Новое название",
            max_length=100,
        )
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.followup.send("Канал не найден.", ephemeral=True)
            return

        info = active_channels.get(channel.id)
        if not info or not _can_manage_channel(interaction.user, info):
            await interaction.followup.send(
                "У тебя нет прав управлять этим каналом.",
                ephemeral=True,
            )
            return

        ok = await rename_channel(channel, str(self.new_name.value).strip())
        if ok:
            await interaction.followup.send("Канал переименован.", ephemeral=True)
        else:
            await interaction.followup.send("Не удалось переименовать канал.", ephemeral=True)


class TransferTempVoiceModal(Modal, title="Передать владельца"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id
        self.target = discord.ui.TextInput(
            label="Участник (ID или @упоминание)",
            max_length=64,
        )
        self.add_item(self.target)

    @staticmethod
    def _extract_user_id(raw: str) -> Optional[int]:
        raw = raw.strip()
        if raw.isdigit():
            return int(raw)
        match = re.match(r"<@!?(\d+)>", raw)
        if match:
            return int(match.group(1))
        return None

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.followup.send("Канал не найден.", ephemeral=True)
            return

        info = active_channels.get(channel.id)
        if not info or not _can_manage_channel(interaction.user, info):
            await interaction.followup.send(
                "У тебя нет прав управлять этим каналом.",
                ephemeral=True,
            )
            return

        user_id = self._extract_user_id(str(self.target.value))
        if not user_id:
            await interaction.followup.send("Неверный формат пользователя.", ephemeral=True)
            return

        new_owner = interaction.guild.get_member(user_id)
        if not new_owner:
            try:
                new_owner = await interaction.guild.fetch_member(user_id)
            except Exception as e:
                _log_exception("Не удалось получить участника для передачи владельца", e)
                await interaction.followup.send("Участник не найден.", ephemeral=True)
                return

        if new_owner.id == interaction.user.id:
            await interaction.followup.send("Ты уже владелец канала.", ephemeral=True)
            return

        if new_owner not in channel.members:
            await interaction.followup.send(
                "Новый владелец должен быть в этом голосовом канале.",
                ephemeral=True,
            )
            return

        ok = await transfer_ownership(channel, new_owner)
        if ok:
            await interaction.followup.send(
                f"Владелец канала передан {new_owner.mention}.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send("Не удалось передать владельца.", ephemeral=True)


class AllowTempVoiceModal(Modal, title="Разрешить доступ"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id
        self.target = discord.ui.TextInput(
            label="Пользователь (ID или @упоминание)",
            max_length=64,
        )
        self.add_item(self.target)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.followup.send("Канал не найден.", ephemeral=True)
            return

        info = active_channels.get(channel.id)
        if not info or not _can_manage_channel(interaction.user, info):
            await interaction.followup.send(
                "У тебя нет прав управлять этим каналом.",
                ephemeral=True,
            )
            return

        user_id = TransferTempVoiceModal._extract_user_id(str(self.target.value))
        if not user_id:
            await interaction.followup.send("Неверный формат пользователя.", ephemeral=True)
            return

        member = interaction.guild.get_member(user_id)
        if not member:
            try:
                member = await interaction.guild.fetch_member(user_id)
            except Exception as e:
                _log_exception("Не удалось получить участника для разрешения доступа", e)
                await interaction.followup.send("Участник не найден.", ephemeral=True)
                return

        ok = await allow_user(channel, member)
        if ok:
            await interaction.followup.send("Доступ разрешён.", ephemeral=True)
        else:
            await interaction.followup.send("Не удалось разрешить доступ.", ephemeral=True)


class BlockTempVoiceModal(Modal, title="Запретить доступ"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id
        self.target = discord.ui.TextInput(
            label="Пользователь (ID или @упоминание)",
            max_length=64,
        )
        self.add_item(self.target)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.followup.send("Канал не найден.", ephemeral=True)
            return

        info = active_channels.get(channel.id)
        if not info or not _can_manage_channel(interaction.user, info):
            await interaction.followup.send(
                "У тебя нет прав управлять этим каналом.",
                ephemeral=True,
            )
            return

        user_id = TransferTempVoiceModal._extract_user_id(str(self.target.value))
        if not user_id:
            await interaction.followup.send("Неверный формат пользователя.", ephemeral=True)
            return

        member = interaction.guild.get_member(user_id)
        if not member:
            try:
                member = await interaction.guild.fetch_member(user_id)
            except Exception as e:
                _log_exception("Не удалось получить участника для запрета доступа", e)
                await interaction.followup.send("Участник не найден.", ephemeral=True)
                return

        ok = await block_user(channel, member)
        if ok:
            await interaction.followup.send("Доступ запрещён.", ephemeral=True)
        else:
            await interaction.followup.send("Не удалось запретить доступ.", ephemeral=True)


class LimitTempVoiceModal(Modal, title="Лимит участников"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id
        self.limit = discord.ui.TextInput(
            label="Лимит (0 = без лимита)",
            max_length=3,
        )
        self.add_item(self.limit)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.followup.send("Канал не найден.", ephemeral=True)
            return

        info = active_channels.get(channel.id)
        if not info or not _can_manage_channel(interaction.user, info):
            await interaction.followup.send(
                "У тебя нет прав управлять этим каналом.",
                ephemeral=True,
            )
            return

        raw = str(self.limit.value).strip()
        if not raw.isdigit():
            await interaction.followup.send("Лимит должен быть числом.", ephemeral=True)
            return

        value = int(raw)
        if value < 0 or value > 99:
            await interaction.followup.send("Лимит должен быть от 0 до 99.", ephemeral=True)
            return

        limit = None if value == 0 else value
        ok = await set_user_limit(channel, limit)
        if ok:
            await interaction.followup.send("Лимит обновлён.", ephemeral=True)
        else:
            await interaction.followup.send("Не удалось обновить лимит.", ephemeral=True)


class TempVoicePanelView(View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        _log_exception("TempVoicePanelView error", error)

    @discord.ui.button(
        label=" ",
        style=discord.ButtonStyle.secondary,
        custom_id="tempvoice-lock",
        emoji="🔒",
        row=0,
    )
    async def lock_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        resolved = await _resolve_user_channel(interaction)
        if not resolved:
            return
        channel, info = resolved

        ok = await toggle_lock(channel)
        if ok:
            status = "Канал закрыт." if info.is_locked else "Канал открыт."
            await interaction.response.send_message(status, ephemeral=True)
        else:
            await interaction.response.send_message("Не удалось изменить доступ.", ephemeral=True)

    @discord.ui.button(
        label=" ",
        style=discord.ButtonStyle.secondary,
        custom_id="tempvoice-hide",
        emoji="👁️",
        row=0,
    )
    async def hide_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        resolved = await _resolve_user_channel(interaction)
        if not resolved:
            return
        channel, info = resolved

        ok = await toggle_hide(channel)
        if ok:
            status = "Канал скрыт." if info.is_hidden else "Канал открыт для просмотра."
            await interaction.response.send_message(status, ephemeral=True)
        else:
            await interaction.response.send_message(
                "Не удалось изменить видимость.", ephemeral=True
            )

    @discord.ui.button(
        label=" ",
        style=discord.ButtonStyle.secondary,
        custom_id="tempvoice-limit",
        emoji="👥",
        row=0,
    )
    async def limit_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        resolved = await _resolve_user_channel(interaction)
        if not resolved:
            return
        channel, _ = resolved
        await interaction.response.send_modal(LimitTempVoiceModal(channel.id))

    @discord.ui.button(
        label=" ",
        style=discord.ButtonStyle.secondary,
        custom_id="tempvoice-rename",
        emoji="✏️",
        row=0,
    )
    async def rename_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        resolved = await _resolve_user_channel(interaction)
        if not resolved:
            return
        channel, _ = resolved
        await interaction.response.send_modal(RenameTempVoiceModal(channel.id))

    @discord.ui.button(
        label=" ",
        style=discord.ButtonStyle.secondary,
        custom_id="tempvoice-transfer",
        emoji="👑",
        row=1,
    )
    async def transfer_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        resolved = await _resolve_user_channel(interaction)
        if not resolved:
            return
        channel, _ = resolved
        await interaction.response.send_modal(TransferTempVoiceModal(channel.id))

    @discord.ui.button(
        label=" ",
        style=discord.ButtonStyle.secondary,
        custom_id="tempvoice-allow",
        emoji="➕",
        row=1,
    )
    async def allow_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        resolved = await _resolve_user_channel(interaction)
        if not resolved:
            return
        channel, _ = resolved
        await interaction.response.send_modal(AllowTempVoiceModal(channel.id))

    @discord.ui.button(
        label=" ",
        style=discord.ButtonStyle.secondary,
        custom_id="tempvoice-block",
        emoji="⛔",
        row=1,
    )
    async def block_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        resolved = await _resolve_user_channel(interaction)
        if not resolved:
            return
        channel, _ = resolved
        await interaction.response.send_modal(BlockTempVoiceModal(channel.id))


@channel_mutation
async def rename_channel(channel: discord.VoiceChannel, new_name: str) -> bool:
    try:
        await channel.edit(name=new_name)
        if channel.id in active_channels:
            await save_channel(channel, active_channels[channel.id])
        return True
    except Exception as e:
        _log_exception("Не удалось переименовать канал", e)
        return False


@channel_mutation
async def set_user_limit(channel: discord.VoiceChannel, limit: Optional[int]) -> bool:
    try:
        await channel.edit(user_limit=limit or 0)
        info = active_channels.get(channel.id)
        if info:
            info.user_limit = limit
        if channel.id in active_channels:
            await save_channel(channel, active_channels[channel.id])
        return True
    except Exception as e:
        _log_exception("Не удалось обновить лимит", e)
        return False


@channel_mutation
async def toggle_lock(channel: discord.VoiceChannel) -> bool:
    info = active_channels.get(channel.id)
    if not info:
        return False
    try:
        new_locked = not info.is_locked
        target = channel.guild.get_role(TEMP_VOICE_ALLOWED_ROLE_ID) or channel.guild.default_role
        overwrite = channel.overwrites_for(target)
        overwrite.connect = not new_locked
        await channel.set_permissions(target, overwrite=overwrite)
        info.is_locked = new_locked
        if channel.id in active_channels:
            await save_channel(channel, active_channels[channel.id])
        return True
    except Exception as e:
        _log_exception("Не удалось изменить доступ", e)
        return False


@channel_mutation
async def toggle_hide(channel: discord.VoiceChannel) -> bool:
    info = active_channels.get(channel.id)
    if not info:
        return False
    try:
        new_hidden = not info.is_hidden
        target = channel.guild.get_role(TEMP_VOICE_ALLOWED_ROLE_ID) or channel.guild.default_role
        overwrite = channel.overwrites_for(target)
        overwrite.view_channel = not new_hidden
        await channel.set_permissions(target, overwrite=overwrite)
        info.is_hidden = new_hidden
        if channel.id in active_channels:
            await save_channel(channel, active_channels[channel.id])
        return True
    except Exception as e:
        _log_exception("Не удалось изменить видимость", e)
        return False


@channel_mutation
async def block_user(channel: discord.VoiceChannel, member: discord.Member) -> bool:
    info = active_channels.get(channel.id)
    if not info:
        return False
    try:
        info.blocked_users.add(member.id)
        info.allowed_users.discard(member.id)
        await channel.set_permissions(member, view_channel=False, connect=False)
        if channel.id in active_channels:
            await save_channel(channel, active_channels[channel.id])
        return True
    except Exception as e:
        _log_exception("Не удалось заблокировать пользователя", e)
        return False


@channel_mutation
async def allow_user(channel: discord.VoiceChannel, member: discord.Member) -> bool:
    info = active_channels.get(channel.id)
    if not info:
        return False
    try:
        info.allowed_users.add(member.id)
        info.blocked_users.discard(member.id)
        await channel.set_permissions(member, view_channel=True, connect=True)
        if channel.id in active_channels:
            await save_channel(channel, active_channels[channel.id])
        return True
    except Exception as e:
        _log_exception("Не удалось разрешить доступ пользователю", e)
        return False


@channel_mutation
async def transfer_ownership(channel: discord.VoiceChannel, new_owner: discord.Member) -> bool:
    info = active_channels.get(channel.id)
    if not info:
        return False
    try:
        old_owner_id = info.owner_id
        old_owner = channel.guild.get_member(old_owner_id)
        old_target = old_owner or await channel.guild.fetch_member(old_owner_id)
        await channel.set_permissions(
            old_target,
            overwrite=discord.PermissionOverwrite(
                manage_channels=False,
                move_members=False,
                mute_members=False,
                deafen_members=False,
            ),
        )
        await channel.set_permissions(
            new_owner,
            overwrite=discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                manage_channels=True,
                move_members=True,
                mute_members=True,
                deafen_members=True,
            ),
        )
        info.owner_id = new_owner.id
        if channel.id in active_channels:
            await save_channel(channel, active_channels[channel.id])
        return True
    except Exception as e:
        _log_exception("Не удалось передать владельца", e)
        return False


@channel_mutation
async def delete_channel(channel: discord.VoiceChannel) -> bool:
    try:
        try:
            await channel.delete()
        except discord.NotFound:
            pass
        await StateRepository().delete(channel.guild.id, "voice", channel.id)
        active_channels.pop(channel.id, None)
        if channel.id in active_channels:
            await save_channel(channel, active_channels[channel.id])
        return True
    except Exception as e:
        _log_exception("Не удалось удалить канал", e)
        return False


async def cleanup_empty_channels(bot: commands.Bot) -> None:
    for channel_id in list(active_channels.keys()):
        channel = bot.get_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            active_channels.pop(channel_id, None)
            continue
        if len(channel.members) == 0:
            await delete_channel(channel)


class TempVoice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cleanup_task.start()

    async def cog_load(self):
        await load_channels(active_channels, TempVoiceChannelInfo)
        self.bot.add_view(TempVoicePanelView(self.bot))
        if TEMP_VOICE_GUILD_ID:
            guild = discord.Object(id=TEMP_VOICE_GUILD_ID)
            self.bot.tree.add_command(self.temp_voice_panel, guild=guild)

    def cog_unload(self):
        self.cleanup_task.cancel()

    @tasks.loop(minutes=5)
    async def cleanup_task(self):
        await cleanup_empty_channels(self.bot)

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()
        await reconcile_channels(self.bot, active_channels, TempVoiceChannelInfo)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        try:
            if after.channel and is_trigger(member.guild.id, after.channel.id):
                temp_channel = await create_temp_voice_channel(member, after.channel.id)
                if temp_channel:
                    try:
                        await member.move_to(temp_channel)
                    except Exception:
                        logging.getLogger(__name__).exception("Optional Discord action failed")

            if before.channel and before.channel.id in active_channels:
                if len(before.channel.members) == 0:
                    channel = before.channel

                    async def delayed_delete():
                        await asyncio.sleep(30)
                        refreshed = self.bot.get_channel(channel.id)
                        if (
                            isinstance(refreshed, discord.VoiceChannel)
                            and len(refreshed.members) == 0
                        ):
                            await delete_channel(refreshed)

                    self.bot.spawn(delayed_delete(), name="voice-delete")
        except Exception as e:
            _log_exception("Ошибка в обработчике on_voice_state_update", e)

    @app_commands.command(
        name="войс",
        description="Создать панель управления временными голосовыми каналами",
    )
    async def temp_voice_panel(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "Недостаточно прав для этой команды.", ephemeral=True
            )
            return

        view = TempVoicePanelView(self.bot)
        embed = discord.Embed(
            title="Панель управление приватными комнатами",
            description=(
                "Как использовать?\n"
                f"1. Зайдите в <#{TEMP_VOICE_TRIGGER_CHANNEL_ID}> для создания временного канала.\n"
                "2. Используйте кнопки ниже для управления вашим каналом.\n\n"
                f"{settings.voice_settings_emoji} Настройки канала:\n\n"
                "✏️ - Изменить название канала\n"
                "👥 - Установить максимальный лимит участников (0 = без лимита)\n"
                "🔒 - Закрыть или открыть доступ для всех\n"
                "👁️ - Сделать канал скрытым или открытым для всех\n\n"
                "👥 Управление участниками:\n\n"
                "➕ - Разрешить доступ конкретному пользователю\n"
                "⛔ - Запретить доступ конкретному пользователю\n"
                "👑 - Передать права владельца другому участнику\n\n"
                f"{settings.voice_footer_emoji} **Канал автоматически удалится через 30 секунд после того, как все участники покинут его**"
            ),
            color=discord.Color.from_rgb(255, 255, 255),
        )
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(TempVoice(bot))
