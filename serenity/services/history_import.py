"""Adopt pending pre-migration Discord requests and repair interrupted publication."""

import logging
import re

import discord

from serenity.config import get_settings
from serenity.repositories.requests import RequestRepository
from serenity.repositories.state import StateRepository
from serenity.services.workflows import promotion_target, publish_request
from serenity.ui.requests import RequestView

log = logging.getLogger(__name__)


async def import_pending_requests(bot):
    await bot.wait_until_ready()
    settings = get_settings()
    repo = RequestRepository()
    state = StateRepository()
    for channel_id in (settings.application_channel_id, settings.promotion_channel_id):
        if await state.get(settings.guild_id, "imports", f"requests:{channel_id}"):
            continue
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        async for message in channel.history(limit=None):
            if message.author.id != bot.user.id or not message.components or not message.embeds:
                continue
            if await repo.pool.fetchval(
                "SELECT id FROM public.requests WHERE message_id=$1", message.id
            ):
                continue
            embed = message.embeds[0]
            if not embed.fields:
                continue
            title = embed.title or ""
            if "Новая заявка на вступление" in title:
                kind = "application"
            elif "Отчёт на Повышение" in title:
                kind = "promotion"
            elif "Смена Фамилии" in title:
                kind = "name_change"
            else:
                continue
            combined = (
                message.content
                + " "
                + (embed.description or "")
                + " "
                + " ".join(field.value for field in embed.fields)
            )
            match = re.search(r"<@!?(\d+)>", combined)
            if match is None:
                continue
            user_id = int(match[1])
            payload = {"legacy_embed": embed.to_dict(), "legacy_content": message.content}
            if kind in ("promotion", "name_change"):
                member = message.guild.get_member(user_id)
                try:
                    member = member or await message.guild.fetch_member(user_id)
                    payload["target_role_id"] = promotion_target(member, settings.rank_role_ids)
                except (discord.NotFound, ValueError):
                    payload["target_role_id"] = None
            row, created = await repo.create(settings.guild_id, user_id, kind, payload)
            if not created:
                # Keep the newest pending request; older messages remain available for manual review.
                continue
            await repo.attach_message(row["id"], channel_id, message.id)
            await message.edit(view=RequestView(row["id"]))
            log.info("Adopted pending %s request message=%s", kind, message.id)
        await state.put(settings.guild_id, "imports", f"requests:{channel_id}", True)


async def recover_request_messages(bot):
    await bot.wait_until_ready()
    settings = get_settings()
    channels = {
        "application": settings.application_channel_id,
        "promotion": settings.promotion_channel_id,
        "name_change": settings.promotion_channel_id,
        "bonus": settings.bonus_channel_id,
    }
    repo = RequestRepository()
    for row in await repo.pending(list(channels)):
        channel = bot.get_channel(row["channel_id"] or channels[row["kind"]])
        if channel is None:
            continue
        if row["message_id"]:
            if "legacy_embed" in row["payload"]:
                try:
                    message = await channel.fetch_message(row["message_id"])
                    ids = [
                        getattr(item, "custom_id", "") or ""
                        for component in message.components
                        for item in component.children
                    ]
                    if not any(value.startswith("request:") for value in ids):
                        await message.edit(view=RequestView(row["id"]))
                except discord.NotFound:
                    log.info("Legacy request message was deleted id=%s", row["id"])
            # Register the persisted view without editing existing messages on every restart.
            bot.add_view(RequestView(row["id"]), message_id=row["message_id"])
            continue
        await publish_request(bot, repo, row["id"], channel)
