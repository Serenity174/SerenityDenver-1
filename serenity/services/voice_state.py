from dataclasses import asdict

import discord

from serenity.config import get_settings
from serenity.repositories.state import StateRepository


async def save_channel(channel, info):
    value = asdict(info)
    value["allowed_users"] = sorted(info.allowed_users)
    value["blocked_users"] = sorted(info.blocked_users)
    await StateRepository().put(channel.guild.id, "voice", channel.id, value)


async def load_channels(active, info_type):
    active.clear()
    for row in await StateRepository().all("voice"):
        value = dict(row["value"])
        value["allowed_users"] = set(value.get("allowed_users", []))
        value["blocked_users"] = set(value.get("blocked_users", []))
        active[int(row["key"])] = info_type(**value)


async def reconcile_channels(bot, active, info_type):
    settings = get_settings()
    state = StateRepository()
    for row in await state.all("voice"):
        channel = bot.get_channel(int(row["key"]))
        if channel is None:
            try:
                await bot.fetch_channel(int(row["key"]))
            except discord.NotFound:
                await state.delete(row["guild_id"], "voice", row["key"])
                active.pop(int(row["key"]), None)
            except discord.Forbidden:
                continue
    for guild in bot.guilds:
        if settings.temp_voice_guild_id and guild.id != settings.temp_voice_guild_id:
            continue
        for channel in guild.voice_channels:
            if channel.id == settings.temp_voice_trigger_channel_id:
                continue
            if channel.id not in active and (
                not settings.temp_voice_category_id
                or channel.category_id != settings.temp_voice_category_id
            ):
                continue
            owners = [
                member.id
                for member, overwrite in channel.overwrites.items()
                if isinstance(member, discord.Member) and overwrite.manage_channels is True
            ]
            if len(owners) != 1:
                continue
            info = active.get(channel.id) or info_type(owner_id=owners[0])
            info.owner_id = owners[0]
            info.user_limit = channel.user_limit or None
            allowed_role = guild.get_role(settings.temp_voice_allowed_role_id)
            if allowed_role:
                permissions = channel.overwrites_for(allowed_role)
                info.is_locked = permissions.connect is False
                info.is_hidden = permissions.view_channel is False
            info.allowed_users = {
                m.id
                for m, p in channel.overwrites.items()
                if isinstance(m, discord.Member) and p.connect is True and m.id != info.owner_id
            }
            info.blocked_users = {
                m.id
                for m, p in channel.overwrites.items()
                if isinstance(m, discord.Member) and p.connect is False
            }
            active[channel.id] = info
            await save_channel(channel, info)
